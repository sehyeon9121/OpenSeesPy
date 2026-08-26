"""Lumped-plasticity pushover (``solve_nonlinear_static``) - a Steel01
moment-rotation hinge at each end of a qualifying member (see
``apply_full_section_to_selection``'s "Fy"/"Zy"/"Zz" keys and
``MaterialFreeStaticsSolver._build_plastic_hinge``).

A cantilever is *statically determinate*, so its bending-moment diagram
(M(x) = P*(L-x)) is fixed by equilibrium alone regardless of material
behaviour - yielding the base hinge does not change the base moment, only
the *rotation* it takes to carry that moment. The verification below is
therefore built on tip displacement, not on the moment ever being "capped":

    delta = P*L**3/(3*E*I) + theta_hinge(M_base) * L

where the hinge's own bilinear (elastic-then-hardening) backbone gives

    theta_hinge(M) = Mp/K0                         if M <= Mp
                   = Mp/K0 + (M - Mp)/(b*K0)        if M > Mp

(K0 = solver.py's own ``_HINGE_STIFFNESS``, the same rigid-hinge constant
already used for a plain moment release). Both branches were independently
hand-derived and cross-checked against a monotonic Steel01 push before being
written here.
"""

import pytest

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver

_HINGE_STIFFNESS = 1.0e8
_LENGTH = 4.0
_ELASTIC = 200000.0
_INERTIA = 0.0002
_PROPERTIES = {
    "E": _ELASTIC,
    "A": 0.02,
    "G": 80000.0,
    "J": 0.0005,
    "Iy": _INERTIA,
    "Iz": _INERTIA,
}


def _cantilever(load: float, *, fy: float, z: float, hardening_ratio: float = 0.02) -> StructuralModel:
    properties = dict(_PROPERTIES)
    if fy > 0.0:
        properties["Fy"] = fy
        properties["Zy"] = z
        properties["Zz"] = z
        properties["StrainHardeningRatio"] = hardening_ratio
    return StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, _LENGTH, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame", properties=properties)},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(2, (0.0, 0.0, -load, 0.0, 0.0, 0.0))],
    )


def test_a_load_well_below_yield_matches_the_plain_elastic_cantilever() -> None:
    """The hinge's own initial stiffness (K0=1e8) is so much stiffer than the
    beam's EI that its pre-yield flexibility is negligible - a member with
    Fy set should behave (almost) exactly like one without, as long as it
    never actually yields."""
    load = 10.0
    model = _cantilever(load, fy=2000.0, z=1.0)

    result = MaterialFreeStaticsSolver().solve_nonlinear_static(
        model, control_node=2, control_dof=3, num_steps=10
    )

    assert result.status == AnalysisStatus.COMPLETED
    expected = load * _LENGTH**3 / (3 * _ELASTIC * _INERTIA)
    assert result.node_results[2].displacement[2] == pytest.approx(-expected, rel=1.0e-4)


def test_pushing_past_the_plastic_moment_adds_hinge_rotation_to_the_tip_deflection() -> None:
    fy = 2000.0
    z = 1.0
    hardening_ratio = 0.02
    load = 750.0  # base moment = 750*4 = 3000 > Mp = fy*z = 2000
    model = _cantilever(load, fy=fy, z=z, hardening_ratio=hardening_ratio)

    result = MaterialFreeStaticsSolver().solve_nonlinear_static(
        model, control_node=2, control_dof=3, num_steps=20, tolerance=1.0e-9, max_iterations=50
    )

    assert result.status == AnalysisStatus.COMPLETED
    assert result.convergence is not None
    assert result.convergence.converged

    mp = fy * z
    base_moment = load * _LENGTH
    assert base_moment > mp
    theta_hinge = mp / _HINGE_STIFFNESS + (base_moment - mp) / (hardening_ratio * _HINGE_STIFFNESS)
    elastic_deflection = load * _LENGTH**3 / (3 * _ELASTIC * _INERTIA)
    expected = elastic_deflection + theta_hinge * _LENGTH

    assert result.node_results[2].displacement[2] == pytest.approx(-expected, rel=1.0e-4)
    # A genuinely useful check that this is not just reproducing the elastic
    # answer: yielding must make the tip strictly softer than pure elastic
    # theory (theta_hinge is strictly positive once base_moment > mp).
    assert abs(result.node_results[2].displacement[2]) > elastic_deflection


def test_a_member_with_no_yield_strength_never_gets_a_hinge_and_stays_purely_elastic() -> None:
    load = 750.0
    model = _cantilever(load, fy=0.0, z=0.0)

    result = MaterialFreeStaticsSolver().solve_nonlinear_static(
        model, control_node=2, control_dof=3, num_steps=10
    )

    assert result.status == AnalysisStatus.COMPLETED
    expected = load * _LENGTH**3 / (3 * _ELASTIC * _INERTIA)
    assert result.node_results[2].displacement[2] == pytest.approx(-expected, rel=1.0e-6)
    assert any("탄성으로 거동" in message for message in result.messages)


def test_2d_models_are_rejected_since_the_hinge_is_a_3d_only_feature() -> None:
    model = StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, _LENGTH, 0.0)},
        elements={1: Element(1, 1, 2, "frame", properties={"E": _ELASTIC, "A": 0.02, "I": _INERTIA})},
        boundaries=[BoundaryCondition(1, (True, True, True))],
        nodal_loads=[NodalLoad(2, (0.0, -10.0, 0.0))],
    )

    result = MaterialFreeStaticsSolver().solve_nonlinear_static(model, control_node=2, control_dof=2)

    assert result.status == AnalysisStatus.FAILED


def test_displacement_control_and_arc_length_refuse_rather_than_run_silently_wrong() -> None:
    model = _cantilever(10.0, fy=2000.0, z=1.0)

    for integrator_type in ("DisplacementControl", "ArcLength"):
        result = MaterialFreeStaticsSolver().solve_nonlinear_static(
            model, control_node=2, control_dof=3, integrator_type=integrator_type
        )
        assert result.status == AnalysisStatus.FAILED
        assert "Load Control" in result.messages[0]
