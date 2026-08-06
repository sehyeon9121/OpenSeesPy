"""3D determinate statics: hand-verified against textbook equilibrium, the same
way the 2D solver's tests are — a determinate structure's reactions and member
forces come from equilibrium alone, independent of the placeholder stiffness
this solver hands OpenSees.
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
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy


def test_a_3d_space_truss_tripod_is_determinate() -> None:
    """Apex free, three base joints each fully pinned (3 dof): m + r - 3j.

    m=3, r=9 (3 bases x 3), j=4 -> 3+9-12=0. The base reactions have no closed
    form worth hand-deriving here, but the sum of the three vertical reactions
    must equal the applied load, and the horizontal components must cancel —
    an equilibrium check independent of how OpenSees actually solved it.
    """
    model = StructuralModel(
        ndm=3,
        nodes={
            1: Node(1, 0.0, 0.0, 3.0),
            2: Node(2, -2.0, -2.0, 0.0),
            3: Node(3, 2.0, -2.0, 0.0),
            4: Node(4, 0.0, 2.0, 0.0),
        },
        elements={
            1: Element(1, 1, 2, "truss"),
            2: Element(2, 1, 3, "truss"),
            3: Element(3, 1, 4, "truss"),
        },
        boundaries=[
            BoundaryCondition(2, (True, True, True)),
            BoundaryCondition(3, (True, True, True)),
            BoundaryCondition(4, (True, True, True)),
        ],
        nodal_loads=[NodalLoad(1, (0.0, 0.0, -9.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    total = [0.0, 0.0, 0.0]
    for tag in (2, 3, 4):
        reaction = result.node_results[tag].reaction
        for axis in range(3):
            total[axis] += reaction[axis]
    assert total == pytest.approx((0.0, 0.0, 9.0), abs=1.0e-6)


def test_a_vertical_cantilever_column_matches_the_hand_calculated_base_moment() -> None:
    """Fixed-base column along Z, a horizontal tip load — the textbook cantilever,
    just standing up: R = -P, base moment = P * L, no other reaction component."""
    load = 10.0
    length = 4.0
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, length)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(2, (load, 0.0, 0.0, 0.0, 0.0, 0.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    reaction = result.node_results[1].reaction
    assert reaction[0] == pytest.approx(-load, abs=1.0e-6)
    assert reaction[1] == pytest.approx(0.0, abs=1.0e-6)
    assert reaction[2] == pytest.approx(0.0, abs=1.0e-6)
    assert abs(reaction[4]) == pytest.approx(load * length, abs=1.0e-6)
    assert reaction[3] == pytest.approx(0.0, abs=1.0e-6)
    assert reaction[5] == pytest.approx(0.0, abs=1.0e-6)


def test_a_horizontal_beam_along_x_also_matches_its_hand_calculated_reactions() -> None:
    """Fixed-base beam along global X, a vertical tip load: the same physics as
    the vertical-column case, checked with a member axis that is not parallel
    to the automatic reference vector this solver falls back to for verticals."""
    load = 10.0
    length = 4.0
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, length, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        nodal_loads=[NodalLoad(2, (0.0, 0.0, -load, 0.0, 0.0, 0.0))],
    )

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    reaction = result.node_results[1].reaction
    assert reaction[2] == pytest.approx(load, abs=1.0e-6)
    assert math.hypot(reaction[3], reaction[4]) == pytest.approx(load * length, abs=1.0e-6)


def test_3d_element_uniform_loads_are_rejected_with_a_clear_message() -> None:
    """The transverse-load direction depends on an axis this solver only ever
    picks automatically; a student-entered wx/wy could silently mean the wrong
    physical direction, so this refuses rather than risk a wrong answer."""
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )
    from openframe.core.domain import UniformElementLoad

    model.element_loads = [UniformElementLoad(1, wy=-10.0)]

    assert check_determinacy(model).degree == 0

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.FAILED
    assert "부재 분포하중" in result.messages[0]


def test_3d_frame_determinacy_matches_the_6m_plus_r_minus_6j_formula() -> None:
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, 3.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )
    assert check_determinacy(model).degree == 0

    model.boundaries.append(BoundaryCondition(2, (True, False, False, False, False, False)))
    assert check_determinacy(model).degree == 1
