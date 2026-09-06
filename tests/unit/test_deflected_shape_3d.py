"""A 3D frame's rebuilt centreline must bow, not follow the displaced chord."""

import math

import pytest

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    BoundaryCondition,
    Element,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.deformation.deflected_shape import member_deflection


def _fixed_cantilever() -> tuple[StructuralModel, float, float]:
    """Vertical column matching the reported 오류3.ofsm layout: i at the tip,
    j at the origin, 6-DOF fixity at the base, +X load at the top.
    """
    length = 5.0
    tip_ux = 0.03029510400218319
    tip_ry = 1.5 * tip_ux / length
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 0.0, 0.0, length, 6),
        },
        elements={1: Element(1, 2, 1, "frame")},
        boundaries=[BoundaryCondition(1, (True, True, True, True, True, True))],
    )
    return model, tip_ux, tip_ry


def _cantilever_result(tip_ux: float, tip_ry: float) -> AnalysisResult:
    return AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
            2: NodeResult(2, displacement=(tip_ux, 0.0, 0.0, 0.0, tip_ry, 0.0)),
        },
    )


def test_fixed_3d_cantilever_centreline_is_not_the_displaced_chord() -> None:
    """The solver's tip Δ is PL³/3EI with zero base rotation. Joining those
    two nodes with a straight stick is a hinge picture; the cubic through
    the end rotation must sit *inside* the chord (textbook midspan 5/16 of
    the tip displacement, not 1/2).
    """
    model, tip_ux, tip_ry = _fixed_cantilever()
    stations = member_deflection(model, _cantilever_result(tip_ux, tip_ry), 1, samples=8)

    assert stations[0].position == 0.0
    assert stations[-1].position == 1.0
    assert stations[0].ux == pytest.approx(tip_ux)
    assert stations[-1].ux == pytest.approx(0.0)

    mid = next(item for item in stations if item.position == pytest.approx(0.5))
    chord_mid = 0.5 * tip_ux
    # Finite-rotation Hermite is a hair off the small-angle 5/16 tip value;
    # what matters is that it is the cantilever cubic, not the chord.
    assert mid.ux == pytest.approx(0.3125 * tip_ux, rel=1e-4)
    assert abs(mid.ux - chord_mid) > 0.1 * tip_ux


def test_fixed_base_stays_vertical_on_the_first_station_step() -> None:
    """Zero rotation at the support must keep the rebuilt tangent along the
    undeformed column, otherwise the cubic still looks hinged at the base.
    """
    model, tip_ux, tip_ry = _fixed_cantilever()
    stations = member_deflection(model, _cantilever_result(tip_ux, tip_ry), 1, samples=8)
    near_base = stations[-2]
    dx = stations[-1].x + stations[-1].ux - (near_base.x + near_base.ux)
    dz = stations[-1].z + stations[-1].uz - (near_base.z + near_base.uz)
    slope = abs(dx / dz) if abs(dz) > 1.0e-12 else math.inf
    chord_slope = tip_ux / 5.0
    assert slope < 0.25 * chord_slope


def test_truss_stays_a_straight_chord() -> None:
    model, tip_ux, _tip_ry = _fixed_cantilever()
    model.elements[1] = Element(1, 2, 1, "truss")
    stations = member_deflection(model, _cantilever_result(tip_ux, 0.0), 1, samples=8)
    assert len(stations) == 2
