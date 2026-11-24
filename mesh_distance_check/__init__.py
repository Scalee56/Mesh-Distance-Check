bl_info = {
    "name": "Mesh Distance Check",
    "author": "Mesh Distance Check contributors",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "Vista 3D > Barra laterale > Mesh Distance",
    "description": "Misura la distanza minima tra le superfici di due mesh",
    "category": "Mesh",
}

import bpy

from .geometry import surface_distance


def selected_meshes(context):
    return [obj for obj in context.selected_objects if obj.type == "MESH"]


def evaluated_triangles(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if mesh is None:
        return []
    try:
        mesh.calc_loop_triangles()
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
        return [tuple(points[i] for i in tri.vertices) for tri in mesh.loop_triangles]
    finally:
        evaluated.to_mesh_clear()


class MESH_OT_check_surface_distance(bpy.types.Operator):
    bl_idname = "mesh.check_surface_distance"
    bl_label = "Misura distanza minima"
    bl_description = "Misura la distanza minima tra le superfici delle due mesh selezionate"

    distance: bpy.props.FloatProperty(options={"HIDDEN", "SKIP_SAVE"})
    unit_label: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and len(selected_meshes(context)) == 2

    def invoke(self, context, event):
        result = self.execute(context)
        if result == {"FINISHED"}:
            return context.window_manager.invoke_popup(self, width=320)
        return result

    def execute(self, context):
        depsgraph = context.evaluated_depsgraph_get()
        triangles = [evaluated_triangles(obj, depsgraph) for obj in selected_meshes(context)]
        if any(not surface for surface in triangles):
            self.report({"ERROR"}, "Entrambe le mesh devono avere almeno una faccia.")
            return {"CANCELLED"}

        self.distance = surface_distance(*triangles)
        units = context.scene.unit_settings
        if units.system == "NONE":
            self.unit_label = f"{self.distance:.6g} BU"
        else:
            self.unit_label = bpy.utils.units.to_string(
                units.system, "LENGTH", self.distance * units.scale_length, precision=5
            )
        self.report({"INFO"}, f"Distanza minima: {self.unit_label}")
        return {"FINISHED"}

    def draw(self, context):
        self.layout.label(text=f"Distanza minima: {self.unit_label}")


class VIEW3D_PT_surface_distance(bpy.types.Panel):
    bl_label = "Distanza tra mesh"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mesh Distance"

    def draw(self, context):
        if not MESH_OT_check_surface_distance.poll(context):
            self.layout.label(text="Seleziona due mesh in modalità Oggetto.")
        self.layout.operator(MESH_OT_check_surface_distance.bl_idname)


classes = (MESH_OT_check_surface_distance, VIEW3D_PT_surface_distance)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
