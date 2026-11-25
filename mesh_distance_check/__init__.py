bl_info = {
    "name": "Mesh Distance Check",
    "version": (0, 5, 1),
    "blender": (4, 2, 0),
    "location": "Vista 3D > Barra laterale > Mesh Distance",
    "description": "Mostra distanze, heatmap e sonda tra superfici mesh",
    "category": "Mesh",
}

import sys
from importlib import import_module

import bmesh
import bpy
from bpy_extras.view3d_utils import region_2d_to_origin_3d, region_2d_to_vector_3d
from mathutils.bvhtree import BVHTree

# Blender can reload the add-on package during an update while leaving its
# child modules in memory. Import both children from the newly installed files.
sys.modules.pop(f"{__name__}.geometry", None)
sys.modules.pop(f"{__name__}.overlay", None)
sys.modules.pop(f"{__name__}.correction", None)
geometry = import_module(".geometry", __name__)
overlay = import_module(".overlay", __name__)
correction = import_module(".correction", __name__)


def selected_meshes(context):
    return [obj for obj in context.selected_objects if obj.type == "MESH"]


def analysis_meshes(context):
    if context.scene.mesh_distance_all_visible:
        return [obj for obj in context.visible_objects if obj.type == "MESH"]
    return selected_meshes(context)


def analysis_surfaces(context, objects):
    depsgraph = context.evaluated_depsgraph_get()
    surfaces = [(obj, evaluated_surface(obj, depsgraph)) for obj in objects]
    return [(obj, surface) for obj, surface in surfaces if surface[1]]


def evaluated_surface(obj, depsgraph, topology=None):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    if mesh is None:
        return [], []
    try:
        mesh.calc_loop_triangles()
        if topology is not None:
            original = obj.data
            if (len(mesh.vertices) == len(original.vertices)
                    and len(mesh.polygons) == len(original.polygons)
                    and all(tuple(a.vertices) == tuple(b.vertices)
                            for a, b in zip(mesh.polygons, original.polygons))):
                coordinates = hash(tuple(tuple(vertex.co) for vertex in original.vertices))
                topology[obj] = (original, len(mesh.polygons), obj.matrix_world.copy(), coordinates)
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
    bl_description = "Stima il minimo globale fra le superfici incluse nell’analisi"

    distance: bpy.props.FloatProperty(options={"HIDDEN", "SKIP_SAVE"})
    unit_label: bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and len(analysis_meshes(context)) >= 2

    def execute(self, context):
        surfaces = analysis_surfaces(context, analysis_meshes(context))
        if len(surfaces) < 2:
            self.report({"ERROR"}, "Servono almeno due mesh con facce.")
            return {"CANCELLED"}

        units = context.scene.unit_settings
        tolerance = 0.000005 / units.scale_length
        start, end = geometry.closest_components(
            (triangles(surface) for _, surface in surfaces), tolerance=tolerance
        )
        self.distance = (end - start).length
        if units.system == "NONE":
            self.unit_label = format_distance(context.scene, self.distance)
        else:
            self.unit_label = f"{self.distance * units.scale_length * 1000:.2f} mm"
        label = f"Minimo ≈ {self.unit_label}"
        overlay.scene_results(context.scene).minimum = overlay.Measurement(
            start, end, label, overlay.MINIMUM
        )
        overlay.redraw()
        self.report({"INFO"}, label)
        return {"FINISHED"}


