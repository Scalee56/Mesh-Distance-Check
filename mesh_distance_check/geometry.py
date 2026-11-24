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


def closest_surfaces(first, second):
    closest = None
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
                    pair = closest_triangles(triangle_a, triangle_b)
                    squared = distance_squared(pair)
                    if squared < best:
                        closest, best = pair, squared
                        if best == 0:
                            return closest
            continue
        pending.extend(sorted(pairs, key=lambda pair: bounds_distance_squared(*pair), reverse=True))
    return closest


def surface_distance(first, second):
    return distance_squared(closest_surfaces(first, second)) ** 0.5
