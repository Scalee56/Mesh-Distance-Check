"""Draw measurements without modifying mesh data or materials."""

from dataclasses import dataclass

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader

NEAR = (0.98, 0.26, 0.11, 0.85)
FAR = (0.10, 0.54, 1.0, 0.85)
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
    legend: str


class Results:
    minimum = None
    probe = None
    heatmap = None
    batch = None


results = {}
handlers = []


def scene_results(scene):
    return results.setdefault(scene.as_pointer(), Results())


def redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def draw_heatmap(data):
    shader = gpu.shader.from_builtin("SMOOTH_COLOR")
    if data.batch is None:
        heatmap = data.heatmap
        low, high = min(heatmap.distances), max(heatmap.distances)
        span = high - low
        fractions = [(d - low) / span if span else 0.0 for d in heatmap.distances]
        colors = [tuple(a + t * (b - a) for a, b in zip(NEAR, FAR)) for t in fractions]
        data.batch = batch_for_shader(
            shader, "TRIS", {"pos": heatmap.points, "color": colors}, indices=heatmap.faces
        )
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.blend_set("ALPHA")
    # Bias clip-space depth slightly to prevent flickering against the source faces.
    projection = gpu.matrix.get_projection_matrix()
    projection[2] = projection[2] - 0.00002 * projection[3]
    with gpu.matrix.push_pop_projection():
        gpu.matrix.load_projection_matrix(projection)
        shader.bind()
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
        for measurement, width in ((data.minimum, 5.0), (data.probe, 3.0)):
            if measurement is not None:
                draw_measurement(measurement, bpy.context.region, width)
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


def draw_labels():
    data = current_results()
    if data is None:
        return
    context = bpy.context
    region, view = context.region, context.region_data
    y = 48
    if data.heatmap is not None:
        text_at(data.heatmap.legend, 18, y, (1.0, 1.0, 1.0, 1.0))
        y += 22
    for index, measurement in enumerate((data.minimum, data.probe)):
        if measurement is None:
            continue
        text_at(measurement.label, 18, y, measurement.color)
        y += 22
        midpoint = (measurement.start + measurement.end) * 0.5
        pos = location_3d_to_region_2d(region, view, midpoint)
        if pos is not None and 0 <= pos.x < region.width and 0 <= pos.y < region.height:
            text_at(measurement.label, pos.x + 8, pos.y + 8 + index * 18, measurement.color)


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
