"""P-Delta (geometric nonlinearity) toggle for the canvas/free-modeling solver.

Verification strategy, since there is no single closed form that covers the
whole range: (1) at zero axial load, PDelta must degenerate EXACTLY to the
ordinary linear (first-order) result - a hard equality check, not an
approximation. (2) deflection must grow monotonically as the compressive axial
load approaches the Euler buckling load - the qualitatively correct direction.
(3) at LOW axial load (P/Pe <= 0.3), OpenSees' single-element P-Delta
transformation is cross-checked against the exact trigonometric beam-column
closed form (Timoshenko, "Theory of Elastic Stability"): a cantilever with tip
axial P and tip lateral H deflects delta = (H/P)*(tan(kL)/k - L), k=sqrt(P/EI).
This is NOT expected to hold near buckling: a single 2-node element's
linearized geometric stiffness under-predicts the true (sharply nonlinear,
tan()-shaped) amplification as P approaches Pe - a well-documented modeling
limitation of one-element-per-member P-Delta, not a bug (see
test_error_grows_as_the_axial_load_approaches_buckling, which documents this
explicitly instead of silently asserting a false level of accuracy there).
"""

import math

import pytest

from openframe.core.domain import AnalysisStatus, BoundaryCondition, Element, NodalLoad, Node, StructuralModel
from openframe.features.analysis.statics import MaterialFreeStaticsSolver

_LENGTH = 4.0
_E = 200_000.0
_A = 0.02
_I = 0.0001
_LATERAL_LOAD = 1.0
#: Euler buckling load for a cantilever (effective length factor K=2).
_EULER_LOAD = math.pi**2 * _E * _I / (2 * _LENGTH) ** 2


def _cantilever_column(axial_load: float) -> StructuralModel:
    """Fixed at the base, free tip carrying a small lateral load plus a
    compressive axial load - the classic beam-column P-Delta problem."""
    return StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 0.0, _LENGTH)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties={"E": _E, "A": _A, "I": _I})},
        boundaries=[BoundaryCondition(1, (True, True, True))],
        nodal_loads=[NodalLoad(2, (_LATERAL_LOAD, -axial_load, 0.0))],
    )


def _exact_beam_column_deflection(axial_load: float) -> float:
    if axial_load <= 0.0:
        return _LATERAL_LOAD * _LENGTH**3 / (3 * _E * _I)
    k = math.sqrt(axial_load / (_E * _I))
    return (_LATERAL_LOAD / axial_load) * (math.tan(k * _LENGTH) / k - _LENGTH)


def test_pdelta_at_zero_axial_load_matches_the_linear_result_exactly() -> None:
    model = _cantilever_column(0.0)
    solver = MaterialFreeStaticsSolver()

    linear = solver.solve(model, geometric_nonlinearity="Linear")
    pdelta = solver.solve(model, geometric_nonlinearity="PDelta")

    assert linear.status == AnalysisStatus.COMPLETED
    assert pdelta.status == AnalysisStatus.COMPLETED
    assert pdelta.node_results[2].displacement == pytest.approx(
        linear.node_results[2].displacement, abs=1.0e-9
    )


def test_pdelta_deflection_grows_monotonically_toward_the_buckling_load() -> None:
    solver = MaterialFreeStaticsSolver()
    fractions = (0.0, 0.3, 0.6, 0.9)
    deflections = [
        solver.solve(
            _cantilever_column(fraction * _EULER_LOAD), geometric_nonlinearity="PDelta"
        ).node_results[2].displacement[0]
        for fraction in fractions
    ]
    assert deflections == sorted(deflections)
    assert all(later > earlier for earlier, later in zip(deflections, deflections[1:], strict=False))


def test_pdelta_matches_the_exact_beam_column_closed_form_at_low_axial_load() -> None:
    """Within the range where a single element's linearized geometric
    stiffness is a good approximation (see module docstring)."""
    solver = MaterialFreeStaticsSolver()
    for fraction in (0.1, 0.2, 0.3):
        axial_load = fraction * _EULER_LOAD
        result = solver.solve(_cantilever_column(axial_load), geometric_nonlinearity="PDelta")
        assert result.status == AnalysisStatus.COMPLETED
        ux = result.node_results[2].displacement[0]
        exact = _exact_beam_column_deflection(axial_load)
        assert ux == pytest.approx(exact, rel=0.07)


def test_error_grows_as_the_axial_load_approaches_buckling() -> None:
    """Documents (rather than hides) the single-element P-Delta limitation:
    the relative error against the exact closed form must grow as P/Pe grows -
    a real, expected property of this modeling choice, not something a future
    change should "fix" by loosening the assertion instead of subdividing the
    member into more elements."""
    solver = MaterialFreeStaticsSolver()
    errors = []
    for fraction in (0.1, 0.5, 0.9):
        axial_load = fraction * _EULER_LOAD
        result = solver.solve(_cantilever_column(axial_load), geometric_nonlinearity="PDelta")
        ux = result.node_results[2].displacement[0]
        exact = _exact_beam_column_deflection(axial_load)
        errors.append(abs(ux - exact) / exact)
    assert errors == sorted(errors)
    assert errors[-1] > 0.3  # near buckling, the single-element error is large.


def test_pdelta_requires_real_material_even_on_a_determinate_structure() -> None:
    """Unlike the first-order case, a P-Delta amplification is stiffness-
    dependent even on an otherwise-determinate structure - no unit-placeholder
    shortcut exists for it."""
    model = StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 0.0, _LENGTH)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
        boundaries=[BoundaryCondition(1, (True, True, True))],
        nodal_loads=[NodalLoad(2, (_LATERAL_LOAD, 0.0, 0.0))],
    )
    solver = MaterialFreeStaticsSolver()

    determinate_linear = solver.solve(model, geometric_nonlinearity="Linear")
    determinate_pdelta = solver.solve(model, geometric_nonlinearity="PDelta")

    assert determinate_linear.status == AnalysisStatus.COMPLETED
    assert determinate_pdelta.status == AnalysisStatus.FAILED
    assert "재료" in determinate_pdelta.messages[-1]


def test_rejects_an_unknown_geometric_nonlinearity_setting() -> None:
    model = _cantilever_column(0.0)
    result = MaterialFreeStaticsSolver().solve(model, geometric_nonlinearity="Corotational")
    assert result.status == AnalysisStatus.FAILED
