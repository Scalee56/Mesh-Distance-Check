"""Distanza minima tra superfici triangolate, in coordinate globali."""

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


def crosses_triangle(edge, triangle):
    start, end = edge
    direction = end - start
    length = direction.length
    if length == 0:
        return False
    unit = direction / length
    hit = intersect_ray_tri(*triangle, unit, start, True)
    return hit is not None and 0 <= (hit - start).dot(unit) <= length


def segment_distance_squared(first, second):
    a, b = first
    c, d = second
    candidates = [(p - project(p, c, d)).length_squared for p in first]
    candidates.extend((p - project(p, a, b)).length_squared for p in second)
    if a != b and c != d:
        pair = intersect_line_line(a, b, c, d)
        if pair is not None:
            p, q = pair
            _, first_factor = intersect_point_line(p, a, b)
            _, second_factor = intersect_point_line(q, c, d)
            if 0 <= first_factor <= 1 and 0 <= second_factor <= 1:
                candidates.append((p - q).length_squared)
    return min(candidates)


def triangle_distance_squared(first, second):
    first_edges, second_edges = edges(first), edges(second)
    if any(crosses_triangle(edge, second) for edge in first_edges):
        return 0.0
    if any(crosses_triangle(edge, first) for edge in second_edges):
        return 0.0
    return min(
        min((p - closest_on_triangle(p, second)).length_squared for p in first),
        min((p - closest_on_triangle(p, first)).length_squared for p in second),
        min(segment_distance_squared(a, b) for a in first_edges for b in second_edges),
    )


class Node:
    def __init__(self, triangles):
        self.low = tuple(min(point[i] for tri in triangles for point in tri) for i in range(3))
        self.high = tuple(max(point[i] for tri in triangles for point in tri) for i in range(3))
        self.count = len(triangles)
        self.children = ()
        self.triangles = triangles
        if self.count > 4:
            axis = max(range(3), key=lambda i: self.high[i] - self.low[i])
            triangles.sort(key=lambda tri: sum(point[axis] for point in tri))
            middle = self.count // 2
            self.children = (Node(triangles[:middle]), Node(triangles[middle:]))
            self.triangles = ()


def bounds_distance_squared(a, b):
    return sum(
        max(0.0, a.low[i] - b.high[i], b.low[i] - a.high[i]) ** 2
        for i in range(3)
    )


def surface_distance(first, second):
    best = float("inf")
    pending = [(Node(list(first)), Node(list(second)))]
    while pending:
        a, b = pending.pop()
        if bounds_distance_squared(a, b) >= best:
            continue
        if a.children and (not b.children or a.count >= b.count):
            pairs = [(child, b) for child in a.children]
        elif b.children:
            pairs = [(a, child) for child in b.children]
        else:
            for triangle_a in a.triangles:
                for triangle_b in b.triangles:
                    best = min(best, triangle_distance_squared(triangle_a, triangle_b))
                    if best == 0:
                        return 0.0
            continue
        pending.extend(sorted(pairs, key=lambda pair: bounds_distance_squared(*pair), reverse=True))
    return best ** 0.5
