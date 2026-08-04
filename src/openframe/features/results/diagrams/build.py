"""Build per-element force diagrams from raw local end forces."""

from collections.abc import Iterable

from openframe.core.domain import ElementResult
from openframe.features.results.diagrams import axial, moment, shear
from openframe.features.results.diagrams.base import MemberDiagram

# 2D elasticBeamColumn local forces from OpenSeesPy's eleForce(): (N_i, V_i, M_i, N_j, V_j, M_j).
# With no interior span load, N and V at the two ends are an equal-and-opposite nodal
# equilibrium pair, so the j-end value is negated to read as one continuous internal force.
# M is already continuous as returned (verified against a hand-calculated cantilever).
_LOCAL_FORCE_COUNT = 6


def member_diagrams(element: ElementResult) -> tuple[MemberDiagram, MemberDiagram, MemberDiagram]:
    forces = element.local_forces
    if len(forces) != _LOCAL_FORCE_COUNT:
        raise ValueError(
            f"부재 {element.element_tag}: 2D elasticBeamColumn 형식의 단부력(6개 값)이 아닙니다."
        )
    axial_i, shear_i, moment_i, axial_j, shear_j, moment_j = forces
    return (
        axial.from_end_forces(element.element_tag, axial_i, -axial_j),
        shear.from_end_forces(element.element_tag, shear_i, -shear_j),
        moment.from_end_forces(element.element_tag, moment_i, moment_j),
    )


def max_abs_value(diagrams: Iterable[MemberDiagram]) -> float:
    values = [point.value for diagram in diagrams for point in diagram.points]
    return max((abs(value) for value in values), default=0.0)
