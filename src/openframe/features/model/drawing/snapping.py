"""Snap resolution for the free-form drawing canvas.

Drawing arbitrary geometry only feels precise when the cursor lands on the point
the user meant.  These helpers work in model coordinates and know nothing about
Qt, so the same resolution can serve a 2D canvas and a 3D work plane later.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from openframe.core.domain.model import Element, Node

Point = tuple[float, float]

_INTERIOR = 1.0e-9


class SnapKind(StrEnum):
    NODE = "node"
    INTERSECTION = "intersection"
    MIDPOINT = "midpoint"
    MEMBER = "member"
    GRID = "grid"
    FREE = "free"


_LABELS = {
    SnapKind.NODE: "절점",
    SnapKind.INTERSECTION: "교차점",
    SnapKind.MIDPOINT: "중점",
    SnapKind.MEMBER: "부재 위",
    SnapKind.GRID: "그리드",
    SnapKind.FREE: "",
}

_PRIORITY = {
    SnapKind.NODE: 0,
    SnapKind.INTERSECTION: 1,
    SnapKind.MIDPOINT: 2,
    SnapKind.MEMBER: 3,
    SnapKind.GRID: 4,
}


@dataclass(frozen=True, slots=True)
class SnapOptions:
    """Which snap targets the user has enabled."""

    nodes: bool = True
    midpoints: bool = True
    members: bool = True
    intersections: bool = True
    grid: float = 0.5

    @property
    def any_geometry(self) -> bool:
        return self.nodes or self.midpoints or self.members or self.intersections


@dataclass(frozen=True, slots=True)
class SnapResult:
    x: float
    y: float
    kind: SnapKind
    node_tag: int | None = None
    element_tag: int | None = None
    position: float | None = None

    @property
    def point(self) -> Point:
        return (self.x, self.y)

    @property
    def label(self) -> str:
        return _LABELS[self.kind]


def apply_ortho(anchor: Point, point: Point, increment_degrees: float = 90.0) -> Point:
    """Lock the direction from ``anchor`` to the nearest angular increment.

    Keeps the distance the cursor already indicates, so the user still controls
    member length while the angle is held to a clean value.
    """
    length = math.hypot(point[0] - anchor[0], point[1] - anchor[1])
    if length <= _INTERIOR or increment_degrees <= 0.0:
        return point
    angle = math.degrees(math.atan2(point[1] - anchor[1], point[0] - anchor[0]))
    locked = round(angle / increment_degrees) * increment_degrees
    radians = math.radians(locked)
    return (
        anchor[0] + length * math.cos(radians),
        anchor[1] + length * math.sin(radians),
    )


def resolve_snap(
    nodes: Mapping[int, Node],
    elements: Mapping[int, Element],
    point: Point,
    tolerance: float,
    options: SnapOptions | None = None,
) -> SnapResult:
    """Return the best snap target within ``tolerance`` of ``point``.

    Falls back to the raw point so a caller can always draw something; check
    ``result.kind`` when the distinction matters.
    """
    options = options or SnapOptions()
    candidates: list[tuple[int, float, SnapResult]] = []

    if options.nodes:
        candidates.extend(_node_candidates(nodes, point, tolerance))
    if options.intersections:
        candidates.extend(_intersection_candidates(nodes, elements, point, tolerance))
    if options.midpoints or options.members:
        candidates.extend(_member_candidates(nodes, elements, point, tolerance, options))
    if options.grid > 0.0:
        candidates.extend(_grid_candidates(point, tolerance, options.grid))

    if not candidates:
        return SnapResult(point[0], point[1], SnapKind.FREE)
    _, _, best = min(candidates, key=lambda item: (item[0], item[1]))
    return best


def _node_candidates(
    nodes: Mapping[int, Node], point: Point, tolerance: float
) -> list[tuple[int, float, SnapResult]]:
    found = []
    for tag, node in nodes.items():
        gap = math.hypot(node.x - point[0], node.y - point[1])
        if gap <= tolerance:
            found.append(
                (
                    _PRIORITY[SnapKind.NODE],
                    gap,
                    SnapResult(node.x, node.y, SnapKind.NODE, node_tag=tag),
                )
            )
    return found


def _member_candidates(
    nodes: Mapping[int, Node],
    elements: Mapping[int, Element],
    point: Point,
    tolerance: float,
    options: SnapOptions,
) -> list[tuple[int, float, SnapResult]]:
    found = []
    for tag, element in elements.items():
        start = nodes.get(element.node_i)
        end = nodes.get(element.node_j)
        if start is None or end is None:
            continue
        position = _projection_parameter(point, start, end)
        if position is None:
            continue
        projected = _interpolate(start, end, position)
        gap = math.hypot(projected[0] - point[0], projected[1] - point[1])
        if gap > tolerance:
            continue
        midpoint = _interpolate(start, end, 0.5)
        midpoint_gap = math.hypot(midpoint[0] - point[0], midpoint[1] - point[1])
        if options.midpoints and midpoint_gap <= tolerance:
            found.append(
                (
                    _PRIORITY[SnapKind.MIDPOINT],
                    midpoint_gap,
                    SnapResult(
                        midpoint[0],
                        midpoint[1],
                        SnapKind.MIDPOINT,
                        element_tag=tag,
                        position=0.5,
                    ),
                )
            )
        if options.members:
            found.append(
                (
                    _PRIORITY[SnapKind.MEMBER],
                    gap,
                    SnapResult(
                        projected[0],
                        projected[1],
                        SnapKind.MEMBER,
                        element_tag=tag,
                        position=position,
                    ),
                )
            )
    return found


def _intersection_candidates(
    nodes: Mapping[int, Node],
    elements: Mapping[int, Element],
    point: Point,
    tolerance: float,
) -> list[tuple[int, float, SnapResult]]:
    found = []
    ordered = sorted(elements)
    for index, first_tag in enumerate(ordered):
        first = elements[first_tag]
        for second_tag in ordered[index + 1 :]:
            second = elements[second_tag]
            if {first.node_i, first.node_j} & {second.node_i, second.node_j}:
                continue
            crossing = _segment_intersection(nodes, first, second)
            if crossing is None:
                continue
            gap = math.hypot(crossing[0] - point[0], crossing[1] - point[1])
            if gap <= tolerance:
                found.append(
                    (
                        _PRIORITY[SnapKind.INTERSECTION],
                        gap,
                        SnapResult(crossing[0], crossing[1], SnapKind.INTERSECTION),
                    )
                )
    return found


def _grid_candidates(
    point: Point, tolerance: float, spacing: float
) -> list[tuple[int, float, SnapResult]]:
    x = round(point[0] / spacing) * spacing
    y = round(point[1] / spacing) * spacing
    gap = math.hypot(x - point[0], y - point[1])
    if gap > tolerance:
        return []
    return [(_PRIORITY[SnapKind.GRID], gap, SnapResult(x, y, SnapKind.GRID))]


def _segment_intersection(
    nodes: Mapping[int, Node], first: Element, second: Element
) -> Point | None:
    a = nodes.get(first.node_i)
    b = nodes.get(first.node_j)
    c = nodes.get(second.node_i)
    d = nodes.get(second.node_j)
    if a is None or b is None or c is None or d is None:
        return None
    r = (b.x - a.x, b.y - a.y)
    s = (d.x - c.x, d.y - c.y)
    denominator = r[0] * s[1] - r[1] * s[0]
    if abs(denominator) <= _INTERIOR:
        return None
    offset = (c.x - a.x, c.y - a.y)
    t = (offset[0] * s[1] - offset[1] * s[0]) / denominator
    u = (offset[0] * r[1] - offset[1] * r[0]) / denominator
    if not (_INTERIOR < t < 1.0 - _INTERIOR and _INTERIOR < u < 1.0 - _INTERIOR):
        return None
    return (a.x + t * r[0], a.y + t * r[1])


def _projection_parameter(point: Point, start: Node, end: Node) -> float | None:
    dx = end.x - start.x
    dy = end.y - start.y
    length_squared = dx * dx + dy * dy
    if length_squared <= _INTERIOR:
        return None
    parameter = ((point[0] - start.x) * dx + (point[1] - start.y) * dy) / length_squared
    if not _INTERIOR < parameter < 1.0 - _INTERIOR:
        return None
    return parameter


def _interpolate(start: Node, end: Node, position: float) -> Point:
    return (
        start.x + (end.x - start.x) * position,
        start.y + (end.y - start.y) * position,
    )
