"""Rebuild the displaced shape between a member's two end nodes.

Joining node positions with straight lines hides everything that happens inside a
member: a uniformly loaded span whose ends cannot move is drawn flat even though it
sags. The interior is therefore reconstructed from beam theory, which is exact for the
elastic elements this application solves.

No Qt objects are created here; drawing belongs to the presentation layer.
"""

import math
from dataclasses import dataclass

from openframe.core.domain import (
    AnalysisResult,
    Element,
    Node,
    NodeResult,
    StructuralModel,
    rotate_about_axis,
)

#: Stations per member. A member's deflected shape is a quartic at worst, so this is far
#: more than enough to draw a smooth curve.
DEFAULT_SAMPLES = 16

#: 3D result overlay tessellates each frame member into this many cubes.
#: Spatial N/V/M ribbons already use 8 stations; 16 (the 2D curve default)
#: would double Quick3D instances for a shape that is at most cubic.
DEFORMED_3D_SAMPLES = 8

_TRUSS_TYPES = frozenset({"truss", "corottruss"})


@dataclass(frozen=True, slots=True)
class DeflectionStation:
    """One point along a member: where it was, and how far it moved."""

    position: float  # 0 at end i, 1 at end j
    x: float  # undeformed coordinates
    y: float
    ux: float  # displacement in global axes, unscaled
    uy: float
    z: float = 0.0
    uz: float = 0.0


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

    if model.ndm == 3:
        return _member_deflection_3d(element, node_i, node_j, result_i, result_j, samples)

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
    load_y_i, load_y_j = (0.0, 0.0)
    if element_result is not None:
        _, load_y_i, _, load_y_j = element_result.uniform_load
    rigidity = element_result.flexural_rigidity if element_result is not None else 0.0

    stations: list[DeflectionStation] = []
    for index in range(samples + 1):
        ratio = index / samples
        distance = ratio * length

        axial = axial_i + (axial_j - axial_i) * ratio
        transverse = _hermite(
            ratio, length, transverse_i, rotation_i, transverse_j, rotation_j
        ) + _clamped_sag(distance, length, load_y_i, load_y_j, rigidity)

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


def deflected_polyline(
    model: StructuralModel,
    result: AnalysisResult,
    element_tag: int,
    scale: float,
    samples: int = DEFORMED_3D_SAMPLES,
) -> tuple[tuple[float, float, float], ...]:
    """Scaled structural-space points along one member's rebuilt centreline."""
    stations = member_deflection(model, result, element_tag, samples=samples)
    return tuple(
        (item.x + item.ux * scale, item.y + item.uy * scale, item.z + item.uz * scale)
        for item in stations
    )


def _member_deflection_3d(
    element: Element,
    node_i: Node,
    node_j: Node,
    result_i: NodeResult,
    result_j: NodeResult,
    samples: int,
) -> tuple[DeflectionStation, ...]:
    """Cubic Hermite through the two displaced ends, matching each end's rotation.

    A 3D result view used to draw one cube between the displaced nodes. That
    chord is exact for a truss; for a frame it hides bending, so a fixed
    cantilever looks like a hinged stick even when the solver's tip Δ is
    PL³/3EI and the base rotations are zero. The 2D overlay already rebuilds
    this cubic from end translation + RZ; here the same cubic is built from
    the 3D rotation *vector* so we do not have to pick a local y/z pairing
    (θy vs −θy flips with vecxz).
    """
    ux_i, uy_i, uz_i = _translation_3d(result_i.displacement)
    ux_j, uy_j, uz_j = _translation_3d(result_j.displacement)
    start = (
        DeflectionStation(0.0, node_i.x, node_i.y, ux_i, uy_i, z=node_i.z, uz=uz_i),
        DeflectionStation(1.0, node_j.x, node_j.y, ux_j, uy_j, z=node_j.z, uz=uz_j),
    )
    if element.element_type.lower() in _TRUSS_TYPES or samples < 1:
        return start

    axis = (node_j.x - node_i.x, node_j.y - node_i.y, node_j.z - node_i.z)
    length = math.sqrt(sum(component * component for component in axis))
    if length <= 1.0e-12:
        return start

    p0 = (node_i.x + ux_i, node_i.y + uy_i, node_i.z + uz_i)
    p1 = (node_j.x + ux_j, node_j.y + uy_j, node_j.z + uz_j)
    m0 = _rotate_by_omega(axis, _rotation_vector(result_i.displacement))
    m1 = _rotate_by_omega(axis, _rotation_vector(result_j.displacement))

    stations: list[DeflectionStation] = []
    for index in range(samples + 1):
        ratio = index / samples
        point = _hermite_point(ratio, p0, m0, p1, m1)
        undeformed = (
            node_i.x + axis[0] * ratio,
            node_i.y + axis[1] * ratio,
            node_i.z + axis[2] * ratio,
        )
        stations.append(
            DeflectionStation(
                position=ratio,
                x=undeformed[0],
                y=undeformed[1],
                ux=point[0] - undeformed[0],
                uy=point[1] - undeformed[1],
                z=undeformed[2],
                uz=point[2] - undeformed[2],
            )
        )
    return tuple(stations)


