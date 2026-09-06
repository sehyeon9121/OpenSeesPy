"""Rectangular structured quad mesher for a single planar ``WallPanel``.

This is still a tensor-product grid, not a general surface mesher. Opening,
wall-wall intersection, embedded-beam splitting, equalDOF and Auto Mesh stay
out of scope. Extra *seeds* (story elevations, USER nodes that already sit
on the rectangle) only insert additional parametric rows or columns; they
do not change the visit order or the ASDShellQ4 connectivity pattern.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from openframe.core.domain.model import Node, NodeOrigin, StructuralModel
from openframe.core.domain.story import STORY_Z_TOLERANCE, Story
from openframe.core.domain.surfaces import ShellQuad, WallPanel

#: Relative/absolute tolerance for "this is a rectangle in a plane".
#: Measured against the longer edge so millimetre and metre models share one
#: check. Tight enough that a visibly skewed quad is rejected, loose enough
#: that float interpolation of a valid rectangle still passes.
_RECTANGLE_REL_TOL = 1.0e-8
_RECTANGLE_ABS_TOL = 1.0e-12

#: OpenSees dummy nodes inside ``MaterialFreeStaticsSolver`` start at 7e6
#: (trapezoid stations). Generated wall-mesh tags stay below that floor so
#: a later solve never collides — identity itself is ``Node.origin``, not
#: this number.
_SOLVER_DUMMY_TAG_FLOOR = 7_000_000


class WallMeshError(ValueError):
    """Geometry the rectangular mesher will not turn into quads."""


@dataclass(frozen=True, slots=True)
class WallQuadPayload:
    """Four corner coordinates of one analysis quad, in model space.

    Undeformed when ``displacements`` is omitted; otherwise each corner is
    translated by ``scale * (Ux, Uy, Uz)``. Viewport converts these to
    Quick3D view space — this type stays Qt-free.
    """

    tag: int
    wall_tag: int
    corners: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]


def assemble_wall_meshes(model: StructuralModel) -> StructuralModel:
    """Drop any previous wall mesh and rebuild every ``WallPanel``.

    Mutates ``model.nodes`` / ``model.shell_quads`` in place and returns the
    same object so Linear Static and the 3D viewport share one node table:
    result tags must exist on the model the caller still holds.

    Only ``WALL_MESH`` nodes and ``shell_quads`` are dropped. USER nodes
    stay, including beam/column nodes the new mesh will re-adopt, so frame
    ``Element`` connectivity is not rewritten across a remesh.
    """
    if not model.walls:
        return model

    user_nodes = {
        tag: node for tag, node in model.nodes.items() if not node.is_wall_mesh
    }
    model.nodes = user_nodes
    model.shell_quads = {}

    next_node_tag = max(user_nodes, default=0)
    next_quad_tag = max(model.elements, default=0)
    generated_nodes: dict[int, Node] = {}
    generated_quads: dict[int, ShellQuad] = {}

    for wall in sorted(model.walls.values(), key=lambda item: item.tag):
        next_node_tag, next_quad_tag, nodes, quads = mesh_rectangular_wall(
            wall,
            user_nodes,
            next_node_tag=next_node_tag,
            next_quad_tag=next_quad_tag,
            stories=model.stories,
        )
        generated_nodes.update(nodes)
        generated_quads.update(quads)

    model.nodes = {**user_nodes, **generated_nodes}
    model.shell_quads = generated_quads
    return model


def mesh_rectangular_wall(
    wall: WallPanel,
    nodes: dict[int, Node],
    *,
    next_node_tag: int,
    next_quad_tag: int,
    stories: tuple[Story, ...] = (),
) -> tuple[int, int, dict[int, Node], dict[int, ShellQuad]]:
    """Build a tensor-product quad mesh on ``wall``.

    Uniform ``nx × ny`` stations are the baseline. Story elevations that
    fall inside the wall height and USER nodes that already sit on the
    rectangle insert extra parametric rows/columns; coincident stations
    collapse to one line. Corner stations still reuse the four authored
    tags; any other grid point that lands on an existing USER node reuses
    that tag instead of allocating ``WALL_MESH``. Visit order stays
    row-major in (iy, ix) with iy along ``n1→n4`` and ix along ``n1→n2``,
    matching the ASDShellQ4 spike so a seed-free 2×2 wall is the same
    connectivity as the engine-only test.

    Frame elements are never rewritten: a beam that already ends on a USER
    node keeps that connectivity, and the wall adopts the tag. ``equalDOF``
    / rigidLink are not a fallback for geometry that misses this tolerance.
    """
    errors = wall.validate()
    if errors:
        raise WallMeshError(errors[0])

    corners = _corner_points(wall, nodes)
    _assert_rectangle(wall.tag, corners)
    origin = corners[0]
    edge_x = _sub(corners[1], corners[0])
    edge_y = _sub(corners[3], corners[0])
    length_x = _length(edge_x)
    length_y = _length(edge_y)
    scale = max(length_x, length_y, 1.0)
    seed_tol = _seed_tolerance(scale)
    param_tol_s = seed_tol / length_x
    param_tol_t = seed_tol / length_y
    ndf = nodes[wall.node_1].ndf

    s_samples = [ix / wall.nx for ix in range(wall.nx + 1)]
    t_samples = [iy / wall.ny for iy in range(wall.ny + 1)]
    t_samples.extend(
        _story_height_parameters(origin, edge_x, edge_y, length_y, seed_tol, stories)
    )
    user_hits = _user_nodes_on_wall(
        nodes, origin, edge_x, edge_y, length_x, length_y, seed_tol
    )
    s_samples.extend(hit[1] for hit in user_hits)
    t_samples.extend(hit[2] for hit in user_hits)
    s_values = _merged_params(s_samples, param_tol_s)
    t_values = _merged_params(t_samples, param_tol_t)
    last_s = len(s_values) - 1
    last_t = len(t_values) - 1

    occupancy: dict[tuple[int, int], int] = {}
    _occupy(occupancy, (0, 0), wall.node_1)
    _occupy(occupancy, (last_s, 0), wall.node_2)
    _occupy(occupancy, (last_s, last_t), wall.node_3)
    _occupy(occupancy, (0, last_t), wall.node_4)
    for tag, s_param, t_param in user_hits:
        ix = _nearest_index(s_param, s_values, param_tol_s)
        iy = _nearest_index(t_param, t_values, param_tol_t)
        if ix is None or iy is None:
            continue
        _occupy(occupancy, (ix, iy), tag)

    grid: dict[tuple[int, int], int] = {}
    generated: dict[int, Node] = {}
    current_node = next_node_tag
    for iy, sy in enumerate(t_values):
        for ix, sx in enumerate(s_values):
            reused = occupancy.get((ix, iy))
            if reused is not None:
                grid[ix, iy] = reused
                continue
            current_node = _allocate_tag(current_node)
            point = _interpolate(origin, edge_x, edge_y, sx, sy)
            generated[current_node] = Node(
                current_node,
                point[0],
                point[1],
                point[2],
                ndf,
                NodeOrigin.WALL_MESH,
            )
            grid[ix, iy] = current_node

    quads: dict[int, ShellQuad] = {}
    current_quad = next_quad_tag
    for iy in range(last_t):
        for ix in range(last_s):
            current_quad = _allocate_tag(current_quad)
            quads[current_quad] = ShellQuad(
                tag=current_quad,
                node_1=grid[ix, iy],
                node_2=grid[ix + 1, iy],
                node_3=grid[ix + 1, iy + 1],
                node_4=grid[ix, iy + 1],
                wall_tag=wall.tag,
            )

    return current_node, current_quad, generated, quads


def wall_local_x(wall: WallPanel, nodes: dict[int, Node]) -> tuple[float, float, float]:
    """Unit vector along ``n1→n2`` — the wall's local x, shared by every quad.

    ASDShellQ4's ``-local`` otherwise takes each element's own 1-2 edge, which
    would flip on a quad whose first edge runs up the wall instead of along
    the width. Forcing one vector per panel keeps the section axes aligned
    with the authored rectangle.
    """
    n1 = nodes[wall.node_1]
    n2 = nodes[wall.node_2]
    vector = (n2.x - n1.x, n2.y - n1.y, n2.z - n1.z)
    length = math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)
    if length <= _RECTANGLE_ABS_TOL:
        raise WallMeshError(f"벽체 {wall.tag}의 폭 방향이 영벡터입니다.")
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def wall_quad_payloads(
    model: StructuralModel,
    *,
    displacements: dict[int, tuple[float, ...]] | None = None,
    scale: float = 1.0,
) -> tuple[WallQuadPayload, ...]:
    """One payload per ``ShellQuad``, undeformed or translated by node UX/UY/UZ."""
    payloads: list[WallQuadPayload] = []
    for quad in sorted(model.shell_quads.values(), key=lambda item: item.tag):
        corners: list[tuple[float, float, float]] = []
        for tag in quad.node_tags():
            node = model.nodes.get(tag)
            if node is None:
                raise WallMeshError(f"셸 쿼드 {quad.tag}의 절점 {tag}가 없습니다.")
            ux, uy, uz = 0.0, 0.0, 0.0
            if displacements is not None:
                sample = displacements.get(tag, ())
                padded = (*sample, 0.0, 0.0, 0.0)
                ux, uy, uz = float(padded[0]), float(padded[1]), float(padded[2])
            corners.append(
                (
                    node.x + ux * scale,
                    node.y + uy * scale,
                    node.z + uz * scale,
                )
            )
        payloads.append(
            WallQuadPayload(
                tag=quad.tag,
                wall_tag=quad.wall_tag,
                corners=(corners[0], corners[1], corners[2], corners[3]),
            )
        )
    return tuple(payloads)


def _seed_tolerance(scale: float) -> float:
    """Physical snap distance for story rows and USER-node reuse.

    Story Manager already treats ``STORY_Z_TOLERANCE`` as "this Z is that
    floor". Reusing it as the seed floor means a beam node sitting on a
    storey and the mesh row for that storey cannot miss each other. The
    rectangle relative term still grows with a huge panel so two stations
    1e-6 apart on a kilometre wall collapse rather than spawning a sliver.
    """
    return max(STORY_Z_TOLERANCE, _RECTANGLE_REL_TOL * scale)


def _merged_params(samples: list[float], param_tol: float) -> tuple[float, ...]:
    """Sort [0, 1] parametric stations and collapse neighbours within ``param_tol``.

    Uniform nx/ny, story elevations and USER seeds all feed this so a
    mid-height storey that already coincides with ``iy/ny`` does not create
    a duplicate row. Endpoints stay exactly 0 and 1 so the authored corners
    remain the grid boundary.
    """
    values = [0.0, 1.0]
    for raw in samples:
        if not math.isfinite(raw):
            continue
        values.append(min(1.0, max(0.0, raw)))
    values.sort()
    merged: list[float] = []
    for value in values:
        if not merged:
            merged.append(value)
            continue
        if value - merged[-1] <= param_tol:
            if value == 1.0:
                merged[-1] = 1.0
            continue
        merged.append(value)
    if merged[0] != 0.0:
        merged.insert(0, 0.0)
    if merged[-1] != 1.0:
        merged.append(1.0)
    return tuple(merged)


def _story_height_parameters(
    origin: tuple[float, float, float],
    edge_x: tuple[float, float, float],
    edge_y: tuple[float, float, float],
    length_y: float,
    seed_tol: float,
    stories: tuple[Story, ...],
) -> list[float]:
    """Map in-range story elevations onto the wall's height parameter t.

    Stories are Z elevations, not 3D points. A constant-Z plane is a
    constant-t row only when the wall is vertical and n1→n2 is level;
    a slab-like or tilted rectangle is skipped rather than inventing a
    diagonal cut. Elevations outside the wall height are ignored the same
    way Story Manager ignores nodes that are not at that floor.
    """
    if not _wall_takes_story_rows(edge_x, edge_y, seed_tol):
        return []
    parameters: list[float] = []
    height_z = edge_y[2]
    for story in stories:
        t_param = (story.elevation - origin[2]) / height_z
        if t_param < -seed_tol / length_y or t_param > 1.0 + seed_tol / length_y:
            continue
        parameters.append(min(1.0, max(0.0, t_param)))
    return parameters


def _wall_takes_story_rows(
    edge_x: tuple[float, float, float],
    edge_y: tuple[float, float, float],
    seed_tol: float,
) -> bool:
    normal = _cross(edge_x, edge_y)
    nlen = _length(normal)
    if nlen <= _RECTANGLE_ABS_TOL:
        return False
    # Unit-normal Z is the sine of tilt from vertical. Ambiguous lean is
    # left unmeshed rather than guessing a non-horizontal story cut.
    if abs(normal[2]) / nlen > 1.0e-6:
        return False
    if abs(edge_x[2]) > seed_tol:
        return False
    return abs(edge_y[2]) > seed_tol


def _user_nodes_on_wall(
    nodes: dict[int, Node],
    origin: tuple[float, float, float],
    edge_x: tuple[float, float, float],
    edge_y: tuple[float, float, float],
    length_x: float,
    length_y: float,
    seed_tol: float,
) -> list[tuple[int, float, float]]:
    """USER nodes that already sit on this rectangle, as (tag, s, t).

    A node off the plane or outside the rectangle is not a connection —
    we do not project it, split a beam, or invent equalDOF. An authored
    node that is clearly on the face (edge, corner, or in-plane junction)
    becomes a seed so the tensor-product grid passes through that tag.
    Embedded members that cross the interior without a node at the
    crossing are left unconnected on purpose.
    """
    normal = _cross(edge_x, edge_y)
    nlen = _length(normal)
    if nlen <= _RECTANGLE_ABS_TOL:
        return []
    unit_n = (normal[0] / nlen, normal[1] / nlen, normal[2] / nlen)
    param_tol_s = seed_tol / length_x
    param_tol_t = seed_tol / length_y
    hits: list[tuple[int, float, float]] = []
    for tag, node in sorted(nodes.items()):
        if node.is_wall_mesh:
            continue
        rel = (node.x - origin[0], node.y - origin[1], node.z - origin[2])
        if abs(_dot(rel, unit_n)) > seed_tol:
            continue
        s_param = _dot(rel, edge_x) / (length_x * length_x)
        t_param = _dot(rel, edge_y) / (length_y * length_y)
        if s_param < -param_tol_s or s_param > 1.0 + param_tol_s:
            continue
        if t_param < -param_tol_t or t_param > 1.0 + param_tol_t:
            continue
        hits.append((tag, min(1.0, max(0.0, s_param)), min(1.0, max(0.0, t_param))))
    return hits


def _occupy(occupancy: dict[tuple[int, int], int], key: tuple[int, int], tag: int) -> None:
    previous = occupancy.get(key)
    occupancy[key] = tag if previous is None else min(previous, tag)


def _nearest_index(value: float, grid: tuple[float, ...], param_tol: float) -> int | None:
    hits = [
        (abs(value - station), index)
        for index, station in enumerate(grid)
        if abs(value - station) <= param_tol
    ]
    if not hits:
        return None
    hits.sort()
    return hits[0][1]


def _interpolate(
    origin: tuple[float, float, float],
    edge_x: tuple[float, float, float],
    edge_y: tuple[float, float, float],
    s_param: float,
    t_param: float,
) -> tuple[float, float, float]:
    return (
        origin[0] + edge_x[0] * s_param + edge_y[0] * t_param,
        origin[1] + edge_x[1] * s_param + edge_y[1] * t_param,
        origin[2] + edge_x[2] * s_param + edge_y[2] * t_param,
    )


def _cross(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _corner_points(
    wall: WallPanel, nodes: dict[int, Node]
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    points: list[tuple[float, float, float]] = []
    for tag in wall.corner_tags():
        node = nodes.get(tag)
        if node is None:
            raise WallMeshError(f"벽체 {wall.tag}의 절점 {tag}가 없습니다.")
        points.append((node.x, node.y, node.z))
    return points[0], points[1], points[2], points[3]


def _assert_rectangle(
    wall_tag: int,
    corners: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> None:
    n1, n2, n3, n4 = corners
    edge_x = _sub(n2, n1)
    edge_y = _sub(n4, n1)
    length_x = _length(edge_x)
    length_y = _length(edge_y)
    scale = max(length_x, length_y, 1.0)
    tol = max(_RECTANGLE_ABS_TOL, _RECTANGLE_REL_TOL * scale)
    if length_x <= tol or length_y <= tol:
        raise WallMeshError(f"벽체 {wall_tag}의 면적이 0이거나 한 변이 퇴화했습니다.")

    expected_n3 = _add(n1, _add(edge_x, edge_y))
    if _length(_sub(n3, expected_n3)) > tol:
        # A planar trapezoid / non-planar warp both fail this: n3 must be
        # n1 + (n2-n1) + (n4-n1). Anything else is not the rectangle this
        # mesher interpolates as a tensor product.
        raise WallMeshError(
            f"벽체 {wall_tag}는 평면 직사각형이 아닙니다. "
            "이번 단계는 네 모서리가 평행사변형이면서 직교하는 벽만 지원합니다."
        )
    if abs(_dot(edge_x, edge_y)) > tol * length_x * length_y / scale:
        raise WallMeshError(f"벽체 {wall_tag}의 인접 변이 직교하지 않습니다.")


def _allocate_tag(current: int) -> int:
    nxt = current + 1
    if nxt >= _SOLVER_DUMMY_TAG_FLOOR:
        raise WallMeshError(
            "생성된 전단벽 절점·요소 번호가 해석기 내부 태그와 겹칩니다."
        )
    return nxt


def _sub(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (first[0] - second[0], first[1] - second[1], first[2] - second[2])


def _add(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (first[0] + second[0], first[1] + second[1], first[2] + second[2])


def _dot(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _length(vector: tuple[float, float, float]) -> float:
    return math.sqrt(_dot(vector, vector))
