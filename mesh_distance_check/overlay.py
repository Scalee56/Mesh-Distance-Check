"""Draw measurements without modifying mesh data or materials."""

from dataclasses import dataclass

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

# Color stops from the Mesh Thickness Analyzer reference.
HEAT_STOPS = (
    (0.00, 1.0, 0.0, 0.0),
    (0.20, 1.0, 0.0, 0.4),
    (0.35, 1.0, 0.45, 0.0),
    (0.55, 0.9, 0.95, 0.0),
    (0.75, 0.1, 0.85, 0.1),
    (1.00, 0.0, 0.25, 1.0),
)
LEGEND_TEXT = (0.96, 0.97, 0.99, 1.0)
MINIMUM = (1.0, 0.77, 0.25, 1.0)
PROBE = (0.35, 1.0, 0.63, 1.0)


@dataclass
class Measurement:
    start: object
    end: object
    label: str
    color: tuple


@dataclass
class Heatmap:
    points: list
    faces: list
    distances: list
    limits: tuple
    labels: tuple
    component_count: int
    spacing: str


class Results:
    def __init__(self):
        self.minimum = None
        self.probes = []
        self.correction_warnings = []
        self.correction_issues = []
        self.critical_vertices = {}
        self.critical_skipped = set()
        self.critical_threshold = None
        self.critical_edit_object = None
        self.heatmap = None
        self.batch = None
        self.legend_batch = None
        self.heat_shader = None


results = {}
handlers = []


def scene_results(scene):
    return results.setdefault(scene.as_pointer(), Results())


def redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def make_heat_shader():
    interface = gpu.types.GPUStageInterfaceInfo("distance_heatmap_values")
    interface.smooth("FLOAT", "sampleValue")
    shader = gpu.types.GPUShaderCreateInfo()
    shader.push_constant("MAT4", "transform")
    shader.push_constant("FLOAT", "opacity")
    shader.vertex_in(0, "VEC3", "pos")
    shader.vertex_in(1, "FLOAT", "fraction")
    shader.vertex_out(interface)
    shader.fragment_out(0, "VEC4", "outColor")
    shader.vertex_source("""
        void main() {
            sampleValue = fraction;
            gl_Position = transform * vec4(pos, 1.0);
        }
    """)
    # Interpolate the measured distance first, then map it to a color.
    clauses = []
    for first, second in zip(HEAT_STOPS, HEAT_STOPS[1:]):
        low, *near = first
        high, *far = second
        near_rgb = ", ".join(map(str, near))
        far_rgb = ", ".join(map(str, far))
        clauses.append(
            f"if (t <= {high}) return mix(vec3({near_rgb}), vec3({far_rgb}), "
            f"(t - {low}) / ({high} - {low}));"
        )
    shader.fragment_source(
        "vec3 palette(float t) { " + " ".join(clauses) + " return vec3(0.0, 0.25, 1.0); }"
        "void main() { outColor = vec4(palette(clamp(sampleValue, 0.0, 1.0)), opacity); }"
    )
    return gpu.shader.create_from_info(shader)


def draw_heatmap(data):
    if data.heat_shader is None:
        data.heat_shader = make_heat_shader()
    shader = data.heat_shader
    if data.batch is None:
        heatmap = data.heatmap
        low, high = heatmap.limits
        span = high - low
        fractions = [(d - low) / span if span else 0.0 for d in heatmap.distances]
        data.batch = batch_for_shader(
            shader, "TRIS", {"pos": heatmap.points, "fraction": fractions}, indices=heatmap.faces
        )
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.blend_set("ALPHA")
    # Bias clip-space depth slightly to prevent flickering against the source faces.
    projection = gpu.matrix.get_projection_matrix()
    projection[2] = projection[2] - 0.00002 * projection[3]
    shader.bind()
    shader.uniform_float("transform", projection @ gpu.matrix.get_model_view_matrix())
    shader.uniform_float("opacity", 0.94)
    data.batch.draw(shader)


def draw_measurement(measurement, region, width):
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    shader.bind()
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", measurement.color)
    points = [measurement.start, measurement.end]
    batch_for_shader(shader, "LINES", {"pos": points}).draw(shader)

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    shader.bind()
    gpu.state.point_size_set(width + 5.0)
    shader.uniform_float("color", measurement.color)
    batch_for_shader(shader, "POINTS", {"pos": points}).draw(shader)