def _translation_3d(displacement: tuple[float, ...]) -> tuple[float, float, float]:
    padded = (*displacement, 0.0, 0.0, 0.0)
    ux, uy, uz = float(padded[0]), float(padded[1]), float(padded[2])
    if not (math.isfinite(ux) and math.isfinite(uy) and math.isfinite(uz)):
        return 0.0, 0.0, 0.0
    return ux, uy, uz


def _rotation_vector(displacement: tuple[float, ...]) -> tuple[float, float, float]:
    padded = (*displacement, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)[:6]
    rx, ry, rz = float(padded[3]), float(padded[4]), float(padded[5])
    if not (math.isfinite(rx) and math.isfinite(ry) and math.isfinite(rz)):
        return 0.0, 0.0, 0.0
    return rx, ry, rz


def _rotate_by_omega(
    vector: tuple[float, float, float], omega: tuple[float, float, float]
) -> tuple[float, float, float]:
    angle = math.sqrt(sum(component * component for component in omega))
    if angle <= 1.0e-15:
        return vector
    axis = tuple(component / angle for component in omega)
    return rotate_about_axis(vector, axis, angle)


def _hermite_point(
    ratio: float,
    start: tuple[float, float, float],
    start_tangent: tuple[float, float, float],
    end: tuple[float, float, float],
    end_tangent: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Cubic that matches both end positions and both end tangents (dP/d ratio)."""
    squared = ratio * ratio
    cubed = squared * ratio
    h00 = 1.0 - 3.0 * squared + 2.0 * cubed
    h10 = ratio - 2.0 * squared + cubed
    h01 = 3.0 * squared - 2.0 * cubed
    h11 = cubed - squared
    return tuple(
        h00 * start[index]
        + h10 * start_tangent[index]
        + h01 * end[index]
        + h11 * end_tangent[index]
        for index in range(3)
    )


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


def _clamped_sag(
    distance: float, length: float, load_y_i: float, load_y_j: float, rigidity: float
) -> float:
    """Extra sag a cubic cannot express, i.e. the clamped-clamped shape under a
    load varying linearly from w_i at end i to w_j at end j (w_i == w_j is the
    plain uniform case).

    Solving EI*y'''' = w_i + (w_j-w_i)*x/L with y(0)=y'(0)=y(L)=y'(L)=0 (the
    "clamped-clamped" boundary conditions - the actual end displacement/rotation
    are already carried by the Hermite term this is added to, same as the
    uniform case) gives, at x == distance:

        y(x) = x^2 * (L*(3L^2 w_i + 2L^2 w_j - 7L w_i x - 3L w_j x + 5 w_i x^2)
                       + x^3 (w_j - w_i)) / (120 * EI * L)

    Independently re-derived and cross-checked three ways: by hand (double
    integration + boundary-condition solve), with sympy's dsolve, and against a
    finite-difference BVP solve (agreed to ~1e-6 relative error). Reduces
    exactly to the uniform-load formula w*x^2*(L-x)^2/(24*EI) - peaking at
    w*L^4/(384*EI) mid-span, the textbook fixed-end deflection - when
    w_i == w_j, which is verified in tests/integration/test_deflected_shape.py.
    """
    if (load_y_i == 0.0 and load_y_j == 0.0) or rigidity <= 0.0 or length <= 0.0:
        return 0.0
    x = distance
    return (
        x * x
        * (
            length
            * (
                3.0 * length * length * load_y_i
                + 2.0 * length * length * load_y_j
                - 7.0 * length * load_y_i * x
                - 3.0 * length * load_y_j * x
                + 5.0 * load_y_i * x * x
            )
            + x ** 3 * (load_y_j - load_y_i)
        )
        / (120.0 * rigidity * length)
    )
