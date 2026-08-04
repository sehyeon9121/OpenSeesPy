"""Rebuild the displaced shape between a member's two end nodes.

Joining node positions with straight lines hides everything that happens inside a
member: a uniformly loaded span whose ends cannot move is drawn flat even though it
sags. The interior is therefore reconstructed from beam theory, which is exact for the
elastic elements this application solves.

No Qt objects are created here; drawing belongs to the presentation layer.
"""

import math
from dataclasses import dataclass

from openframe.core.domain import AnalysisResult, StructuralModel

#: Stations per member. A member's deflected shape is a quartic at worst, so this is far
#: more than enough to draw a smooth curve.
DEFAULT_SAMPLES = 16


@dataclass(frozen=True, slots=True)
class DeflectionStation:
    """One point along a member: where it was, and how far it moved."""

    position: float  # 0 at end i, 1 at end j
    x: float  # undeformed coordinates
    y: float
    ux: float  # displacement in global axes, unscaled
    uy: float


def member_deflection(
    model: StructuralModel,
    result: AnalysisResult,
    element_tag: int,
    samples: int = DEFAULT_SAMPLES,
) -> tuple[DeflectionStation, ...]:
    """Return stations along one member, or its two ends when the shape is unknown."""
    element = model.elements.get(element_tag)
    if element is None:
        return ()
    node_i = model.nodes.get(element.node_i)
    node_j = model.nodes.get(element.node_j)
    result_i = result.node_results.get(element.node_i)
    result_j = result.node_results.get(element.node_j)
    if node_i is None or node_j is None or result_i is None or result_j is None:
        return ()

    dx = node_j.x - node_i.x
    dy = node_j.y - node_i.y
    length = math.hypot(dx, dy)
    ux_i, uy_i, rotation_i = _components(result_i.displacement)
    ux_j, uy_j, rotation_j = _components(result_j.displacement)

    if length <= 0.0 or samples < 1:
        return (
            DeflectionStation(0.0, node_i.x, node_i.y, ux_i, uy_i),
            DeflectionStation(1.0, node_j.x, node_j.y, ux_j, uy_j),
        )

    cosine = dx / length
    sine = dy / length

    # End displacements resolved onto the member's own axes.
    axial_i = cosine * ux_i + sine * uy_i
    axial_j = cosine * ux_j + sine * uy_j
    transverse_i = -sine * ux_i + cosine * uy_i
    transverse_j = -sine * ux_j + cosine * uy_j

    element_result = result.element_results.get(element_tag)
    load_y = element_result.uniform_load[1] if element_result is not None else 0.0
    rigidity = element_result.flexural_rigidity if element_result is not None else 0.0

    stations: list[DeflectionStation] = []
    for index in range(samples + 1):
        ratio = index / samples
        distance = ratio * length

        axial = axial_i + (axial_j - axial_i) * ratio
        transverse = _hermite(
            ratio, length, transverse_i, rotation_i, transverse_j, rotation_j
        ) + _clamped_sag(distance, length, load_y, rigidity)

        stations.append(
            DeflectionStation(
                position=ratio,
                x=node_i.x + dx * ratio,
                y=node_i.y + dy * ratio,
                ux=cosine * axial - sine * transverse,
                uy=sine * axial + cosine * transverse,
            )
        )
    return tuple(stations)


def _components(displacement: tuple[float, ...]) -> tuple[float, float, float]:
    padded = (*displacement, 0.0, 0.0, 0.0)
    return float(padded[0]), float(padded[1]), float(padded[2])


def _hermite(
    ratio: float,
    length: float,
    start_value: float,
    start_slope: float,
    end_value: float,
    end_slope: float,
) -> float:
    """Cubic that matches both end deflections and both end rotations."""
    squared = ratio * ratio
    cubed = squared * ratio
    return (
        (1.0 - 3.0 * squared + 2.0 * cubed) * start_value
        + length * (ratio - 2.0 * squared + cubed) * start_slope
        + (3.0 * squared - 2.0 * cubed) * end_value
        + length * (cubed - squared) * end_slope
    )


def _clamped_sag(distance: float, length: float, load_y: float, rigidity: float) -> float:
    """Extra sag a cubic cannot express, i.e. the clamped-clamped shape under w.

    Peaks at w*L^4/(384*EI) mid-span, the textbook fixed-end deflection.
    """
    if load_y == 0.0 or rigidity <= 0.0:
        return 0.0
    remaining = length - distance
    return load_y * distance * distance * remaining * remaining / (24.0 * rigidity)
