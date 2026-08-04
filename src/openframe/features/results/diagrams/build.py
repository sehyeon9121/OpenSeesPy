"""Build per-element force diagrams from raw local end forces."""

from collections.abc import Callable, Iterable

from openframe.core.domain import ElementResult
from openframe.features.results.diagrams import axial, moment, shear
from openframe.features.results.diagrams.base import (
    DiagramKind,
    DiagramPoint,
    MemberDiagram,
)

# 2D beam-column end forces along the member's local axes:
# (N_i, V_i, M_i, N_j, V_j, M_j). These are the forces the element exerts on its nodes,
# so they must be converted to internal forces read continuously from end i to end j.
# Verified against textbook cases (cantilever with tip load; simply supported beam with a
# central point load, where M = PL/4 sagging and V = +P/2 then -P/2):
#   axial   N = -N_i = +N_j   (tension positive)
#   shear   V = +V_i = -V_j
#   moment  M = -M_i = +M_j   (sagging positive)
_LOCAL_FORCE_COUNT = 6

# With a distributed load the moment varies parabolically, so the two end values alone
# would miss the span maximum entirely. The internal forces are then rebuilt from
# equilibrium along the member, verified against a UDL beam (M = wL^2/8 at midspan) and a
# UDL cantilever (M = -wL^2/2 at the fixed end):
#   N(x) = -N_i - wx*x
#   V(x) =  V_i + wy*x
#   M(x) = -M_i + V_i*x + wy*x^2/2
_SPAN_SAMPLES = 20


def member_diagrams(element: ElementResult) -> tuple[MemberDiagram, MemberDiagram, MemberDiagram]:
    forces = element.local_forces
    if len(forces) != _LOCAL_FORCE_COUNT:
        raise ValueError(
            f"부재 {element.element_tag}: 2D elasticBeamColumn 형식의 단부력(6개 값)이 아닙니다."
        )
    axial_i, shear_i, moment_i, axial_j, shear_j, moment_j = forces
    load_x, load_y = element.uniform_load
    length = element.length

    if (load_x == 0.0 and load_y == 0.0) or length <= 0.0:
        return (
            axial.from_end_forces(element.element_tag, -axial_i, axial_j),
            shear.from_end_forces(element.element_tag, shear_i, -shear_j),
            moment.from_end_forces(element.element_tag, -moment_i, moment_j),
        )

    positions = _sample_positions(shear_i, load_y, length)
    return (
        _sampled(
            element.element_tag,
            DiagramKind.AXIAL,
            positions,
            lambda x: -axial_i - load_x * x,
            length,
        ),
        _sampled(
            element.element_tag,
            DiagramKind.SHEAR,
            positions,
            lambda x: shear_i + load_y * x,
            length,
        ),
        _sampled(
            element.element_tag,
            DiagramKind.MOMENT,
            positions,
            lambda x: -moment_i + shear_i * x + load_y * x * x / 2.0,
            length,
        ),
    )


def max_abs_value(diagrams: Iterable[MemberDiagram]) -> float:
    values = [point.value for diagram in diagrams for point in diagram.points]
    return max((abs(value) for value in values), default=0.0)


def _sample_positions(shear_i: float, load_y: float, length: float) -> tuple[float, ...]:
    """Evenly spaced positions plus the exact station where the moment turns.

    Sampling alone can straddle the parabola's vertex and under-report the peak, so the
    stationary point of M(x) - where the shear crosses zero - is added when it lies
    inside the member.
    """
    positions = [index / _SPAN_SAMPLES for index in range(_SPAN_SAMPLES + 1)]
    if load_y != 0.0:
        turning_point = -shear_i / load_y
        if 0.0 < turning_point < length:
            positions.append(turning_point / length)
    return tuple(sorted(set(positions)))


def _sampled(
    element_tag: int,
    kind: DiagramKind,
    positions: tuple[float, ...],
    value_at: Callable[[float], float],
    length: float,
) -> MemberDiagram:
    return MemberDiagram(
        element_tag,
        kind,
        tuple(DiagramPoint(position, value_at(position * length)) for position in positions),
    )
