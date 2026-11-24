"""Distanza minima tra superfici triangolate, in coordinate globali."""

from itertools import combinations
from math import ceil

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
    return closest_components((first, second))


def closest_components(surfaces):
    closest = None
    best = float("inf")
    roots = [Node(list(surface)) for surface in surfaces]
    pending = sorted(
        combinations(roots, 2), key=lambda pair: bounds_distance_squared(*pair), reverse=True
    )
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

def nearest_component(point, trees):
    best_distance = float("inf")
    nearest = None
    for component, tree in trees:
        hit, _, _, distance = tree.find_nearest(point, best_distance)
        if distance is not None and distance < best_distance:
            best_distance = distance
            nearest = component, hit, distance
            if distance == 0:
                break
    return nearest


def sample_surfaces(surfaces, trees, resolution):
    """Subdivide long triangles for display only, with a shared spacing and budget."""
    all_triangles = []
    for points, faces in surfaces:
        triangles = []
        for i, j, k in faces:
            a, b, c = points[i], points[j], points[k]
            length = max((b - a).length, (c - a).length, (c - b).length)
            triangles.append((a, b, c, length))
        all_triangles.append(triangles)
    lengths = [length for triangles in all_triangles for _, _, _, length in triangles]
    longest = max(lengths)
    spacing = longest / resolution

    def divisions(length):
        return max(1, ceil(length / spacing)) if spacing else 1

    budget = max(300_000, len(lengths))
    while sum(divisions(length) ** 2 for length in lengths) > budget:
        spacing *= 1.4

    points, faces, distances = [], [], []
    for component, triangles in enumerate(all_triangles):
        vertex_cache = {}
        targets = [(index, tree) for index, tree in trees if component != index]

        def sample(point):
            key = tuple(point)
            index = vertex_cache.get(key)
            if index is None:
                _, _, distance = nearest_component(point, targets)
                index = vertex_cache[key] = len(points)
                points.append(point)
                distances.append(distance)
            return index

        for a, b, c, length in triangles:
            count = divisions(length)
            if count == 1:
                faces.append((sample(a), sample(b), sample(c)))
                continue

            # A triangular lattice includes both edge and interior samples.
            ab, ac = b - a, c - a
            rows = [
                [sample(a + ab * (i / count) + ac * (j / count))
                 for j in range(count - i + 1)]
                for i in range(count + 1)
            ]
            for i in range(count):
                row, next_row = rows[i], rows[i + 1]
                for j in range(count - i):
                    faces.append((row[j], next_row[j], row[j + 1]))
                    if j + 1 < len(next_row):
                        faces.append((row[j + 1], next_row[j], next_row[j + 1]))
    return points, faces, distances, spacing
