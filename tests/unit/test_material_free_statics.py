import pytest

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
    UniformElementLoad,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy
from openframe.features.results.diagrams import member_diagrams


def _simply_supported_beam() -> StructuralModel:
    return StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[
            BoundaryCondition(1, (True, True, False)),
            BoundaryCondition(2, (False, True, False)),
        ],
        element_loads=[UniformElementLoad(1, wy=-10.0)],
    )


def test_determinate_beam_is_solved_without_material_properties() -> None:
    model = _simply_supported_beam()

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[1].reaction[1] == pytest.approx(20.0)
    assert result.node_results[2].reaction[1] == pytest.approx(20.0)
    _, shear, moment = member_diagrams(result.element_results[1])
    assert max(point.value for point in moment.points) == pytest.approx(20.0)
    assert shear.points[0].value == pytest.approx(20.0)
    assert shear.points[-1].value == pytest.approx(-20.0)


def test_cantilever_point_load_reaction_and_moment() -> None:
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 3.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True, True, True))],
        nodal_loads=[NodalLoad(2, (0.0, -12.0, 0.0))],
    )

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[1].reaction[1] == pytest.approx(12.0)
    assert result.node_results[1].reaction[2] == pytest.approx(36.0)


def test_gerber_beam_is_determinate_through_its_hinge() -> None:
    """Cantilever plus a suspended span: determinate only because of the release."""
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0), 3: Node(3, 8.0, 0.0)},
        elements={
            1: Element(1, 1, 2, "frame"),
            2: Element(2, 2, 3, "frame", moment_release_i=True),
        },
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(3, (False, True, False)),
        ],
        element_loads=[UniformElementLoad(2, wy=-10.0)],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[3].reaction[1] == pytest.approx(20.0)
    assert result.node_results[1].reaction[1] == pytest.approx(20.0)
    assert result.node_results[1].reaction[2] == pytest.approx(80.0)
    assert result.element_results[2].local_forces[2] == pytest.approx(0.0, abs=1.0e-9)


