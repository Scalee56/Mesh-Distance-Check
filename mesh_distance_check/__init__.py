bl_info = {
    "name": "Mesh Distance Check",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "Vista 3D > Barra laterale > Mesh Distance",
    "description": "Mostra distanze, heatmap e sonda tra superfici mesh",
    "category": "Mesh",
}

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

from . import overlay
from .geometry import closest_surfaces


def selected_meshes(context):
    return [obj for obj in context.selected_objects if obj.type == "MESH"]


def evaluated_surface(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if mesh is None:
        return [], []
    try:
        mesh.calc_loop_triangles()
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        faces = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
        return points, faces
    finally:
        evaluated.to_mesh_clear()


def triangles(surface):
    points, faces = surface
    return [tuple(points[i] for i in face) for face in faces]


def evaluated_triangles(obj, depsgraph):
    return triangles(evaluated_surface(obj, depsgraph))


def surface_bvh(surface):
    return BVHTree.FromPolygons(*surface, all_triangles=True)


def format_distance(scene, distance):
    units = scene.unit_settings
    if units.system == "NONE":
        return f"{distance:.6g} BU"
    return bpy.utils.units.to_string(
        units.system, "LENGTH", distance * units.scale_length, precision=5
    )


class MESH_OT_check_surface_distance(bpy.types.Operator):
    bl_idname = "mesh.check_surface_distance"
    bl_label = "Misura distanza minima"
    bl_description = "Mostra il segmento più corto tra le due superfici selezionate"

    distance: bpy.props.FloatProperty(options={"HIDDEN", "SKIP_SAVE"})
    unit_label: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and len(selected_meshes(context)) == 2

    def execute(self, context):
        depsgraph = context.evaluated_depsgraph_get()
        surfaces = [evaluated_triangles(obj, depsgraph) for obj in selected_meshes(context)]
        if any(not surface for surface in surfaces):
            self.report({"ERROR"}, "Entrambe le mesh devono avere almeno una faccia.")
            return {"CANCELLED"}

        start, end = closest_surfaces(*surfaces)
        self.distance = (end - start).length
        self.unit_label = format_distance(context.scene, self.distance)
        label = f"Minimo: {self.unit_label}"
        overlay.scene_results(context.scene).minimum = overlay.Measurement(
            start, end, label, overlay.MINIMUM
        )
        overlay.redraw()
        self.report({"INFO"}, label)
        return {"FINISHED"}


class MESH_OT_distance_heatmap(bpy.types.Operator):
    bl_idname = "mesh.distance_heatmap"
    bl_label = "Mostra heatmap"
    bl_description = "Colora la mesh attiva in base alla distanza dalla seconda mesh"

    @classmethod
    def poll(cls, context):
        return (
            MESH_OT_check_surface_distance.poll(context)
            and context.active_object in selected_meshes(context)
        )

    def execute(self, context):
        source = context.active_object
        target = next(obj for obj in selected_meshes(context) if obj != source)
        depsgraph = context.evaluated_depsgraph_get()
        points, faces = evaluated_surface(source, depsgraph)
        target_surface = evaluated_surface(target, depsgraph)
        if not faces or not target_surface[1]:
            self.report({"ERROR"}, "Entrambe le mesh devono avere almeno una faccia.")
            return {"CANCELLED"}

        # Skip loose vertices so they cannot alter the heatmap range.
        used = sorted({index for face in faces for index in face})
        indices = {old: new for new, old in enumerate(used)}
        points = [points[index] for index in used]
        faces = [tuple(indices[index] for index in face) for face in faces]

        tree = surface_bvh(target_surface)
        distances = [tree.find_nearest(point)[3] for point in points]
        if any(distance is None for distance in distances):
            self.report({"ERROR"}, "La mesh di destinazione non ha una superficie misurabile.")
            return {"CANCELLED"}

        low = format_distance(context.scene, min(distances))
        high = format_distance(context.scene, max(distances))
        legend = f"Heatmap {source.name} → {target.name} | Rosso {low} · Blu {high}"
        data = overlay.scene_results(context.scene)
        data.heatmap = overlay.Heatmap(points, faces, distances, legend)
        data.batch = None
        overlay.redraw()
        return {"FINISHED"}


def mesh_only(_scene, obj):
    return obj.type == "MESH"


class MESH_OT_distance_probe(bpy.types.Operator):
    bl_idname = "mesh.distance_probe"
    bl_label = "Misura dal vertice selezionato"
    bl_description = "Misura dal vertice selezionato alla superficie più vicina"

    @classmethod
    def poll(cls, context):
        return context.mode == "EDIT_MESH" and context.edit_object is not None

    def execute(self, context):
        source = context.edit_object
        edit_mesh = bmesh.from_edit_mesh(source.data)
        selected = [vert for vert in edit_mesh.verts if vert.select and not vert.hide]
        active = edit_mesh.select_history.active
        if isinstance(active, bmesh.types.BMVert) and active in selected:
            vertex = active
        elif len(selected) == 1:
            vertex = selected[0]
        else:
            self.report({"ERROR"}, "Seleziona un vertice in modalità di selezione vertici.")
            return {"CANCELLED"}

        start = source.matrix_world @ vertex.co
        target = context.scene.mesh_distance_probe_target
        if target == source:
            self.report({"ERROR"}, "Scegli una mesh di destinazione diversa dalla sorgente.")
            return {"CANCELLED"}
        if target is not None:
            candidates = [target] if target.name in context.view_layer.objects else []
        else:
            candidates = [
                obj for obj in context.visible_objects if obj.type == "MESH" and obj != source
            ]

        depsgraph = context.evaluated_depsgraph_get()
        nearest = None
        best_distance = float("inf")
        for obj in candidates:
            surface = evaluated_surface(obj, depsgraph)
            if not surface[1]:
                continue
            point, _, _, distance = surface_bvh(surface).find_nearest(start)
            if distance is not None and distance < best_distance:
                nearest, best_distance, target = point, distance, obj

        if nearest is None:
            self.report({"ERROR"}, "Nessuna superficie di destinazione disponibile.")
            return {"CANCELLED"}
        label = f"Sonda → {target.name}: {format_distance(context.scene, best_distance)}"
        overlay.scene_results(context.scene).probe = overlay.Measurement(
            start, nearest, label, overlay.PROBE
        )
        overlay.redraw()
        self.report({"INFO"}, label)
        return {"FINISHED"}


class MESH_OT_clear_distance_overlay(bpy.types.Operator):
    bl_idname = "mesh.clear_distance_overlay"
    bl_label = "Cancella risultati"

    def execute(self, context):
        overlay.results.pop(context.scene.as_pointer(), None)
        overlay.redraw()
        return {"FINISHED"}


class VIEW3D_PT_surface_distance(bpy.types.Panel):
    bl_label = "Distanza tra mesh"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mesh Distance"

    def draw(self, context):
        layout = self.layout
        if context.mode == "EDIT_MESH":
            layout.prop(context.scene, "mesh_distance_probe_target", text="Destinazione")
            layout.operator(MESH_OT_distance_probe.bl_idname)
        else:
            if not MESH_OT_check_surface_distance.poll(context):
                layout.label(text="Seleziona due mesh in modalità Oggetto.")
            layout.operator(MESH_OT_check_surface_distance.bl_idname)
            layout.operator(MESH_OT_distance_heatmap.bl_idname)

        data = overlay.results.get(context.scene.as_pointer())
        if data is not None:
            for measurement in (data.minimum, data.probe):
                if measurement is not None:
                    layout.label(text=measurement.label)
            layout.operator(MESH_OT_clear_distance_overlay.bl_idname)


classes = (
    MESH_OT_check_surface_distance,
    MESH_OT_distance_heatmap,
    MESH_OT_distance_probe,
    MESH_OT_clear_distance_overlay,
    VIEW3D_PT_surface_distance,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mesh_distance_probe_target = bpy.props.PointerProperty(
        name="Destinazione sonda",
        description="Lascia vuoto per cercare la superficie più vicina tra le mesh visibili",
        type=bpy.types.Object,
        poll=mesh_only,
    )
    overlay.register()


def unregister():
    overlay.unregister()
    del bpy.types.Scene.mesh_distance_probe_target
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
