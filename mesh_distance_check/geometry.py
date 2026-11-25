"""Distanza minima tra superfici triangolate, in coordinate globali."""

from heapq import heappop, heappush
from itertools import count
from math import ceil, inf, log2, sqrt

from mathutils.geometry import (
    closest_point_on_tri,
    intersect_line_line,
    intersect_point_line,
    intersect_ray_tri,
)


def edges(triangle):
    a, b, c = triangle
    return ((a, b), (b, c), (c, a))


def project(point, start, end):
    if start == end:
        return start
    closest, factor = intersect_point_line(point, start, end)
    if factor < 0:
        return start
    if factor > 1:
        return end
    return closest


def closest_on_triangle(point, triangle):
    a, b, c = triangle
    if (b - a).cross(c - a).length_squared == 0:
        return min(
            (project(point, *edge) for edge in edges(triangle)),
            key=lambda candidate: (point - candidate).length_squared,
        )
    return closest_point_on_tri(point, *triangle)


def edge_hit(edge, triangle):
    start, end = edge
    direction = end - start
    length = direction.length
    if length == 0:
        return None
    unit = direction / length
    hit = intersect_ray_tri(*triangle, unit, start, True)
    if hit is not None and 0 <= (hit - start).dot(unit) <= length:
        return hit
    return None


def distance_squared(pair):
    first, second = pair
    return (first - second).length_squared


def closest_segments(first, second):
    a, b = first
    c, d = second
    candidates = [(p, project(p, c, d)) for p in first]
    candidates.extend((project(q, a, b), q) for q in second)
    if a != b and c != d:
        pair = intersect_line_line(a, b, c, d)
        if pair is not None:
            p, q = pair
            _, first_factor = intersect_point_line(p, a, b)
            _, second_factor = intersect_point_line(q, c, d)
            if 0 <= first_factor <= 1 and 0 <= second_factor <= 1:
                candidates.append(pair)
    return min(candidates, key=distance_squared)


def closest_triangles(first, second):
    first_edges, second_edges = edges(first), edges(second)
    for source, target in ((first_edges, second), (second_edges, first)):
        for edge in source:
            hit = edge_hit(edge, target)
            if hit is not None:
                return hit, hit

    candidates = [(p, closest_on_triangle(p, second)) for p in first]
    candidates.extend((closest_on_triangle(q, first), q) for q in second)
    candidates.extend(closest_segments(a, b) for a in first_edges for b in second_edges)
    return min(candidates, key=distance_squared)


class Node:
    def __init__(self, triangles):
        self.low = tuple(min(point[i] for tri in triangles for point in tri) for i in range(3))
        self.high = tuple(max(point[i] for tri in triangles for point in tri) for i in range(3))
        self.count = len(triangles)
        self.children = ()
        self.triangles = triangles

    def split(self):
        if not self.children:
            axis = max(range(3), key=lambda i: self.high[i] - self.low[i])
            self.triangles.sort(key=lambda tri: sum(point[axis] for point in tri))
            middle = self.count // 2
            self.children = (Node(self.triangles[:middle]), Node(self.triangles[middle:]))
            self.triangles = ()
        return self.children


def bounds_distance_squared(a, b):
    return sum(
        max(0.0, a.low[i] - b.high[i], b.low[i] - a.high[i]) ** 2
        for i in range(3)
    )


def closest_surfaces(first, second):
    return closest_components((first, second))


def closest_components(surfaces, tolerance=0.0):
    """Return a real surface pair, stopping once its error is bounded by tolerance."""
    return finish_search(search_components(surfaces, tolerance=tolerance))


def finish_search(search):
    try:
        while True:
            next(search)
    except StopIteration as stop:
        return stop.value


def search_components(surfaces, tolerance=0.0, cutoff=None):
    """Yield between zones. With a cutoff, return the first violating faces and points."""
    closest = None
    best = limit = inf if cutoff is None else cutoff ** 2
    roots = [Node(list(surface)) for surface in surfaces]
    groups = ComponentZone([(root.low, root.high, index, root) for index, root in enumerate(roots)])
    order = count()

    def entry(a, b):
        if a is not b:
            # A component leaf unwraps to its triangle hierarchy.
            if isinstance(a, ComponentZone) and a.tree is not None:
                a = a.tree
            if isinstance(b, ComponentZone) and b.tree is not None:
                b = b.tree
        return bounds_distance_squared(a, b), a is b, a.count + b.count, next(order), a, b

    pending = [entry(groups, groups)]
    while pending:
        yield
        bound, _, _, _, a, b = heappop(pending)
        if bound >= limit:
            break
        if a is b:
            if not a.children:
                continue
            left, right = a.children
            pairs = ((left, left), (left, right), (right, right))
        elif isinstance(a, ComponentZone):
            pairs = ((child, b) for child in a.children)
        elif isinstance(b, ComponentZone):
            pairs = ((a, child) for child in b.children)
        elif a.count > 4 and a.count >= b.count:
            pairs = ((child, b) for child in a.split())
        elif b.count > 4:
            pairs = ((a, child) for child in b.split())
        else:
            for triangle_a in a.triangles:
                for triangle_b in b.triangles:
                    pair = closest_triangles(triangle_a, triangle_b)
                    squared = distance_squared(pair)
                    if squared < best:
                        if cutoff is not None:
                            return (triangle_a, triangle_b), pair
                        closest, best = pair, squared
                        limit = max(0.0, sqrt(best) - tolerance) ** 2
                        if bound >= limit:
                            return closest
            continue
        for pair in pairs:
            item = entry(*pair)
            if item[0] < limit:
                heappush(pending, item)
    return closest