class MESH_OT_distance_heatmap(bpy.types.Operator):
    bl_idname = "mesh.distance_heatmap"
    bl_label = "Mostra heatmap"
    bl_description = "Mostra su ogni mesh la distanza dal componente più vicino"

    @classmethod
    def poll(cls, context):
        return MESH_OT_check_surface_distance.poll(context)

    def execute(self, context):
        topology = {}
        depsgraph = context.evaluated_depsgraph_get()
        measured = [(obj, evaluated_surface(obj, depsgraph, topology)) for obj in analysis_meshes(context)]
        measured = [(obj, surface) for obj, surface in measured if surface[1]]
        if len(measured) < 2:
            self.report({"ERROR"}, "Servono almeno due mesh con facce.")
            return {"CANCELLED"}

        surfaces = [surface for _, surface in measured]
        trees = [(index, surface_bvh(surface)) for index, surface in enumerate(surfaces)]
        scene = context.scene
        cutoff = scene.mesh_distance_scale_max or None
        samples = [{} for _ in measured]
        points, faces, distances, spacing = geometry.sample_surfaces(
            surfaces, trees, scene.mesh_distance_resolution, cutoff=cutoff, vertex_samples=samples,
        )
        if cutoff is None:
            low, high = min(distances), max(distances)
        else:
            low, high = 0.0, cutoff
        labels = tuple(format_distance(scene, value) for value in (low, (low + high) / 2, high))
        data = overlay.scene_results(scene)
        data.heatmap = overlay.Heatmap(
            points, faces, distances, (low, high), labels, len(surfaces),
            format_distance(scene, spacing),
        )
        data.batch = None
        data.legend_batch = None
        data.critical_vertices = {
            obj: (*topology[obj], vertices)
            for (obj, _), vertices in zip(measured, samples) if obj in topology
        }
        data.critical_skipped = {obj for obj, _ in measured if obj not in topology}
        data.heatmap_sample_limit = cutoff if cutoff is not None and max(distances) >= cutoff else None
        data.heatmap_scale_max = scene.mesh_distance_scale_max
        overlay.redraw()
        return {"FINISHED"}


def red_limit(heatmap):
    low, high = heatmap.limits
    return low + overlay.HEAT_STOPS[1][0] * (high - low)


def update_heatmap_scale(scene, _context):
    data = overlay.results.get(scene.as_pointer())
    if data is None or data.heatmap is None:
        return
    scale = scene.mesh_distance_scale_max
    limit = data.heatmap_sample_limit
    if limit is not None and (scale == 0 or scale > limit):
        overlay.redraw()
        return

    heatmap = data.heatmap
    if scale:
        low, high = 0.0, scale
    else:
        low, high = min(heatmap.distances), max(heatmap.distances)
    heatmap.limits = (low, high)
    heatmap.labels = tuple(format_distance(scene, d) for d in (low, (low + high) / 2, high))
    data.heatmap_scale_max = scale
    data.batch = None
    data.legend_batch = None
    overlay.redraw()


def select_critical_vertices(context, data):
    if context.scene.mesh_distance_scale_max != data.heatmap_scale_max:
        return None, ["Ricalcola la heatmap per applicare Fine scala."]
    threshold = red_limit(data.heatmap)

    edits, skipped = [], []
    for obj in context.objects_in_mode_unique_data:
        entry = data.critical_vertices.get(obj)
        if entry is None:
            if obj in data.critical_skipped:
                skipped.append(obj.name)
            continue
        mesh, face_count, transform, coordinates, samples = entry
        bm = bmesh.from_edit_mesh(obj.data)
        if (obj.data != mesh or len(bm.faces) != face_count or obj.matrix_world != transform
                or hash(tuple(tuple(vertex.co) for vertex in bm.verts)) != coordinates):
            skipped.append(obj.name)
            continue
        indices = {index for index, distance in samples.items() if distance <= threshold}
        edits.append((obj, bm, indices))

    if not edits:
        return None, skipped
    context.tool_settings.mesh_select_mode = (True, False, False)
    selected = 0
    for obj, bm, indices in edits:
        bm.verts.index_update()
        bm.select_mode = {"VERT"}
        bm.select_history.clear()
        for collection in (bm.faces, bm.edges):
            for element in collection:
                element.select = False
        for vertex in bm.verts:
            vertex.select_set(not vertex.hide and vertex.index in indices)
            selected += vertex.select
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    overlay.redraw()
    return selected, skipped


