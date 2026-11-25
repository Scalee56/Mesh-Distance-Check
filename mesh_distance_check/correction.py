"""Deform evaluated copies and validate the candidate assembly before publishing it."""

from math import ceil
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


def face_samples(a, b, c, divisions):
    yield (a + b + c) / 3
    yield (a * 4 + b + c) / 6
    yield (a + b * 4 + c) / 6
    yield (a + b + c * 4) / 6
    # Interior samples on a triangular lattice, inset away from edge seams.
    ab, ac = b - a, c - a
    for row in range(divisions):
        for col in range(divisions - row):
            yield a + ab * ((row + 1 / 3) / divisions) + ac * ((col + 1 / 3) / divisions)


def check_thickness(component, minimum, affected, resolution):
    triangles = component.triangles()
    face_normals = normals_for(component.points, component.faces)
    normals = {id(triangle): normal for triangle, normal in zip(triangles, face_normals)}
    tree = component.tree()
    offset = minimum * 0.0001
    closed = is_closed(component)
    ray_limit = minimum - offset if closed else float("inf")
    lengths = {
        i: max((end - start).length for start, end in geometry.edges(triangles[i]))
        for i in affected
    }
    spacing = max(lengths.values()) / resolution
    # Keep the extra verification samples bounded on highly tessellated surfaces.
    spacing = max(spacing, sum(lengths.values()) / max(4096, len(affected) * 2))
    for index in affected:
        yield
        a, b, c = triangles[index]
        normal = face_normals[index]
        face_vertices = set(component.faces[index])
        # Sample inside each face as an additional guard on slanted walls.
        samples = max(1, ceil(lengths[index] / spacing)) if spacing else 1
        for point in face_samples(a, b, c, samples):
            yield
            directions = (-normal,) if closed else (-normal, normal)
            opposite = False
            for direction in directions:
                _, _, hit, distance = tree.ray_cast(point + direction * offset, direction, ray_limit)
                if (hit is not None and direction.dot(face_normals[hit]) > 0.15
                        and face_vertices.isdisjoint(component.faces[hit])):
                    opposite = True
                    break
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


def check_surface(component, affected):
    normals = normals_for(component.points, component.faces)
    if any(normals[i].length_squared == 0 for i in affected):
        raise CorrectionError(f"{component.obj.name}: facce degeneri nella zona deformata.")

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


class Proxy:
    def __init__(self, points, faces, mapping=None):
        self.points = points
        self.faces = faces
        self.mapping = mapping

    def triangles(self):
        return [tuple(self.points[i] for i in face) for face in self.faces]

    def tree(self):
        return BVHTree.FromPolygons(self.points, self.faces, all_triangles=True)


def simplify(component):
    points, faces = component.points, component.faces
    if len(faces) < 512:
        return Proxy(list(points), faces)
    lo = [min(point[i] for point in points) for i in range(3)]
    hi = [max(point[i] for point in points) for i in range(3)]
    divisions = 10
    scale = [divisions / (hi[i] - lo[i]) if hi[i] != lo[i] else 0 for i in range(3)]
    cells, sums, counts, mapping = {}, [], [], []
    for index, point in enumerate(points):
        if index % 256 == 0:
            yield
        cell = [(point[i] - lo[i]) * scale[i] for i in range(3)]
        # Keep outer boundary planes on their original coordinates.
        key = tuple(0 if value < 1e-6 else divisions if value > divisions - 1e-6
                    else min(divisions - 1, 1 + int(value)) for value in cell)
        group = cells.get(key)
        if group is None:
            group = cells[key] = len(sums)
            sums.append(point.copy())
            counts.append(1)
        else:
            sums[group] += point
            counts[group] += 1
        mapping.append(group)
    reduced, keys = [], set()
    for index, face in enumerate(faces):
        if index % 256 == 0:
            yield
        triangle = tuple(mapping[i] for i in face)
        key = tuple(sorted(triangle))
        if len(set(key)) < 3 or key in keys:
            continue
        keys.add(key)
        reduced.append(triangle)
    if not reduced or len(reduced) >= len(faces) * 0.8:
        return Proxy(list(points), faces)
    return Proxy([point / count for point, count in zip(sums, counts)], reduced, mapping)


def proposal(components, current, goal):
    owners, (start, end) = current
    direction = start - end
    distance = direction.length
    if distance == 0:
        return None

    trees = []
    for component in components:
        yield
        trees.append(component.tree())
    changes = []
    for index, component in enumerate(components):
        changes.append((yield from displacements(component, index, trees, goal)))
    # Seed the supporting faces even when the closest point falls between samples.
    delta = direction.normalized() * ((goal - distance) * 0.55)
    for (index, face), push in zip(owners, (delta, -delta)):
        keep_push(changes[index], face, push)
    return changes


