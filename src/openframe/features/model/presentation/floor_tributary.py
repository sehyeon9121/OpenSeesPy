"""Convert a floor ``LoadEntry``'s magnitude over its (convex) boundary
polygon into equivalent ``UniformElementLoad`` contributions on the
boundary beams.

Only ever called from ``canvas_load_entries.py``'s
``_activate_generated_case_for_analysis`` - the sole place any Loads-tab
entry is projected into ``self.element_loads``/``build_model()`` today, and
its own docstring already anticipated floor entries getting a "dedicated
conversion path" plugged in there. Nothing here is invoked outside that one
integration point, and nothing here mutates the drawn model - a floor's
tributary loads are recomputed fresh every time, never persisted as their
own ``LoadEntry``/``Element``/``Node`` (matching how self-weight is derived
data too).

``target_nodes`` is stored as ``tuple(sorted(selected_node_tags))`` - not an
ordered boundary loop, whatever the field's own docstring says - so the
polygon's real vertex order is recovered here by angular sort, which is only
valid for a convex boundary (this feature's declared scope; a concave
boundary produces a wrong, self-intersecting order and is not detected).

Every ``element_loads`` value in this app's ``build_model()`` pipeline is a
single linear ramp (w_i -> w_j) along the whole member - there is no way to
express a peak-in-the-middle shape without physically splitting the member,
which this feature deliberately never does (see the module docstring above).
So a two-way edge's true triangular/trapezoidal-with-plateau tributary shape
is replaced by the *statically equivalent* linear ramp: the one (w_i, w_j)
pair whose own total force and resultant location exactly match the true
shape's (see ``_equivalent_linear_ramp``). Reaction totals and the
resultant's line of action come out exact for every shape this module
handles exactly (triangle, axis-aligned rectangle); only the fine-grained
shape along the member is an approximation, inherent to the app's existing
single-ramp load model rather than specific to this feature.
"""

import math
from collections.abc import Sequence

from openframe.core.domain import Element, FloorLoadEntry, LoadEntry, Node
from openframe.features.model.presentation.canvas_model_build import _local_axes