class MESH_OT_select_critical_distance(bpy.types.Operator):
    bl_idname = "mesh.select_critical_distance"
    bl_label = "Seleziona zone critiche"
    bl_description = "Seleziona i vertici nella fascia rossa della heatmap"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        data = overlay.results.get(context.scene.as_pointer())
        return context.mode in {"OBJECT", "EDIT_MESH"} and data is not None and data.heatmap is not None

    def execute(self, context):
        data = overlay.results[context.scene.as_pointer()]
        if context.scene.mesh_distance_scale_max != data.heatmap_scale_max:
            self.report({"WARNING"}, "Ricalcola la heatmap per applicare Fine scala.")
            return {"CANCELLED"}
        if context.mode == "OBJECT":
            if not any(obj in data.critical_vertices for obj in selected_meshes(context)):
                self.report({"WARNING"}, "Seleziona almeno una mesh analizzata con topologia compatibile.")
                return {"CANCELLED"}
            bpy.ops.object.mode_set(mode="EDIT")
        count, skipped = select_critical_vertices(context, data)
        data.critical_edit_object = context.edit_object
        if skipped:
            self.report({"WARNING"}, "Selezione da aggiornare o indisponibile: " + ", ".join(skipped))
        if count is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"Vertici critici selezionati: {count}")
        return {"FINISHED"}


def auto_select_critical():
    context = bpy.context
    scene = context.scene
    if scene is None:
        return 0.25
    data = overlay.results.get(scene.as_pointer())
    if data is None or data.heatmap is None:
        return 0.25
    obj = context.edit_object if context.mode == "EDIT_MESH" else None
    if obj != data.critical_edit_object:
        data.critical_edit_object = obj
        if obj is not None and scene.mesh_distance_auto_critical:
            select_critical_vertices(context, data)
    return 0.25


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

        if not add_probe(context, source, start, analysis_surfaces(context, candidates)):
            self.report({"ERROR"}, "Nessuna superficie di destinazione disponibile.")
            return {"CANCELLED"}
        return {"FINISHED"}


def add_probe(context, source, start, surfaces):
    trees = [(obj, surface_bvh(surface)) for obj, surface in surfaces if obj != source]
    hit = geometry.nearest_component(start, trees)
    if hit is None:
        return False
    target, point, distance = hit
    label = f"{source.name} → {target.name}: {format_distance(context.scene, distance)}"
    overlay.scene_results(context.scene).probes.append(
        overlay.Measurement(start, point, label, overlay.PROBE)
    )
    overlay.redraw()
    return True


class MESH_OT_click_distance_probe(bpy.types.Operator):
    bl_idname = "mesh.click_distance_probe"
    bl_label = "Sonda (clic per misurare)"
    bl_description = "Clicca su una superficie per misurare verso la mesh analizzata più vicina"

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == "VIEW_3D"
            and MESH_OT_check_surface_distance.poll(context)
        )

    def invoke(self, context, event):
        surfaces = analysis_surfaces(context, analysis_meshes(context))
        if len(surfaces) < 2:
            self.report({"ERROR"}, "Servono almeno due mesh con facce.")
            return {"CANCELLED"}
        self.objects = [obj.name for obj, _ in surfaces]
        self.area = context.area
        self.window = context.window
        self.area.header_text_set("Sonda distanza · Clic sinistro: misura · Esc / tasto destro: termina")
        self.window.cursor_modal_set("CROSSHAIR")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if context.screen and any(area == self.area for area in context.screen.areas):
            self.area.header_text_set(None)
        self.window.cursor_modal_restore()

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self.cancel(context)
            return {"FINISHED"}
        if context.area != self.area or event.type != "LEFTMOUSE" or event.value != "PRESS":
            return {"PASS_THROUGH"}

        under_mouse = [
            region for region in self.area.regions
            if region.x <= event.mouse_x < region.x + region.width
            and region.y <= event.mouse_y < region.y + region.height
        ]
        region = next((region for region in under_mouse if region.type == "WINDOW"), None)
        if region is None or any(panel.type in {"UI", "TOOLS"} for panel in under_mouse):
            return {"PASS_THROUGH"}

        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        with context.temp_override(region=region):
            view = context.region_data
        if view is None:
            return {"PASS_THROUGH"}
        direction = region_2d_to_vector_3d(region, view, (x, y))
        origin = region_2d_to_origin_3d(region, view, (x, y))
        if not self.measure_ray(context, origin, direction):
            self.report({"INFO"}, "Clicca su una delle mesh incluse nell’analisi.")
        return {"RUNNING_MODAL"}

    def measure_ray(self, context, origin, direction):
        objects = [obj for obj in context.visible_objects if obj.name in self.objects]
        # Scene ray cast respects the first object under the cursor, including occluders.
        hit, start, _, _, source, _ = context.scene.ray_cast(
            context.evaluated_depsgraph_get(), origin, direction
        )
        if not hit or source is None or source.original not in objects:
            return False
        source = source.original
        targets = analysis_surfaces(context, (obj for obj in objects if obj != source))
        return add_probe(context, source, start, targets)


