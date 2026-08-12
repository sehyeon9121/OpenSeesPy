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


def test_a_3d_gerber_beam_with_a_shared_hinge_matches_hand_calculation() -> None:
    """The classic fixed-hinge-roller Gerber beam, generalised to 3D: a straight
    beam along X, fixed at one end, an internal hinge (element 1's j-end AND
    element 2's i-end both released - a true shared hinge, not just one side),
    then continuous through a point load to a roller at the far end.

    Segment 2 (hinge to roller, length Lb=10) behaves as its own simply-supported
    span for the point load at its midpoint: each of its own two "supports" (the
    hinge and the roller) carries P/2, and its midspan moment is P*Lb/4 - textbook
    formulas, independent of this codebase. That P/2 becomes a tip point load on
    segment 1 (fixed cantilever of length L=10), giving base reactions R=P/2 and
    M=P/2*L - so node1 and node4 (the far roller) split the total load P equally,
    node1 additionally carries the fixed-end moment, and the hinge itself must
    show zero moment from both connecting elements.
    """
    load = 100.0
    length = 10.0
    model = StructuralModel(
        ndm=3,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, length, 0.0, 0.0),
            3: Node(3, 1.5 * length, 0.0, 0.0),
            4: Node(4, 2.0 * length, 0.0, 0.0),
        },
        elements={
            1: Element(1, 1, 2, "frame", moment_release_j=True),
            2: Element(2, 2, 3, "frame", moment_release_i=True),
            3: Element(3, 3, 4, "frame"),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            # A 3D roller generalising the 2D "restrain only the load direction"
            # roller needs BOTH out-of-plane translations (Uy and Uz) restrained,
            # not just Uz - otherwise segment 2 (both bending directions released
            # at its hinge end) is free to swing laterally about the hinge, a
            # genuine mechanism with no load needed to reveal it.
            BoundaryCondition(4, (False, True, True, False, False, False)),
        ],
        nodal_loads=[NodalLoad(3, (0.0, 0.0, -load, 0.0, 0.0, 0.0))],
    )

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    base_reaction = result.node_results[1].reaction
    roller_reaction = result.node_results[4].reaction
    # abs=1e-3-scale tolerance, not exact equality: the hinge is a very stiff
    # (1e8) but not literally infinite penalty spring, the same tolerance already
    # used elsewhere in this file for the inclined-support penalty technique.
    assert base_reaction[2] == pytest.approx(load / 2, abs=1.0e-2)
    assert abs(base_reaction[4]) == pytest.approx(load / 2 * length, abs=1.0e-1)
    assert roller_reaction[2] == pytest.approx(load / 2, abs=1.0e-2)
    assert roller_reaction[4] == pytest.approx(0.0, abs=1.0e-6)

    # The hinge must show zero moment from BOTH connecting elements independently
    # (element 1's j-end and element 2's i-end each connect to their own dummy
    # node - neither transmits bending through the released zeroLength).
    element_1_forces = result.element_results[1].local_forces
    element_2_forces = result.element_results[2].local_forces
    assert element_1_forces[10] == pytest.approx(0.0, abs=1.0e-6)  # My at j-end
    assert element_2_forces[4] == pytest.approx(0.0, abs=1.0e-6)  # My at i-end
    # Element 2's OWN midspan moment (its j-end, continuous into element 3):
    # a simply-supported span of length Lb=length with a midpoint point load.
    assert abs(element_2_forces[10]) == pytest.approx(load * length / 4, abs=1.0e-1)


def test_3d_release_shared_by_every_element_at_a_node_counts_as_k_minus_1() -> None:
    """Two elements BOTH released at their shared node (a true hinge, as in the
    Gerber beam above) contribute only one condition equation, not two - the
    members share one collective relative-rotation freedom. released_dof_per_end
    is 2 in 3D (My and Mz both go together), so the net effect is -2 to degree,
    not -4."""
    model = StructuralModel(
        ndm=3,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 5.0, 0.0, 0.0),
            3: Node(3, 10.0, 0.0, 0.0),
        },
        elements={
            1: Element(1, 1, 2, "frame", moment_release_j=True),
            2: Element(2, 2, 3, "frame", moment_release_i=True),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(3, (False, True, True, False, False, False)),
        ],
    )
    assert check_determinacy(model).degree == 0


def test_3d_release_at_a_node_that_also_has_a_rigid_connection_counts_in_full() -> None:
    """A pinned diagonal brace framing into an otherwise-rigid beam-column joint:
    only the brace releases there, so its one condition equation counts in full
    (the rigid beam-column connection anchors a well-defined node rotation for
    the brace to be independently free relative to) - unlike the shared-hinge
    case above, this does NOT get the k-1 discount."""
    model = StructuralModel(
        ndm=3,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 0.0, 0.0, 3.0),
            3: Node(3, 4.0, 0.0, 3.0),
        },
        elements={
            1: Element(1, 1, 2, "frame"),
            2: Element(2, 2, 3, "frame", moment_release_i=True),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(3, (True,) * 6),
        ],
    )
    # 6*2 + 12 - 6*3 - (1 condition * 2 dof) = 12+12-18-2 = 4, not 6 (which is
    # what the naive "always subtract k, never k-1" count would have given if
    # this were mistaken for a shared hinge instead of a lone brace release).
    assert check_determinacy(model).degree == 4


def test_3d_lone_release_at_an_otherwise_untouched_node_adds_no_condition_equations() -> None:
    """A release at a node nothing else connects to (e.g. redundant with an
    already-pinned support, which has no moment reaction to begin with) must not
    double-subtract: the support's own reduced reaction count already reflects
    "no moment here", so the release itself contributes k-1 = 0."""
    with_release = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame", moment_release_i=True)},
        boundaries=[
            # A pin: translations only, matching the release's own implication.
            BoundaryCondition(1, (True, True, True, False, False, False)),
            BoundaryCondition(2, (True, True, True, False, False, False)),
        ],
    )
    without_release = StructuralModel(
        ndm=3,
        nodes=dict(with_release.nodes),
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=list(with_release.boundaries),
    )
    assert check_determinacy(with_release).degree == check_determinacy(without_release).degree
