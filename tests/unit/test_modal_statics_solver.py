import math

import pytest

from openframe.core.domain import AnalysisStatus, BoundaryCondition, Element, Node, StructuralModel
from openframe.features.analysis.statics import ModalStaticsSolver

_LENGTH = 4.0
_E = 200_000.0
_A = 0.02
_I = 0.0001
_DENSITY = 10.0
_GRAVITY = 9.81


def _cantilever(*, density: float = _DENSITY) -> StructuralModel:
    return StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, _LENGTH, 0.0)},
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties={"E": _E, "A": _A, "I": _I, "density": density},
            )
        },
        boundaries=[BoundaryCondition(1, (True, True, True))],
    )


def test_cantilever_bending_and_axial_modes_match_the_lumped_mass_hand_calculation() -> None:
    """A cantilever with mass lumped only at its free tip (half its own self-
    weight) reduces to two independent single-dof oscillators - closed form,
    independent of this codebase: omega = sqrt(k/m) with k = 3EI/L^3 for the
    transverse/bending mode and k = EA/L for the axial one."""
    model = _cantilever()

    result = ModalStaticsSolver().solve(model, num_modes=2, length_unit="m")

    assert result.status == AnalysisStatus.COMPLETED
    modes = result.mode_shapes
    assert len(modes) == 2

    tip_mass = (_DENSITY * _A * _LENGTH / 2.0) / _GRAVITY
    expected_bending = math.sqrt(3 * _E * _I / _LENGTH**3 / tip_mass)
    expected_axial = math.sqrt(_E * _A / _LENGTH / tip_mass)

    assert modes[0].angular_frequency == pytest.approx(expected_bending, rel=1e-6)
    assert modes[1].angular_frequency == pytest.approx(expected_axial, rel=1e-6)
    # The softer (bending) mode is always the fundamental (longer period) one.
    assert modes[0].period > modes[1].period


def test_rejects_a_model_missing_real_material_on_any_element() -> None:
    model = StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, _LENGTH, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
        boundaries=[BoundaryCondition(1, (True, True, True))],
    )

    result = ModalStaticsSolver().solve(model, num_modes=1)

    assert result.status == AnalysisStatus.FAILED
    assert "재료" in result.messages[0]


def test_rejects_a_model_with_no_mass() -> None:
    model = _cantilever(density=0.0)

    result = ModalStaticsSolver().solve(model, num_modes=1)

    assert result.status == AnalysisStatus.FAILED
    assert "질량" in result.messages[0]


def test_rejects_a_truss_only_model() -> None:
    model = StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, _LENGTH, 0.0)},
        elements={1: Element(1, 1, 2, "truss", properties={"A": _A, "material_tag": 1})},
        boundaries=[BoundaryCondition(1, (True, True))],
    )

    result = ModalStaticsSolver().solve(model, num_modes=1)

    assert result.status == AnalysisStatus.FAILED
    assert "트러스" in result.messages[0]


def test_rejects_a_3d_model() -> None:
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, _LENGTH, 0.0, 0.0)},
        elements={
            1: Element(
                1, 1, 2, "elasticBeamColumn", properties={"E": _E, "A": _A, "I": _I, "density": _DENSITY}
            )
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )

    result = ModalStaticsSolver().solve(model, num_modes=1)

    assert result.status == AnalysisStatus.FAILED
    assert "2D" in result.messages[0]


def test_gravity_constant_is_selected_from_the_length_unit() -> None:
    """The SAME density/area/E/I numbers, only the length_unit string changes:
    "mm" picks g=9810 (1000x "m"'s 9.81), so mass = W/g comes out 1000x SMALLER
    in mm - and since omega = sqrt(k/m), a 1000x smaller mass with the SAME
    stiffness gives exactly sqrt(1000) times the angular frequency, not a
    different one by some unpredictable amount."""
    model = _cantilever()

    result_m = ModalStaticsSolver().solve(model, num_modes=1, length_unit="m")
    result_mm = ModalStaticsSolver().solve(model, num_modes=1, length_unit="mm")

    assert result_m.status == AnalysisStatus.COMPLETED
    assert result_mm.status == AnalysisStatus.COMPLETED
    ratio = result_mm.mode_shapes[0].angular_frequency / result_m.mode_shapes[0].angular_frequency
    assert ratio == pytest.approx(math.sqrt(1000.0), rel=1e-6)