def apply_changes(component, changes):
    for index, push in changes.items():
        yield
        vertex = component.mesh.vertices[index]
        vertex.co = component.inverse @ (component.points[index] + push)
        component.points[index] = component.matrix @ vertex.co


def transfer_proxies(components, proxies, original, target, goal):
    trees = [component.tree() for component in components]
    all_changes = []
    for index, (component, proxy, before) in enumerate(zip(components, proxies, original)):
        targets = [(other, tree) for other, tree in enumerate(trees) if other != index]
        offsets = [after - previous for after, previous in zip(proxy.points, before)]
        changes = {}
        for vertex, point in enumerate(component.points):
            if vertex % 256 == 0:
                yield
            group = proxy.mapping[vertex] if proxy.mapping is not None else vertex
            offset = offsets[group]
            if not offset.length_squared:
                continue
            match = geometry.nearest_component(point, targets, target)
            if match is None or match[2] == 0:
                continue
            _, nearest, distance = match
            direction = (point - nearest).normalized()
            if direction.dot(offset) > 0:
                changes[vertex] = direction * min(offset.length, (goal - distance) * 0.65)
        all_changes.append(changes)
    for component, changes in zip(components, all_changes):
        yield from apply_changes(component, changes)


def solve_proxies(components, target, goal):
    proxies = []
    for component in components:
        proxies.append((yield from simplify(component)))
    if not any(proxy.mapping is not None for proxy in proxies):
        return
    before = [list(proxy.points) for proxy in proxies]
    for _ in range(4):
        current = yield from violation(proxies, target)
        if current is None:
            break
        try:
            changes = yield from proposal(proxies, current, goal)
        except CorrectionError:
            # Simplification can introduce contacts absent from the nominal meshes.
            break
        if changes is None:
            break
        for proxy, deltas in zip(proxies, changes):
            for index, delta in deltas.items():
                proxy.points[index] = proxy.points[index] + delta
    if any(proxy.points != points for proxy, points in zip(proxies, before)):
        yield "Trasferimento sulla geometria originale"
        yield from transfer_proxies(components, proxies, before, target, goal)


def adjust(components, target, minimum, resolution):
    goal = target + minimum * 0.002
    yield "Calcolo sulla geometria semplificata"
    yield from solve_proxies(components, target, goal)
    yield "Verifica e rifinitura sulla geometria originale"
    current = yield from violation(components, target)
    moved = any(component.points != component.original_points for component in components)
    if current is None and not moved:
        return False

    for _ in range(12):
        if current is None:
            break
        changes = yield from proposal(components, current, goal)
        if changes is None:
            raise CorrectionError("Le mesh si toccano o si intersecano. Separale leggermente prima di correggerle.")
        for component, deltas in zip(components, changes):
            yield from apply_changes(component, deltas)
        current = yield from violation(components, target)
    if current is not None:
        raise CorrectionError("La soglia non è raggiungibile con questa correzione locale.")

    yield "Controllo dello spessore e della distanza finale"
    for component in components:
        yield
        moved = {i for i, (old, new) in enumerate(
            zip(component.original_points, component.points)
        ) if old != new}
        if not moved:
            continue
        component.mesh.update()
        component.mesh.calc_loop_triangles()
        component.faces = [tuple(face.vertices) for face in component.mesh.loop_triangles]
        affected = {i for i, face in enumerate(component.faces) if moved.intersection(face)}
        if affected:
            check_surface(component, affected)
            yield from check_thickness(component, minimum, affected, resolution)

    if (yield from violation(components, target)) is not None:
        raise CorrectionError("La geometria finale non rispetta la distanza richiesta.")
    return True


class CorrectionJob:
    def __init__(self, context, objects, target, minimum, resolution):
        self.steps = create_corrected_copies(context, objects, target, minimum, resolution)
        self.phase = "Preparazione delle mesh"

    def advance(self, seconds):
        end = monotonic() + seconds
        try:
            while monotonic() < end:
                phase = next(self.steps)
                if phase is not None:
                    self.phase = phase
        except StopIteration as stop:
            return stop.value
        return None

    def close(self):
        self.steps.close()


def create_corrected_copies(context, objects, target, minimum, resolution):
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
        if not (yield from adjust(components, target, minimum, resolution)):
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
