"""Deform evaluated copies and validate the candidate assembly before publishing it."""

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


def clearance(components):
    pair = geometry.closest_components(component.triangles() for component in components)
    return geometry.distance_squared(pair) ** 0.5


def displacements(component, index, trees, goal):
    targets = [tree for other, tree in enumerate(trees) if other != index]
    deltas = [Vector((0, 0, 0)) for _ in component.points]

    def push(point, indices):
        best = goal
        nearest = None
        for tree in targets:
            hit, _, _, distance = tree.find_nearest(point, best)
            if distance is not None and distance < best:
                nearest, best = hit, distance
        if nearest is None:
            return
        if best == 0:
            raise CorrectionError("Le superfici si toccano o si intersecano durante la correzione.")
        delta = (point - nearest).normalized() * ((goal - best) * 0.55)
        for vertex in indices:
            if delta.length_squared > deltas[vertex].length_squared:
                deltas[vertex] = delta

    for vertex, point in enumerate(component.points):
        push(point, (vertex,))
    for face in component.faces:
        a, b, c = (component.points[vertex] for vertex in face)
        push((a + b + c) / 3, face)
        for midpoint, edge in (((a + b) * .5, face[:2]), ((b + c) * .5, face[1:]),
                               ((c + a) * .5, (face[2], face[0]))):
            push(midpoint, edge)
    return deltas


def adjust(components, target, minimum):
    distance = clearance(components)
    if distance >= target:
        return False
    if distance <= 0:
        raise CorrectionError("Le mesh si toccano o si intersecano. Separale leggermente prima di correggerle.")

    goal = target + minimum * 0.002
    for _ in range(10):
        trees = [component.tree() for component in components]
        changes = [displacements(component, index, trees, goal)
                   for index, component in enumerate(components)]
        if not any(delta.length_squared for deltas in changes for delta in deltas):
            break
        for component, deltas in zip(components, changes):
            # Round-trip through local coordinates before validating the output.
            for vertex, point, delta in zip(component.mesh.vertices, component.points, deltas):
                if delta.length_squared:
                    vertex.co = component.inverse @ (point + delta)
            component.points = [component.matrix @ vertex.co for vertex in component.mesh.vertices]
        distance = clearance(components)
        if distance >= target:
            for component in components:
                moved = {i for i, (old, new) in enumerate(
                    zip(component.original_points, component.points)
                ) if old != new}
                affected = {i for i, face in enumerate(component.faces) if moved.intersection(face)}
                if not affected:
                    continue
                check_surface(component, affected)
                component.mesh.update()
                component.mesh.calc_loop_triangles()
                component.faces = [tuple(face.vertices) for face in component.mesh.loop_triangles]
                affected = {i for i, face in enumerate(component.faces) if moved.intersection(face)}
                check_surface(component, affected, check_orientation=False)
                check_thickness(component, minimum, affected)
            if clearance(components) < target:
                raise CorrectionError("La geometria finale non rispetta la distanza richiesta.")
            return True
        if distance <= 0:
            raise CorrectionError("La correzione ha generato un contatto o un’intersezione.")

    raise CorrectionError("La soglia di distanza non è raggiungibile con questa correzione locale.")


def create_corrected_copies(context, objects, target, minimum):
    depsgraph = context.evaluated_depsgraph_get()
    meshes, copies = [], []
    complete = False
    try:
        components = []
        for obj in objects:
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
        if not adjust(components, target, minimum):
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