class MESH_OT_clear_distance_probes(bpy.types.Operator):
    bl_idname = "mesh.clear_distance_probes"
    bl_label = "Cancella sonde"

    def execute(self, context):
        overlay.scene_results(context.scene).probes.clear()
        overlay.redraw()
        return {"FINISHED"}


class MESH_OT_clear_distance_overlay(bpy.types.Operator):
    bl_idname = "mesh.clear_distance_overlay"
    bl_label = "Cancella risultati"

    def execute(self, context):
        overlay.results.pop(context.scene.as_pointer(), None)
        overlay.redraw()
        return {"FINISHED"}


class MESH_OT_correct_clearance(bpy.types.Operator):
    bl_idname = "mesh.correct_clearance"
    bl_label = "Correggi distanza minima"
    bl_description = "Deforma localmente copie delle mesh selezionate e controlla le pareti da 1 mm"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and len(selected_meshes(context)) >= 2

    def start(self, context):
        scene = context.scene
        millimeter = 0.001 / scene.unit_settings.scale_length
        self.job = correction.CorrectionJob(
            context, selected_meshes(context),
            scene.mesh_distance_clearance_mm * millimeter, millimeter, scene.mesh_distance_resolution,
        )

    def invoke(self, context, event):
        if bpy.app.background or context.window is None:
            return self.execute(context)
        self.start(context)
        self.timer = context.window_manager.event_timer_add(0.04, window=context.window)
        self.workspace = context.workspace
        self.phase = self.job.phase
        self.workspace.status_text_set(f"{self.phase} · Esc per annullare")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self.job.close()
        context.window_manager.event_timer_remove(self.timer)
        self.workspace.status_text_set(None)

    def modal(self, context, event):
        if event.type == "ESC" and event.value == "PRESS":
            self.cancel(context)
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}
        try:
            result = self.job.advance(0.025)
        except correction.CorrectionError as error:
            self.cancel(context)
            self.report({"WARNING"}, str(error))
            return {"CANCELLED"}
        except Exception:
            self.cancel(context)
            raise
        if result is None:
            if self.phase != self.job.phase:
                self.phase = self.job.phase
                self.workspace.status_text_set(f"{self.phase} · Esc per annullare")
            return {"RUNNING_MODAL"}
        self.cancel(context)
        return self.finish(context, result)

    def execute(self, context):
        self.start(context)
        try:
            result = self.job.advance(float("inf"))
        except correction.CorrectionError as error:
            self.report({"WARNING"}, str(error))
            return {"CANCELLED"}
        finally:
            self.job.close()
        return self.finish(context, result)

    def finish(self, context, result):
        copies, warnings, issues = result
        scene = context.scene
        if not copies:
            self.report({"INFO"}, "Le mesh rispettano già la distanza minima.")
            return {"FINISHED"}
        overlay.results.pop(scene.as_pointer(), None)
        if warnings or issues:
            data = overlay.scene_results(scene)
            data.correction_warnings = warnings
            data.correction_issues = issues
            status = "Correzione parziale visibile." if issues else "Copie corrette."
            self.report({"WARNING"}, status + " " + " | ".join(issues + warnings))
        else:
            self.report({"INFO"}, f"Correzione verificata su {len(copies)} copie. Originali nascosti.")
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
            layout.operator(MESH_OT_select_critical_distance.bl_idname)
            layout.prop(context.scene, "mesh_distance_probe_target", text="Destinazione")
            layout.operator(MESH_OT_distance_probe.bl_idname)
        else:
            layout.prop(context.scene, "mesh_distance_all_visible")
            if not MESH_OT_check_surface_distance.poll(context):
                layout.label(text="Includi almeno due mesh in modalità Oggetto.")
            layout.operator(MESH_OT_check_surface_distance.bl_idname)
            layout.operator(MESH_OT_click_distance_probe.bl_idname, icon="EYEDROPPER")
            heatmap = layout.column(align=True)
            heatmap.prop(context.scene, "mesh_distance_resolution")
            heatmap.prop(context.scene, "mesh_distance_scale_max")
            heatmap.operator(MESH_OT_distance_heatmap.bl_idname)
            heatmap.prop(context.scene, "mesh_distance_auto_critical")
            heatmap.operator(MESH_OT_select_critical_distance.bl_idname)
            repair = layout.column(align=True)
            repair.prop(context.scene, "mesh_distance_clearance_mm")
            repair.operator_context = "INVOKE_DEFAULT"
            repair.operator(MESH_OT_correct_clearance.bl_idname)

        data = overlay.results.get(context.scene.as_pointer())
        if data is not None:
            if data.minimum is not None:
                layout.label(text=data.minimum.label)
            if data.heatmap is not None:
                if context.scene.mesh_distance_scale_max != data.heatmap_scale_max:
                    layout.label(text="Ricalcola per applicare Fine scala", icon="INFO")
                else:
                    limit = format_distance(context.scene, red_limit(data.heatmap))
                    layout.label(text=f"Fascia rossa ≤ {limit}")
                layout.label(text=f"Passo stimato: {data.heatmap.spacing}")
            if data.probes:
                layout.label(text=f"Sonde: {len(data.probes)}")
                layout.label(text=data.probes[-1].label)
                layout.operator(MESH_OT_clear_distance_probes.bl_idname)
            if data.correction_issues:
                partial = layout.box()
                partial.label(text="Correzione parziale", icon="ERROR")
                for message in data.correction_issues:
                    partial.label(text=message)
            if data.correction_warnings:
                warnings = layout.box()
                warnings.label(text="Avvisi spessore", icon="ERROR")
                for message in data.correction_warnings:
                    name, _, detail = message.partition(": ")
                    warnings.label(text=name)
                    warnings.label(text=detail)
            layout.operator(MESH_OT_clear_distance_overlay.bl_idname)