# Must match Quick3DSceneBridge._floor_direction_vector
# (features/viewport/presentation/quick3d_scene_bridge.py) - both read the
# same fixed-global-axis convention FloorLoadEntry.direction uses.
_DIRECTION_VECTORS: dict[str, tuple[float, float, float]] = {
    "-z": (0.0, 0.0, -1.0),
    "+z": (0.0, 0.0, 1.0),
    "-x": (-1.0, 0.0, 0.0),
    "+x": (1.0, 0.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
}

_EPSILON = 1e-9

_EdgeForce = tuple[float, float, float]  # (unit-pressure total force, centroid-from-start, length)


def _axis_and_uv(
    nodes: dict[int, Node], tags: Sequence[int]
) -> tuple[tuple[int, int], dict[int, tuple[float, float]]] | None:
    """Drop whichever of (x, y, z) is nearly constant across every tagged
    node and project the rest to (u, v) - floor boundaries are only ever
    picked from nodes drawn on one axis-aligned ``WorkPlane``
    (``canvas_work_planes.py``), so this recovers the same projection
    ``WorkPlane.to_2d`` would give, without needing that object to still be
    around at conversion time."""
    if len(tags) < 3:
        return None
    points = [(nodes[tag].x, nodes[tag].y, nodes[tag].z) for tag in tags]
    spans = [
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    ]
    dropped_axis = min(range(3), key=lambda axis: spans[axis])
    remaining = tuple(axis for axis in range(3) if axis != dropped_axis)
    uv_by_tag = {
        tag: (point[remaining[0]], point[remaining[1]]) for tag, point in zip(tags, points, strict=True)
    }
    return remaining, uv_by_tag


def _order_convex(uv_by_tag: dict[int, tuple[float, float]]) -> list[int]:
    """Angular sort around the vertex centroid - the correct winding order
    for any convex polygon (this feature's declared scope); wrong, silently,
    for a concave one."""
    tags = list(uv_by_tag)
    center_u = sum(uv_by_tag[tag][0] for tag in tags) / len(tags)
    center_v = sum(uv_by_tag[tag][1] for tag in tags) / len(tags)
    return sorted(
        tags, key=lambda tag: math.atan2(uv_by_tag[tag][1] - center_v, uv_by_tag[tag][0] - center_u)
    )


def _polygon_area(ordered_uv: list[tuple[float, float]]) -> float:
    n = len(ordered_uv)
    total = sum(
        ordered_uv[i][0] * ordered_uv[(i + 1) % n][1] - ordered_uv[(i + 1) % n][0] * ordered_uv[i][1]
        for i in range(n)
    )
    return abs(total) / 2.0


def _boundary_edges(ordered_tags: list[int], elements: dict[int, Element]) -> list[int | None]:
    """One entry per polygon edge (``ordered_tags[i]`` -> ``ordered_tags[i+1]``):
    the ``Element`` tag that physically spans it, or ``None`` if no drawn
    member does - a gap in the boundary simply cannot deliver load (treated
    like an unsupported/cantilevered edge), it does not block the rest of
    the panel's conversion."""
    n = len(ordered_tags)
    edges: list[int | None] = []
    for i in range(n):
        a, b = ordered_tags[i], ordered_tags[(i + 1) % n]
        match = next(
            (tag for tag, element in elements.items() if {element.node_i, element.node_j} == {a, b}),
            None,
        )
        edges.append(match)
    return edges


def _equivalent_linear_ramp(total_force: float, centroid: float, length: float) -> tuple[float, float]:
    """The (w_i, w_j) linear ramp whose own total force and centroid
    (measured from the ramp's own i-end) exactly reproduce ``total_force``/
    ``centroid`` - see this module's own docstring for why an exact
    pointwise shape isn't attempted instead."""
    if length <= _EPSILON:
        return 0.0, 0.0
    scale = 2.0 * total_force / length
    w_i = scale * (2.0 - 3.0 * centroid / length)
    w_j = scale * (3.0 * centroid / length - 1.0)
    return w_i, w_j


def _one_way_edge_forces(ordered_uv: list[tuple[float, float]], span_axis: int) -> list[_EdgeForce]:
    """Unit-pressure UDL per edge for a slab spanning along ``span_axis``
    (0=u, 1=v): only the two edges roughly perpendicular to the span
    direction carry load (classified by each edge's own direction vector),
    each at intensity = (span extent)/2, uniform along its own length.
    Exact for a rectangle; an approximation (total load not guaranteed
    conserved) for any other convex shape, same as any one-way idealization."""
    n = len(ordered_uv)
    perp_axis = 1 - span_axis
    span_extent = max(p[span_axis] for p in ordered_uv) - min(p[span_axis] for p in ordered_uv)
    results: list[_EdgeForce] = []
    for i in range(n):
        p0, p1 = ordered_uv[i], ordered_uv[(i + 1) % n]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length <= _EPSILON:
            results.append((0.0, 0.0, 0.0))
            continue
        edge_vector = (p1[0] - p0[0], p1[1] - p0[1])
        carries_load = abs(edge_vector[perp_axis]) >= abs(edge_vector[span_axis])
        force = (span_extent / 2.0) * length if carries_load else 0.0
        results.append((force, length / 2.0, length))
    return results


def _triangle_edge_forces(ordered_uv: list[tuple[float, float]]) -> list[_EdgeForce]:
    """Exact via the incenter: it sits at the same perpendicular distance
    (the inradius) from all three sides, so edge i's tributary region is
    exactly the flat triangle formed by that edge and the incenter."""
    (ax, ay), (bx, by), (cx, cy) = ordered_uv
    a = math.hypot(bx - cx, by - cy)  # side opposite A = edge BC
    b = math.hypot(cx - ax, cy - ay)  # side opposite B = edge CA
    c = math.hypot(ax - bx, ay - by)  # side opposite C = edge AB
    perimeter = a + b + c
    if perimeter <= _EPSILON:
        return [(0.0, 0.0, 0.0)] * 3
    incenter = (
        (a * ax + b * bx + c * cx) / perimeter,
        (a * ay + b * by + c * cy) / perimeter,
    )
    area = _polygon_area(ordered_uv)
    inradius = 2.0 * area / perimeter
    lengths = (c, a, b)  # edge0=AB, edge1=BC, edge2=CA
    results: list[_EdgeForce] = []
    for index in range(3):
        p0, p1 = ordered_uv[index], ordered_uv[(index + 1) % 3]
        length = lengths[index]
        if length <= _EPSILON:
            results.append((0.0, 0.0, 0.0))
            continue
        edge_dir = ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
        projection = (incenter[0] - p0[0]) * edge_dir[0] + (incenter[1] - p0[1]) * edge_dir[1]
        centroid = (projection + length) / 3.0  # centroid of the (0, t, length) triangle
        force = 0.5 * length * inradius
        results.append((force, centroid, length))
    return results


def _is_axis_aligned_rectangle(ordered_uv: list[tuple[float, float]]) -> bool:
    if len(ordered_uv) != 4:
        return False
    us = sorted({round(p[0], 9) for p in ordered_uv})
    vs = sorted({round(p[1], 9) for p in ordered_uv})
    if len(us) != 2 or len(vs) != 2:
        return False
    expected = {(us[0], vs[0]), (us[0], vs[1]), (us[1], vs[0]), (us[1], vs[1])}
    return {(round(p[0], 9), round(p[1], 9)) for p in ordered_uv} == expected


def _rectangle_edge_forces(ordered_uv: list[tuple[float, float]]) -> list[_EdgeForce]:
    """Exact classical 45-degree yield-line construction: the two short
    edges get a symmetric triangular tributary region (peak = pressure *
    short/2 at midspan), the two long edges get a symmetric trapezoid (same
    peak, flat plateau over the long-short remainder) - both symmetric, so
    each edge's statically-equivalent ramp collapses to a plain uniform
    load (see the module docstring)."""
    us = [p[0] for p in ordered_uv]
    vs = [p[1] for p in ordered_uv]
    lx = max(us) - min(us)
    ly = max(vs) - min(vs)
    short, long_ = min(lx, ly), max(lx, ly)
    short_force = short * short / 4.0
    long_force = (short / 2.0) * (long_ - short) + short * short / 4.0
    results: list[_EdgeForce] = []
    for index in range(4):
        p0, p1 = ordered_uv[index], ordered_uv[(index + 1) % 4]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        is_short = abs(length - short) < abs(length - long_)
        force = short_force if is_short else long_force
        results.append((force, length / 2.0, length))
    return results


def _point_in_polygon(point: tuple[float, float], ordered_uv: list[tuple[float, float]]) -> bool:
    u, v = point
    inside = False
    n = len(ordered_uv)
    for i in range(n):
        u0, v0 = ordered_uv[i]
        u1, v1 = ordered_uv[(i + 1) % n]
        if (v0 > v) != (v1 > v):
            u_intersect = u0 + (v - v0) * (u1 - u0) / (v1 - v0)
            if u < u_intersect:
                inside = not inside
    return inside


def _nearest_edge(point: tuple[float, float], ordered_uv: list[tuple[float, float]]) -> tuple[int, float]:
    n = len(ordered_uv)
    best_index = 0
    best_distance = math.inf
    best_projection = 0.0
    for i in range(n):
        p0, p1 = ordered_uv[i], ordered_uv[(i + 1) % n]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length <= _EPSILON:
            continue
        edge_dir = ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
        projection = (point[0] - p0[0]) * edge_dir[0] + (point[1] - p0[1]) * edge_dir[1]
        clamped = max(0.0, min(length, projection))
        closest = (p0[0] + edge_dir[0] * clamped, p0[1] + edge_dir[1] * clamped)
        distance = math.hypot(point[0] - closest[0], point[1] - closest[1])
        if distance < best_distance:
            best_distance = distance
            best_index = i
            best_projection = clamped
    return best_index, best_projection


_APPROX_GRID_RESOLUTION = 80


def _approx_edge_forces(ordered_uv: list[tuple[float, float]]) -> list[_EdgeForce]:
    """Approximate partition for any convex shape this module has no exact
    formula for (a pentagon or higher, or a non-rectangular quadrilateral):
    assign a fine interior grid of sample points to their nearest boundary
    edge (by point-to-segment distance) and reduce each edge's samples to a
    (total force, centroid, length). Not exact for any single shape, but
    conserves the total load exactly by construction - every sample cell is
    assigned to exactly one edge."""
    n = len(ordered_uv)
    min_u = min(p[0] for p in ordered_uv)
    max_u = max(p[0] for p in ordered_uv)
    min_v = min(p[1] for p in ordered_uv)
    max_v = max(p[1] for p in ordered_uv)
    span_u = max(max_u - min_u, _EPSILON)
    span_v = max(max_v - min_v, _EPSILON)
    resolution = _APPROX_GRID_RESOLUTION
    cell_area = (span_u / resolution) * (span_v / resolution)
    lengths = [
        math.hypot(
            ordered_uv[(i + 1) % n][0] - ordered_uv[i][0], ordered_uv[(i + 1) % n][1] - ordered_uv[i][1]
        )
        for i in range(n)
    ]
    force_sums = [0.0] * n
    moment_sums = [0.0] * n
    for iu in range(resolution):
        u = min_u + (iu + 0.5) * span_u / resolution
        for iv in range(resolution):
            v = min_v + (iv + 0.5) * span_v / resolution
            point = (u, v)
            if not _point_in_polygon(point, ordered_uv):
                continue
            edge_index, projection = _nearest_edge(point, ordered_uv)
            force_sums[edge_index] += cell_area
            moment_sums[edge_index] += cell_area * projection
    results: list[_EdgeForce] = []
    for index in range(n):
        length = lengths[index]
        force = force_sums[index]
        centroid = moment_sums[index] / force if force > _EPSILON else length / 2.0
        results.append((force, centroid, length))
    return results


def _two_way_edge_forces(ordered_uv: list[tuple[float, float]]) -> list[_EdgeForce]:
    if len(ordered_uv) == 3:
        return _triangle_edge_forces(ordered_uv)
    if _is_axis_aligned_rectangle(ordered_uv):
        return _rectangle_edge_forces(ordered_uv)
    return _approx_edge_forces(ordered_uv)


def _span_axis_index(remaining_axes: tuple[int, int], span_direction: str) -> int:
    """``span_direction`` ("x"/"y") names one of the two axes this floor's
    plane still has after the constant one was dropped - "x" picks global X
    if it survived the projection, "y" picks global Y, and either falls
    back to the first/second projected axis when its named global axis was
    the one dropped (e.g. a floor on the YZ plane has no global X to pick)."""
    target_axis = 0 if span_direction == "x" else 1
    if target_axis in remaining_axes:
        return remaining_axes.index(target_axis)
    return 0 if span_direction == "x" else 1


def _project_global_to_local(
    global_vector: tuple[float, float, float],
    local_x: tuple[float, float, float],
    local_y: tuple[float, float, float],
    local_z: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        sum(global_vector[axis] * local_x[axis] for axis in range(3)),
        sum(global_vector[axis] * local_y[axis] for axis in range(3)),
        sum(global_vector[axis] * local_z[axis] for axis in range(3)),
    )


def convert_floor_entry(
    entry: LoadEntry, nodes: dict[int, Node], elements: dict[int, Element]
) -> dict[int, tuple[float, float, float, float, float, float]]:
    """(wx0, wy0, wz0, wx1, wy1, wz1) local-axis contribution per boundary
    ``Element`` tag, from one floor ``LoadEntry`` - empty if the entry can't
    be converted (fewer than 3 usable boundary nodes, or a degenerate/zero-
    area boundary)."""
    payload = entry.payload
    if not isinstance(payload, FloorLoadEntry):
        return {}
    tags = [tag for tag in payload.target_nodes if tag in nodes]
    if len(tags) < 3:
        return {}
    projection = _axis_and_uv(nodes, tags)
    if projection is None:
        return {}
    remaining_axes, uv_by_tag = projection
    ordered_tags = _order_convex(uv_by_tag)
    ordered_uv = [uv_by_tag[tag] for tag in ordered_tags]
    if _polygon_area(ordered_uv) <= _EPSILON:
        return {}
    edge_elements = _boundary_edges(ordered_tags, elements)

    if payload.distribution == "one_way":
        span_axis = _span_axis_index(remaining_axes, payload.span_direction)
        edge_forces = _one_way_edge_forces(ordered_uv, span_axis)
    else:
        edge_forces = _two_way_edge_forces(ordered_uv)

    direction_vector = _DIRECTION_VECTORS.get(payload.direction, (0.0, 0.0, -1.0))
    contributions: dict[int, tuple[float, float, float, float, float, float]] = {}
    n = len(ordered_tags)
    for index in range(n):
        element_tag = edge_elements[index]
        if element_tag is None:
            continue
        force, centroid, length = edge_forces[index]
        if length <= _EPSILON or force <= _EPSILON:
            continue
        total_force = force * payload.magnitude
        w_start, w_end = _equivalent_linear_ramp(total_force, centroid, length)

        element = elements[element_tag]
        axes = _local_axes(element, nodes, 3)
        if axes is None:
            continue
        local_x, local_y, local_z = axes
        # ordered_tags[index] is this edge's start vertex - if the drawn
        # element's own node_i is the *other* end, the ramp's start/end
        # values need swapping to line up with the element's own i/j order.
        if element.node_i != ordered_tags[index]:
            w_start, w_end = w_end, w_start

        global_start = tuple(component * w_start for component in direction_vector)
        global_end = tuple(component * w_end for component in direction_vector)
        wx0, wy0, wz0 = _project_global_to_local(global_start, local_x, local_y, local_z)
        wx1, wy1, wz1 = _project_global_to_local(global_end, local_x, local_y, local_z)
        existing = contributions.get(element_tag, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        contributions[element_tag] = (
            existing[0] + wx0,
            existing[1] + wy0,
            existing[2] + wz0,
            existing[3] + wx1,
            existing[4] + wy1,
            existing[5] + wz1,
        )
    return contributions
