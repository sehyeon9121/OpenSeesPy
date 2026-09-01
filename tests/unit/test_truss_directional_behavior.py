"""tension_only/compression_only/cable: properties["behavior"] now reaches the
solver (see solver.py's _element_behavior/_define_truss_material) instead of
being silently ignored and built as an ordinary bidirectional Elastic truss.

Every case here is a single vertical member between a fully-fixed top node and
a bottom node restrained only horizontally (a roller) - so the member is the
*only* thing resisting vertical load, and its sign tells the whole story:
loading it in its allowed direction must match an ordinary elastic truss's
closed-form force/elongation exactly (P*L/(EA)); loading it the other way must
leave the bottom node with no vertical resistance at all - a mechanism, which
OpenSees can only fail to converge on, not silently mis-solve.
"""

import math

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

_E = 2.0e8
_A = 0.001
_L = 4.0


def _hanging_member(behavior: str) -> StructuralModel:
    """node1 (top, fully fixed) --- node2 (bottom, horizontal roller only)."""
    return StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, _L), 2: Node(2, 0.0, 0.0)},
        elements={
            1: Element(
                1, 1, 2, "truss",
                properties={"E": _E, "A": _A, "behavior": behavior},
            ),
        },
        boundaries=[
            BoundaryCondition(1, (True, True)),
            BoundaryCondition(2, (True, False)),
        ],
        nodal_loads=[NodalLoad(2, (0.0, 0.0))],
    )


@pytest.mark.parametrize(
    ("behavior", "load_y"),
    [
        ("tension_only", -10.0),  # pulls node2 down -> member stretches, tension
        ("compression_only", 10.0),  # pushes node2 up -> member shortens, compression
        ("cable", -10.0),
    ],
)
def test_directional_truss_in_its_allowed_direction_matches_closed_form(
    behavior: str, load_y: float
) -> None:
    model = _hanging_member(behavior)
    model.nodal_loads[0] = NodalLoad(2, (0.0, load_y))

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    expected_axial = abs(load_y)  # vertical equilibrium at node2: only member resists
    axial = result.element_results[1].local_forces[3]
    assert axial == pytest.approx(expected_axial if load_y < 0 else -expected_axial, rel=1e-6)
    expected_elongation = load_y * _L / (_E * _A)
    displacement_y = result.node_results[2].displacement[1]
    assert displacement_y == pytest.approx(expected_elongation, rel=1e-6, abs=1e-12)


@pytest.mark.parametrize(
    ("behavior", "load_y"),
    [
        ("tension_only", 10.0),  # would need to push node2 up -> compression, not allowed
        ("compression_only", -10.0),  # would need to pull node2 down -> tension, not allowed
        ("cable", 10.0),
    ],
)
def test_directional_truss_in_its_disallowed_direction_is_an_unstable_mechanism(
    behavior: str, load_y: float
) -> None:
    model = _hanging_member(behavior)
    model.nodal_loads[0] = NodalLoad(2, (0.0, load_y))

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.FAILED


def test_plain_truss_behaviour_is_unaffected_and_still_uses_elastic() -> None:
    """No "behavior" key at all (older saved models / templates / imports) or
    an explicit "truss" must still build the ordinary bidirectional Elastic
    truss - same closed-form answer regardless of load direction."""
    for behavior in (None, "truss"):
        properties = {"E": _E, "A": _A}
        if behavior is not None:
            properties["behavior"] = behavior
        model = StructuralModel(
            ndm=2,
            nodes={1: Node(1, 0.0, _L), 2: Node(2, 0.0, 0.0)},
            elements={1: Element(1, 1, 2, "truss", properties=properties)},
            boundaries=[
                BoundaryCondition(1, (True, True)),
                BoundaryCondition(2, (True, False)),
            ],
            nodal_loads=[NodalLoad(2, (0.0, 10.0))],
        )

        result = MaterialFreeStaticsSolver().solve(model)

        assert result.status == AnalysisStatus.COMPLETED
        axial = result.element_results[1].local_forces[3]
        assert axial == pytest.approx(-10.0, rel=1e-6)


def test_determinate_directional_truss_without_real_ea_is_rejected_not_unit_stiffness() -> None:
    """A determinate pure truss with ordinary "truss" behaviour and no E/A
    falls back to unit-stiffness equilibrium-only forces (see
    test_truss_stiffness_policy.py). A directional member must not take that
    shortcut - whether the structure is even stable depends on which way the
    member ends up loaded, which equilibrium alone cannot answer."""
    model = _hanging_member("tension_only")
    model.elements[1] = Element(1, 1, 2, "truss", properties={"behavior": "tension_only"})
    model.nodal_loads[0] = NodalLoad(2, (0.0, -10.0))

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.FAILED
    joined = " ".join(result.messages)
    assert "인장전담" in joined


def test_cable_element_command_is_plain_truss_without_prestress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cable stays the ordinary linear truss here (not corotTruss) as long as
    solver.py has no prestress wiring - see _truss_element_command's own
    docstring for the unphysical "flip-through" equilibrium corotTruss alone
    would otherwise admit."""
    from openframe.features.analysis.statics import solver as solver_module

    calls: list[tuple] = []
    real_element = solver_module.ops.element

    def spy(*args: object) -> None:
        calls.append(args)
        return real_element(*args)

    monkeypatch.setattr(solver_module.ops, "element", spy)

    model = _hanging_member("cable")
    model.nodal_loads[0] = NodalLoad(2, (0.0, -10.0))
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    element_calls = [call for call in calls if call and call[1] == 1]
    assert element_calls, "expected element 1 to be built"
    assert element_calls[0][0] == "truss"