def current_results():
    context = bpy.context
    if context.scene is None or context.space_data is None:
        return None
    if context.space_data.type != "VIEW_3D" or not context.space_data.overlay.show_overlays:
        return None
    return results.get(context.scene.as_pointer())


def draw_view():
    data = current_results()
    if data is None:
        return
    try:
        if data.heatmap is not None:
            draw_heatmap(data)
        gpu.state.depth_test_set("NONE")
        if data.minimum is not None:
            draw_measurement(data.minimum, bpy.context.region, 5.0)
        for measurement in data.probes:
            draw_measurement(measurement, bpy.context.region, 3.0)
    finally:
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")
        gpu.state.point_size_set(1.0)


def text_at(text, x, y, color):
    blf.size(0, 14)
    blf.color(0, *color)
    blf.enable(0, blf.SHADOW)
    blf.shadow(0, 3, 0.0, 0.0, 0.0, 1.0)
    blf.shadow_offset(0, 1, -1)
    blf.position(0, x, y, 0)
    blf.draw(0, text)
    blf.disable(0, blf.SHADOW)


def draw_legend(data, region):
    heatmap = data.heatmap
    x, y, width = 40, 60, 24
    height = min(220, max(16, region.height - 165))
    if data.heat_shader is None:
        data.heat_shader = make_heat_shader()
    shader = data.heat_shader
    uniform = heatmap.limits[0] == heatmap.limits[1]
    # Geometry stays in normalized coordinates so resizing only changes the transform.
    if data.legend_batch is None:
        fractions = (0.0, 0.0, 0.0, 0.0) if uniform else (0.0, 0.0, 1.0, 1.0)
        data.legend_batch = batch_for_shader(shader, "TRI_STRIP", {
            "pos": ((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)),
            "fraction": fractions,
        })
    shader.bind()
    transform = Matrix.Translation((x, y, 0)) @ Matrix.Diagonal((width, height, 1, 1))
    shader.uniform_float(
        "transform", gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix() @ transform
    )
    shader.uniform_float("opacity", 1.0)
    data.legend_batch.draw(shader)

    text_at(f"Distanza · {heatmap.component_count} mesh", x, y + height + 14, LEGEND_TEXT)
    labels = ((0.5, heatmap.labels[0]),) if uniform else zip((0, 0.5, 1), heatmap.labels)
    for fraction, label in labels:
        text_at(label, x + width + 10, y + fraction * height - 5, LEGEND_TEXT)


def draw_labels():
    data = current_results()
    if data is None:
        return
    context = bpy.context
    region, view = context.region, context.region_data
    y = 48
    if data.heatmap is not None:
        draw_legend(data, region)
        y = 18
    if data.minimum is not None:
        text_at(data.minimum.label, 18, y, data.minimum.color)
        y += 22
    if data.probes:
        text_at(data.probes[-1].label, 18, y, PROBE)

    measurements = ([data.minimum] if data.minimum is not None else []) + data.probes
    for index, measurement in enumerate(measurements):
        midpoint = (measurement.start + measurement.end) * 0.5
        pos = location_3d_to_region_2d(region, view, midpoint)
        if pos is not None and 0 <= pos.x < region.width and 0 <= pos.y < region.height:
            offset = 18 if data.minimum is not None and index > 0 else 0
            text_at(measurement.label, pos.x + 8, pos.y + 8 + offset, measurement.color)


@bpy.app.handlers.persistent
def clear_all(_unused=None):
    results.clear()


def register():
    if bpy.app.background:
        return
    handlers.append(bpy.types.SpaceView3D.draw_handler_add(draw_view, (), "WINDOW", "POST_VIEW"))
    handlers.append(bpy.types.SpaceView3D.draw_handler_add(draw_labels, (), "WINDOW", "POST_PIXEL"))
    bpy.app.handlers.load_pre.append(clear_all)
    bpy.app.handlers.undo_post.append(clear_all)
    bpy.app.handlers.redo_post.append(clear_all)


def unregister():
    for handler in handlers:
        bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
    handlers.clear()
    for callbacks in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if clear_all in callbacks:
            callbacks.remove(clear_all)
    clear_all()
