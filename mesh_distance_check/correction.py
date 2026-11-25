"""Deform evaluated copies and validate the candidate assembly before publishing it."""

from time import monotonic

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import geometry


class CorrectionError(Exception):
    pass


def normals_for(points, faces):
    normals = []
    for i, j, k in faces:
        normal = (points[j] - points[i]).cross(points[k] - points[i])
        normals.append(normal.normalized())
    return normals


class Component:
    def __init__(self, obj, mesh, matrix):
        self.obj, self.mesh = obj, mesh
        self.matrix = Matrix.LocRotScale(*matrix.decompose())
        self.inverse = self.matrix.inverted()
        # A standalone object stores location, rotation and scale. Bake any
        # residual shear from the evaluated parent transform into its mesh.
        if matrix != self.matrix:
            mesh.transform(self.inverse @ matrix)
        self.points = [self.matrix @ vert.co for vert in mesh.vertices]
        self.original_points = list(self.points)
        mesh.calc_loop_triangles()
        self.faces = [tuple(face.vertices) for face in mesh.loop_triangles]
        self.normals = normals_for(self.points, self.faces)

    def triangles(self):
        return [tuple(self.points[i] for i in face) for face in self.faces]

    def tree(self):
        return BVHTree.FromPolygons(self.points, self.faces, all_triangles=True)


def is_closed(component):
    mesh = bmesh.new()
    try:
        mesh.from_mesh(component.mesh)
        return (all(edge.is_manifold and edge.is_contiguous for edge in mesh.edges)
                and all(vert.is_manifold for vert in mesh.verts))
    finally:
        mesh.free()


def check_thickness(component, minimum, affected):
    triangles = component.triangles()
    face_normals = normals_for(component.points, component.faces)
    normals = {id(triangle): normal for triangle, normal in zip(triangles, face_normals)}
    tree = component.tree()
    offset = minimum * 0.0001
    closed = is_closed(component)
    ray_limit = minimum - offset if closed else float("inf")
    for index in affected:
        yield
        a, b, c = triangles[index]
        normal = face_normals[index]
        # Sample inside each face as an additional guard on slanted walls.
        for point in ((a + b + c) / 3, (a * 4 + b + c) / 6,
                      (a + b * 4 + c) / 6, (a + b + c * 4) / 6):
            _, _, hit, distance = tree.ray_cast(point - normal * offset, -normal, ray_limit)
            opposite = hit is not None and normal.dot(face_normals[hit]) < -0.15
            if opposite and distance + offset < minimum:
                raise CorrectionError(f"{component.obj.name}: spessore sotto 1 mm lungo una parete.")
            if not closed and not opposite:
                raise CorrectionError(
                    f"{component.obj.name}: parete opposta assente o non verificabile nella zona deformata."
                )
    pending = [(geometry.Node([triangles[i] for i in affected]), geometry.Node(triangles))]
    squared = minimum ** 2
    while pending:
        yield
        a, b = pending.pop()
        if geometry.bounds_distance_squared(a, b) >= squared:
            continue
        if a.count > 4 and a.count >= b.count:
            pending.extend((child, b) for child in a.split())
        elif b.count > 4:
            pending.extend((a, child) for child in b.split())
        else:
            for first in a.triangles:
                for second in b.triangles:
                    if normals[id(first)].dot(normals[id(second)]) > -0.5:
                        continue
                    pair = geometry.closest_triangles(first, second)
                    if geometry.distance_squared(pair) < squared:
                        raise CorrectionError(
                            f"{component.obj.name}: pareti contrapposte sotto 1 mm."
                        )


def check_surface(component, affected, check_orientation=True):
    normals = normals_for(component.points, component.faces)
    if any(normals[i].length_squared == 0 for i in affected):
        raise CorrectionError(f"{component.obj.name}: facce degeneri nella zona deformata.")
    if check_orientation and any(component.normals[i].dot(normals[i]) <= 0 for i in affected):
        raise CorrectionError(f"{component.obj.name}: la correzione ribalta una faccia.")

    changed = [component.faces[i] for i in affected]
    changed_tree = BVHTree.FromPolygons(component.points, changed, all_triangles=True)
    for a, b in changed_tree.overlap(component.tree()):
        if set(changed[a]).isdisjoint(component.faces[b]):
            raise CorrectionError(f"{component.obj.name}: la zona deformata si interseca con la mesh.")


def violation(components, target):
    triangles = [component.triangles() for component in components]
    result = yield from geometry.search_components(triangles, cutoff=target)
    if result is None:
        return None
    faces, points = result
    owners = {}
    for component_index, (component, surface) in enumerate(zip(components, triangles)):
        for index, triangle in enumerate(surface):
            if triangle is faces[0] or triangle is faces[1]:
                owners[id(triangle)] = component_index, component.faces[index]
    return [owners[id(face)] for face in faces], points


def keep_push(deltas, indices, delta):
    for vertex in indices:
        previous = deltas.get(vertex)
        if previous is None or delta.length_squared > previous.length_squared:
            deltas[vertex] = delta


