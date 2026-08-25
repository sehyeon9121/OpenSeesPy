"""Elastic (finite-stiffness) support - solver.py's ``_apply_springs``.

Closed-form check: a truss member provides zero transverse stiffness at its
own free end (a two-force member can't resist a transverse point load at all
without something else bracing it), so a transverse spring at that node is
the *only* thing resisting a transverse load there - displacement must equal
exactly load/stiffness (Hooke's law), independent of the member's own axial
EA.
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
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy


def test_transverse_spring_at_a_truss_node_obeys_hookes_law() -> None:
    stiffness = 500.0
    load = 12.0
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 5.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "truss")},
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(2, (True, False, True), spring_stiffnesses=(None, stiffness, None)),
        ],
        nodal_loads=[NodalLoad(2, (0.0, load, 0.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[2].displacement[1] == pytest.approx(load / stiffness, rel=1.0e-9)


def test_a_rigidly_fixed_dof_ignores_any_spring_stiffness_set_on_it() -> None:
    """A DOF can be fixed OR sprung, never both - restraints wins. X is both
    rigidly fixed and (should-be-ignored) given a stiffness; Y is genuinely
    sprung in the same boundary condition, so one model exercises both."""
    stiffness_y = 500.0
    load_y = 100.0
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 5.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "truss")},
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(2, (True, False, True), spring_stiffnesses=(1.0, stiffness_y, None)),
        ],
        nodal_loads=[NodalLoad(2, (500.0, load_y, 0.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[2].displacement[0] == pytest.approx(0.0, abs=1.0e-9)
    assert result.node_results[2].displacement[1] == pytest.approx(load_y / stiffness_y, rel=1.0e-9)