def test_three_hinge_gable_frame_carries_thrust_and_keeps_the_apex_free() -> None:
    model = StructuralModel(
        nodes={
            1: Node(1, 0.0, 0.0),
            2: Node(2, 0.0, 4.0),
            3: Node(3, 5.0, 6.0),
            4: Node(4, 10.0, 4.0),
            5: Node(5, 10.0, 0.0),
        },
        elements={
            1: Element(1, 1, 2, "frame"),
            2: Element(2, 2, 3, "frame"),
            3: Element(3, 3, 4, "frame", moment_release_i=True),
            4: Element(4, 4, 5, "frame"),
        },
        boundaries=[
            BoundaryCondition(1, (True, True, False)),
            BoundaryCondition(5, (True, True, False)),
        ],
        nodal_loads=[NodalLoad(3, (0.0, -20.0, 0.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[1].reaction[1] == pytest.approx(10.0)
    assert result.node_results[5].reaction[1] == pytest.approx(10.0)
    thrust = 10.0 * 5.0 / 6.0
    assert abs(result.node_results[1].reaction[0]) == pytest.approx(thrust)
    assert result.node_results[1].reaction[0] == pytest.approx(
        -result.node_results[5].reaction[0]
    )
    assert result.element_results[3].local_forces[2] == pytest.approx(0.0, abs=1.0e-9)


def test_hinge_release_lowers_the_determinacy_degree() -> None:
    model = _simply_supported_beam()
    model.boundaries[1] = BoundaryCondition(2, (True, True, True))
    assert check_determinacy(model).degree == 2

    model.elements[1] = Element(1, 1, 2, "frame", moment_release_j=True)
    assert check_determinacy(model).degree == 1


def test_inclined_roller_reaction_matches_hand_calculated_equilibrium() -> None:
    """Beam pinned at A, resting on a roller at B whose surface is tilted 30 deg.

    Hand solution (P=10 down at B, incline theta=30 deg from horizontal, roller
    restrains only the direction normal to its own sliding surface):
        R_B = P / cos(theta) = 11.5470
        A = (R_B sin(theta), P - R_B cos(theta)) = (5.7735, 0.0)
        B = R_B * (-sin(theta), cos(theta)) = (-5.7735, 10.0)
    """
    theta = 30.0
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 6.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[
            BoundaryCondition(1, (True, True, False)),
            BoundaryCondition(2, (False, True, False), angle=theta),
        ],
        nodal_loads=[NodalLoad(2, (0.0, -10.0, 0.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    a = result.node_results[1].reaction
    b = result.node_results[2].reaction
    assert a[0] == pytest.approx(5.7735, abs=1.0e-3)
    assert a[1] == pytest.approx(0.0, abs=1.0e-3)
    assert b[0] == pytest.approx(-5.7735, abs=1.0e-3)
    assert b[1] == pytest.approx(10.0, abs=1.0e-3)
    # Equilibrium must hold regardless of how the reaction was recovered.
    assert a[0] + b[0] == pytest.approx(0.0, abs=1.0e-3)
    assert a[1] + b[1] == pytest.approx(10.0, abs=1.0e-3)


def test_an_inclined_pin_still_restrains_the_full_reaction_it_should() -> None:
    """A fully-fixed inclined support (both local directions) is just a rotated fixed
    end: the total reaction still balances the applied load however it is angled."""
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True, True, True), angle=40.0)],
        nodal_loads=[NodalLoad(2, (0.0, -12.0, 0.0))],
    )

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    reaction = result.node_results[1].reaction
    assert reaction[1] == pytest.approx(12.0, abs=1.0e-3)
    assert reaction[0] == pytest.approx(0.0, abs=1.0e-3)
    assert reaction[2] == pytest.approx(48.0, abs=1.0e-2)


def test_zero_angle_support_takes_the_exact_ops_fix_path_unchanged() -> None:
    """angle=0.0 must reproduce the original bit-exact behaviour, not the penalty one."""
    model = _simply_supported_beam()
    model.boundaries[0] = BoundaryCondition(1, (True, True, False), angle=0.0)

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.node_results[1].reaction[1] == pytest.approx(20.0, abs=1.0e-9)
    assert result.node_results[2].reaction[1] == pytest.approx(20.0, abs=1.0e-9)


def test_a_determinate_2d_truss_matches_hand_calculated_reactions() -> None:
    """Two-bar A-frame, both bases pinned: (2,2) restraints x 2 joints = 4
    reactions, 2 members, 3 joints -> m + r - 2j = 2 + 4 - 6 = 0, determinate.

    This is also the regression test for a solver bug where `element truss`
    was called with a raw modulus in the material-tag slot instead of an actual
    material tag, which OpenSees rejects outright — no truss model could ever be
    solved through this path before the fix.
    """
    model = StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0), 3: Node(3, 2.0, 3.0)},
        elements={1: Element(1, 1, 3, "truss"), 2: Element(2, 2, 3, "truss")},
        boundaries=[
            BoundaryCondition(1, (True, True)),
            BoundaryCondition(2, (True, True)),
        ],
        nodal_loads=[NodalLoad(3, (0.0, -12.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[1].reaction == pytest.approx((4.0, 6.0), abs=1.0e-6)
    assert result.node_results[2].reaction == pytest.approx((-4.0, 6.0), abs=1.0e-6)


def test_indeterminate_beam_requires_stiffness_instead_of_using_fake_values() -> None:
    model = _simply_supported_beam()
    model.boundaries[1] = BoundaryCondition(2, (True, True, False))

    check = check_determinacy(model)
    result = MaterialFreeStaticsSolver().solve(model)

    assert check.degree == 1
    assert result.status == AnalysisStatus.FAILED
    assert "부정정" in result.messages[0]
