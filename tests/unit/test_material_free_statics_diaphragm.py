"""Rigid floor diaphragm (Story Manager) - solver.py's ``ops.rigidDiaphragm``
wiring, and the ``constraints("Transformation")`` switch it needs (``Plain``
cannot express a multi-point constraint at all and silently drops it - see
``_analyze``'s own comment).

Closed form: two independent cantilever columns of different stiffness,
tied together only at their tops by a rigid diaphragm, loaded by a single
horizontal force at ONE top node - a textbook parallel-spring problem.
Both tops must end up at the same displacement, and the load splits between
the columns in exact proportion to their lateral stiffness k = 3EI/H**3.
"""

import pytest

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    RigidDiaphragm,
    StructuralModel,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver


def _two_column_model(*, with_diaphragm: bool) -> tuple[StructuralModel, float, float, float]:
    height = 3.0
    elastic = 200000.0
    inertia_a = 0.0004
    inertia_b = 0.0009
    load = 1000.0
    properties = lambda inertia: {
        "E": elastic, "A": 0.02, "G": 80000.0, "J": 0.0005, "Iy": inertia, "Iz": inertia,
    }
    model = StructuralModel(
        ndm=3,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, height),
            3: Node(3, 5.0, 0.0, 0.0), 4: Node(4, 5.0, 0.0, height),
        },
        elements={
            1: Element(1, 1, 2, "frame", properties=properties(inertia_a)),
            2: Element(2, 3, 4, "frame", properties=properties(inertia_b)),
        },
        boundaries=[BoundaryCondition(1, (True,) * 6), BoundaryCondition(3, (True,) * 6)],
        nodal_loads=[NodalLoad(2, (load, 0.0, 0.0, 0.0, 0.0, 0.0))],
        rigid_diaphragms=(
            (RigidDiaphragm(perp_dirn=3, master_tag=2, slave_tags=(4,)),) if with_diaphragm else ()
        ),
    )
    stiffness_a = 3 * elastic * inertia_a / height**3
    stiffness_b = 3 * elastic * inertia_b / height**3
    return model, load, stiffness_a, stiffness_b


def test_rigid_diaphragm_splits_load_between_columns_by_relative_stiffness() -> None:
    model, load, stiffness_a, stiffness_b = _two_column_model(with_diaphragm=True)

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    expected_delta = load / (stiffness_a + stiffness_b)
    assert result.node_results[2].displacement[0] == pytest.approx(expected_delta, rel=1.0e-6)
    # Both diaphragm nodes move together - the entire point of the feature.
    assert result.node_results[4].displacement[0] == pytest.approx(expected_delta, rel=1.0e-6)
    assert result.node_results[1].reaction[0] == pytest.approx(
        -stiffness_a * expected_delta, rel=1.0e-6
    )
    assert result.node_results[3].reaction[0] == pytest.approx(
        -stiffness_b * expected_delta, rel=1.0e-6
    )


def test_without_a_diaphragm_the_two_columns_are_fully_independent() -> None:
    """Same geometry, no rigid_diaphragms entry - column B must see nothing
    at all, proving the diaphragm (not some other coupling) caused the
    load-sharing above."""
    model, load, stiffness_a, _stiffness_b = _two_column_model(with_diaphragm=False)

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[2].displacement[0] == pytest.approx(load / stiffness_a, rel=1.0e-6)
    assert result.node_results[4].displacement[0] == pytest.approx(0.0, abs=1.0e-9)
    assert result.node_results[3].reaction[0] == pytest.approx(0.0, abs=1.0e-9)