def surface_distance(first, second):
    return distance_squared(closest_surfaces(first, second)) ** 0.5

def nearest_component(point, trees, limit=inf):
    best_distance = limit
    nearest = None
    for component, tree in trees:
        hit, _, _, distance = tree.find_nearest(point, best_distance)
        if distance is not None and distance < best_distance:
            best_distance = distance
            nearest = component, hit, distance
            if distance == 0:
                break
    return nearest


class ComponentZone:
    """Spatial index over component bounds, with Blender BVHs at the leaves."""

    def __init__(self, components):
        self.low = tuple(min(item[0][i] for item in components) for i in range(3))
        self.high = tuple(max(item[1][i] for item in components) for i in range(3))
        self.children = ()
        self.component = None
        self.count = len(components)
        self.tree = None
        if len(components) == 1:
            _, _, self.component, self.tree = components[0]
        else:
            axis = max(range(3), key=lambda i: self.high[i] - self.low[i])
            components.sort(key=lambda item: item[0][axis] + item[1][axis])
            middle = len(components) // 2
            self.children = (ComponentZone(components[:middle]), ComponentZone(components[middle:]))

    def point_bound(self, point):
        return sum(
            max(0.0, self.low[i] - point[i], point[i] - self.high[i]) ** 2 for i in range(3)
        )

    def nearest_distance(self, point, excluded, limit=inf):
        pending = [(0.0, self)]
        squared = limit ** 2
        while pending:
            bound, zone = pending.pop()
            if bound >= squared or zone.component == excluded:
                continue
            if zone.children:
                branches = [(child.point_bound(point), child) for child in zone.children
                            if child.component != excluded]
                pending.extend(sorted(branches, key=lambda item: item[0], reverse=True))
            else:
                _, _, _, distance = zone.tree.find_nearest(point, limit)
                if distance is not None and distance < limit:
                    limit, squared = distance, distance ** 2
        return limit


def sample_surfaces(surfaces, trees, resolution, cutoff=None, critical=None):
    """Subdivide long triangles in the heatmap, pruning zones beyond the color range."""
    all_triangles, bounds = [], []
    for points, faces in surfaces:
        triangles = []
        for i, j, k in faces:
            a, b, c = points[i], points[j], points[k]
            length = max((b - a).length, (c - a).length, (c - b).length)
            triangles.append((a, b, c, length))
        all_triangles.append(triangles)
        low = tuple(min(point[i] for point in points) for i in range(3))
        high = tuple(max(point[i] for point in points) for i in range(3))
        bounds.append((low, high))
    zones = ComponentZone([(*bounds[index], index, tree) for index, tree in trees])
    lengths = [length for triangles in all_triangles for _, _, _, length in triangles]
    spacing = max(lengths) / resolution

    def depth(length):
        return ceil(log2(length / spacing)) if spacing and length > spacing else 0

    def outside_range(a, b, c, component):
        center = (a + b + c) / 3
        radius = max((a - center).length, (b - center).length, (c - center).length)
        # The distance to a surface cannot vary faster than distance from the center.
        reach = (cutoff + radius) * 1.000001
        return zones.nearest_distance(center, component, reach) == reach

    far_triangles = set()
    eligible_lengths = []
    for component, triangles in enumerate(all_triangles):
        for index, (a, b, c, length) in enumerate(triangles):
            if cutoff is not None and length > spacing and outside_range(a, b, c, component):
                far_triangles.add((component, index))
            else:
                eligible_lengths.append(length)

    budget = max(300_000, len(lengths))
    while len(far_triangles) + sum(4 ** depth(length) for length in eligible_lengths) > budget:
        spacing *= 1.4

    limit = inf if cutoff is None else cutoff
    points, faces, distances = [], [], []
    for component, triangles in enumerate(all_triangles):
        cache = {}

        def sample(point, saturated=False):
            key = tuple(point)
            index = cache.get(key)
            if index is None:
                value = limit if saturated else zones.nearest_distance(point, component, limit)
                index = cache[key] = len(points)
                points.append(point)
                distances.append(value)
            return index

        def emit(a, b, c, level, check_range=True):
            if level == 0:
                faces.append((sample(a), sample(b), sample(c)))
                return
            if check_range and cutoff is not None and outside_range(a, b, c, component):
                faces.append((sample(a, True), sample(b, True), sample(c, True)))
                return
            ab, bc, ca = (a + b) * 0.5, (b + c) * 0.5, (c + a) * 0.5
            emit(a, ab, ca, level - 1)
            emit(ab, b, bc, level - 1)
            emit(ca, bc, c, level - 1)
            emit(ab, bc, ca, level - 1)

        for index, (a, b, c, length) in enumerate(triangles):
            start = len(faces)
            if (component, index) in far_triangles:
                faces.append((sample(a, True), sample(b, True), sample(c, True)))
            else:
                emit(a, b, c, depth(length), check_range=False)
            if critical is not None and (component, index) not in far_triangles:
                threshold, vertices = critical
                original = surfaces[component][1][index]
                close_vertices = {
                    vertex for vertex, point in zip(original, (a, b, c))
                    if distances[sample(point)] < threshold
                }
                if close_vertices:
                    vertices[component].update(close_vertices)
                elif any(distances[i] < threshold for face in faces[start:] for i in face):
                    # A critical region in a face interior has no editable sample vertex.
                    vertices[component].update(original)
    return points, faces, distances, spacing