classes = (
    MESH_OT_check_surface_distance,
    MESH_OT_distance_heatmap,
    MESH_OT_select_critical_distance,
    MESH_OT_distance_probe,
    MESH_OT_click_distance_probe,
    MESH_OT_clear_distance_probes,
    MESH_OT_clear_distance_overlay,
    MESH_OT_correct_clearance,
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
    bpy.types.Scene.mesh_distance_all_visible = bpy.props.BoolProperty(
        name="Tutte le mesh visibili",
        description="Analizza tutte le mesh visibili invece delle sole mesh selezionate",
    )
    bpy.types.Scene.mesh_distance_resolution = bpy.props.IntProperty(
        name="Risoluzione",
        description="Densità della heatmap e della verifica dello spessore dopo la correzione",
        default=32, min=4, max=96,
    )
    bpy.types.Scene.mesh_distance_scale_max = bpy.props.FloatProperty(
        name="Fine scala",
        description="Distanza corrispondente al blu. Zero usa il range comune misurato",
        default=0, min=0, subtype="DISTANCE", unit="LENGTH", precision=4,
        update=update_heatmap_scale,
    )
    bpy.types.Scene.mesh_distance_clearance_mm = bpy.props.FloatProperty(
        name="Distanza minima (mm)", default=0.3, min=0.001, precision=3,
        description="Distanza richiesta tra le copie delle mesh selezionate, in millimetri",
    )
    bpy.types.Scene.mesh_distance_auto_critical = bpy.props.BoolProperty(
        name="Seleziona entrando in Modifica",
        description="Seleziona le zone critiche dell’ultima heatmap quando entri in Modalità Modifica",
        default=True,
    )
    overlay.register()
    if not bpy.app.background:
        bpy.app.timers.register(auto_select_critical, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(auto_select_critical):
        bpy.app.timers.unregister(auto_select_critical)
    overlay.unregister()
    del bpy.types.Scene.mesh_distance_auto_critical
    del bpy.types.Scene.mesh_distance_clearance_mm
    del bpy.types.Scene.mesh_distance_scale_max
    del bpy.types.Scene.mesh_distance_resolution
    del bpy.types.Scene.mesh_distance_all_visible
    del bpy.types.Scene.mesh_distance_probe_target
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
