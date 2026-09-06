"""Rectangular structured quad mesher for a single planar ``WallPanel``.

This is deliberately not a general surface mesher. Opening, story-level
seeds, beam intersections and transition elements are out of scope: adding
them here would hide the fact that the Phase-1 wall is a tensor-product
grid on a rectangle, which is the only connectivity Linear Static needs
for the ASDShellQ4 vertical slice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from openframe.core.domain.model import Node, NodeOrigin, StructuralModel
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
) -> tuple[int, int, dict[int, Node], dict[int, ShellQuad]]:
    """Build an ``nx × ny`` tensor-product quad mesh on ``wall``.

    Corner grid stations reuse the four authored node tags; every other
    station is a new ``NodeOrigin.WALL_MESH`` node. Visit order is row-major
    in (iy, ix) with iy along ``n1→n4`` and ix along ``n1→n2``, matching the
    ASDShellQ4 spike so a 2×2 OpenFrame wall is the same connectivity as
    the engine-only test.
    """
    errors = wall.validate()
    if errors:
        raise WallMeshError(errors[0])

    corners = _corner_points(wall, nodes)
    _assert_rectangle(wall.tag, corners)
    origin, edge_x, edge_y = corners[0], _sub(corners[1], corners[0]), _sub(corners[3], corners[0])
    nx, ny = wall.nx, wall.ny
    ndf = nodes[wall.node_1].ndf

    grid: dict[tuple[int, int], int] = {
        (0, 0): wall.node_1,
        (nx, 0): wall.node_2,
        (nx, ny): wall.node_3,
        (0, ny): wall.node_4,
    }
    generated: dict[int, Node] = {}
    current_node = next_node_tag
    for iy in range(ny + 1):
        for ix in range(nx + 1):
            if (ix, iy) in grid:
                continue
            current_node = _allocate_tag(current_node)
            sx = ix / nx
            sy = iy / ny
            point = (
                origin[0] + edge_x[0] * sx + edge_y[0] * sy,
                origin[1] + edge_x[1] * sx + edge_y[1] * sy,
                origin[2] + edge_x[2] * sx + edge_y[2] * sy,
            )
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
    for iy in range(ny):
        for ix in range(nx):
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