def displacements(component, index, trees, goal):
    targets = [tree for other, tree in enumerate(trees) if other != index]
    deltas, seen_vertices = {}, set()

    def push(point, indices):
        match = geometry.nearest_component(point, enumerate(targets), goal)
        if match is None or match[2] >= goal:
            return
        _, nearest, distance = match
        if distance == 0:
            raise CorrectionError("Le superfici si toccano durante la correzione.")
        delta = (point - nearest).normalized() * ((goal - distance) * 0.55)
        keep_push(deltas, indices, delta)

    for face in component.faces:
        yield
        a, b, c = (component.points[vertex] for vertex in face)
        center = (a + b + c) / 3
        radius = max((point - center).length for point in (a, b, c))
        reach = (goal + radius) * 1.000001
        if not any(tree.find_nearest(center, reach)[0] is not None for tree in targets):
            continue
        for vertex in face:
            if vertex not in seen_vertices:
                push(component.points[vertex], (vertex,))
                seen_vertices.add(vertex)
        push(center, face)
    return deltas


def adjust(components, target, minimum):
    current = yield from violation(components, target)
    if current is None:
        return False

    goal = target + minimum * 0.002
    for _ in range(12):
        owners, (start, end) = current
        direction = start - end
        distance = direction.length
        if distance == 0:
            raise CorrectionError("Le mesh si toccano o si intersecano. Separale leggermente prima di correggerle.")

        trees = []
        for component in components:
            yield
            trees.append(component.tree())
        changes = []
        for index, component in enumerate(components):
            changes.append((yield from displacements(component, index, trees, goal)))

        # The exact violating points can lie between every vertex and centroid.
        # Push both supporting faces even when the samples miss the narrow gap.
        delta = direction.normalized() * ((goal - distance) * 0.55)
        for (index, face), push in zip(owners, (delta, -delta)):
            keep_push(changes[index], face, push)

        for component, deltas in zip(components, changes):
            for index, push in deltas.items():
                yield
                vertex = component.mesh.vertices[index]
                vertex.co = component.inverse @ (component.points[index] + push)
                component.points[index] = component.matrix @ vertex.co

        current = yield from violation(components, target)
        if current is None:
            break
    else:
        raise CorrectionError("La soglia non è raggiungibile con questa correzione locale.")

    for component in components:
        yield
        moved = {i for i, (old, new) in enumerate(
            zip(component.original_points, component.points)
        ) if old != new}
        affected = {i for i, face in enumerate(component.faces) if moved.intersection(face)}
        if not affected:
            continue
        check_surface(component, affected)
        yield
        component.mesh.update()
        component.mesh.calc_loop_triangles()
        component.faces = [tuple(face.vertices) for face in component.mesh.loop_triangles]
        affected = {i for i, face in enumerate(component.faces) if moved.intersection(face)}
        check_surface(component, affected, check_orientation=False)
        yield from check_thickness(component, minimum, affected)

    if (yield from violation(components, target)) is not None:
        raise CorrectionError("La geometria finale non rispetta la distanza richiesta.")
    return True


class CorrectionJob:
    def __init__(self, context, objects, target, minimum):
        self.steps = create_corrected_copies(context, objects, target, minimum)
        self.deadline = monotonic() + 20

    def advance(self, seconds):
        end = monotonic() + seconds
        try:
            while monotonic() < end:
                if monotonic() >= self.deadline:
                    raise CorrectionError(
                        "Correzione interrotta dopo 20 secondi. Prova con meno componenti selezionati."
                    )
                next(self.steps)
        except StopIteration as stop:
            return stop.value
        return None

    def close(self):
        self.steps.close()


def create_corrected_copies(context, objects, target, minimum):
    depsgraph = context.evaluated_depsgraph_get()
    meshes, copies = [], []
    complete = False
    try:
        components = []
        for obj in objects:
            yield
            evaluated = obj.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(
                evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
            )
            meshes.append(mesh)
            if not mesh.polygons:
                raise CorrectionError(f"{obj.name}: serve una mesh con facce.")
            try:
                components.append(Component(obj, mesh, evaluated.matrix_world))
            except ValueError as error:
                raise CorrectionError(f"{obj.name}: la trasformazione della mesh è singolare.") from error
        if not (yield from adjust(components, target, minimum)):
            return []
        for component in components:
            component.mesh.update()
            copy = bpy.data.objects.new(f"{component.obj.name} · Distanza", component.mesh)
            copies.append(copy)
            context.scene.collection.objects.link(copy)
            copy.matrix_world = component.matrix

        active = context.view_layer.objects.active
        for obj, copy in zip(objects, copies):
            obj.select_set(False)
            obj.hide_set(True)
            copy.select_set(True)
            if obj == active:
                context.view_layer.objects.active = copy
        complete = True
        return copies
    finally:
        if not complete:
            for copy in copies:
                bpy.data.objects.remove(copy, do_unlink=True)
            for mesh in meshes:
                bpy.data.meshes.remove(mesh)
