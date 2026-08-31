"""Phase S-1: real truss EA, indeterminate pure trusses, unit-stiffness metadata."""

import math

import pytest

from openframe.core.domain import (
    UNIT_STIFFNESS_DISPLACEMENT_WARNING,
    AnalysisStatus,
    BoundaryCondition,
    DisplacementStiffnessKind,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy


def _determinate_a_frame(*, elastic: float | None, area: float | None) -> StructuralModel:
    """Two-bar A-frame: m+r-2j = 2+4-6 = 0.

    Hand-checked reactions for the -12 vertical load at the apex are
    (4, 6) and (-4, 6) regardless of EA - see
    test_a_determinate_2d_truss_matches_hand_calculated_reactions.
    """
    properties: dict[str, float] = {}
    if elastic is not None:
        properties["E"] = elastic
    if area is not None:
        properties["A"] = area
    return StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0), 3: Node(3, 2.0, 3.0)},
        elements={
            1: Element(1, 1, 3, "truss", properties=dict(properties)),
            2: Element(2, 2, 3, "truss", properties=dict(properties)),
        },
        boundaries=[
            BoundaryCondition(1, (True, True)),
            BoundaryCondition(2, (True, True)),
        ],
        nodal_loads=[NodalLoad(3, (0.0, -12.0))],
    )


def _tripod(*, elastic: float | None, area: float | None) -> StructuralModel:
    properties: dict[str, float] = {}
    if elastic is not None:
        properties["E"] = elastic
    if area is not None:
        properties["A"] = area
    return StructuralModel(
        ndm=3,
        nodes={
            1: Node(1, 0.0, 0.0, 3.0),
            2: Node(2, -2.0, -2.0, 0.0),
            3: Node(3, 2.0, -2.0, 0.0),
            4: Node(4, 0.0, 2.0, 0.0),
        },
        elements={
            1: Element(1, 1, 2, "truss", properties=dict(properties)),
            2: Element(2, 1, 3, "truss", properties=dict(properties)),
            3: Element(3, 1, 4, "truss", properties=dict(properties)),
        },
        boundaries=[
            BoundaryCondition(2, (True, True, True)),
            BoundaryCondition(3, (True, True, True)),
            BoundaryCondition(4, (True, True, True)),
        ],
        nodal_loads=[NodalLoad(1, (0.0, 0.0, -9.0))],
    )


def _three_bar_truss(
    *, mid_elastic: float, mid_area: float, side_elastic: float, side_area: float
) -> StructuralModel:
    """Symmetric 3-bar truss: pinned bases at (-1,0)/(0,0)/(1,0), apex (0,1).

    m=3, r=6, j=4 → degree 1. The mid bar is vertical; the two sides share
    length √2. Closed-form vertical stiffness at the apex is
    EA_mid/L_mid + 2 (EA_side/L_side) sin²θ with sinθ = 1/√2.
    """
    return StructuralModel(
        ndm=2,
        nodes={
            1: Node(1, -1.0, 0.0),
            2: Node(2, 0.0, 0.0),
            3: Node(3, 1.0, 0.0),
            4: Node(4, 0.0, 1.0),
        },
        elements={
            1: Element(1, 1, 4, "truss", properties={"E": side_elastic, "A": side_area}),
            2: Element(2, 2, 4, "truss", properties={"E": mid_elastic, "A": mid_area}),
            3: Element(3, 3, 4, "truss", properties={"E": side_elastic, "A": side_area}),
        },
        boundaries=[
            BoundaryCondition(1, (True, True)),
            BoundaryCondition(2, (True, True)),
            BoundaryCondition(3, (True, True)),
        ],
        nodal_loads=[NodalLoad(4, (0.0, -10.0))],
    )


def test_determinate_2d_truss_scales_displacement_with_ea_and_keeps_forces() -> None:
    base = MaterialFreeStaticsSolver().solve(_determinate_a_frame(elastic=200_000.0, area=0.01))
    stiff = MaterialFreeStaticsSolver().solve(_determinate_a_frame(elastic=400_000.0, area=0.01))

    assert base.status == AnalysisStatus.COMPLETED
    assert stiff.status == AnalysisStatus.COMPLETED
    assert base.displacement_stiffness is DisplacementStiffnessKind.PHYSICAL
    assert UNIT_STIFFNESS_DISPLACEMENT_WARNING not in base.messages

    for tag in (1, 2):
        assert base.node_results[tag].reaction == pytest.approx(
            stiff.node_results[tag].reaction, rel=1e-8
        )
        assert base.element_results[tag].local_forces == pytest.approx(
            stiff.element_results[tag].local_forces, rel=1e-8
        )
    assert stiff.node_results[3].displacement == pytest.approx(
        tuple(value / 2.0 for value in base.node_results[3].displacement), rel=1e-6
    )
    assert base.node_results[1].reaction == pytest.approx((4.0, 6.0), abs=1e-6)
    assert base.node_results[2].reaction == pytest.approx((-4.0, 6.0), abs=1e-6)


def test_determinate_3d_truss_scales_displacement_with_ea_and_keeps_forces() -> None:
    base = MaterialFreeStaticsSolver().solve(_tripod(elastic=200_000.0, area=0.01))
    stiff = MaterialFreeStaticsSolver().solve(_tripod(elastic=200_000.0, area=0.02))

    assert base.status == AnalysisStatus.COMPLETED
    assert stiff.status == AnalysisStatus.COMPLETED
    assert base.displacement_stiffness is DisplacementStiffnessKind.PHYSICAL

    for tag in (2, 3, 4):
        assert base.node_results[tag].reaction == pytest.approx(
            stiff.node_results[tag].reaction, rel=1e-8
        )
    for tag in (1, 2, 3):
        assert base.element_results[tag].local_forces == pytest.approx(
            stiff.element_results[tag].local_forces, rel=1e-8
        )
    assert stiff.node_results[1].displacement == pytest.approx(
        tuple(value / 2.0 for value in base.node_results[1].displacement), rel=1e-6
    )


def test_indeterminate_three_bar_truss_matches_closed_form_stiffness() -> None:
    elastic, area, load = 1000.0, 1.0, 10.0
    model = _three_bar_truss(
        mid_elastic=elastic, mid_area=area, side_elastic=elastic, side_area=area
    )
    result = MaterialFreeStaticsSolver().solve(model)

    assert check_determinacy(model).degree == 1
    assert result.status == AnalysisStatus.COMPLETED
    assert result.displacement_stiffness is DisplacementStiffnessKind.PHYSICAL

    # K_yy = EA + 2 (EA/√2)(1/2) = EA (1 + 1/√2)
    stiffness = elastic * area * (1.0 + 1.0 / math.sqrt(2.0))
    expected_uy = -load / stiffness
    expected_n_mid = elastic * area * expected_uy
    expected_n_side = elastic * area * expected_uy / 2.0

    assert result.node_results[4].displacement[1] == pytest.approx(expected_uy, rel=1e-6)
    # Solver stores truss local force as (-N_ops, ..., +N_ops); N_ops matches
    # OpenSees axialForce (tension positive here because Uy is negative → compression).
    assert result.element_results[2].local_forces[3] == pytest.approx(expected_n_mid, rel=1e-6)
    assert result.element_results[1].local_forces[3] == pytest.approx(expected_n_side, rel=1e-6)
    assert result.element_results[3].local_forces[3] == pytest.approx(expected_n_side, rel=1e-6)
    assert result.node_results[2].reaction[1] == pytest.approx(-expected_n_mid, rel=1e-6)


def test_indeterminate_truss_with_real_ea_doubles_stiffness_like_the_determinate_case() -> None:
    base = MaterialFreeStaticsSolver().solve(
        _three_bar_truss(mid_elastic=1000.0, mid_area=1.0, side_elastic=1000.0, side_area=1.0)
    )
    stiff = MaterialFreeStaticsSolver().solve(
        _three_bar_truss(mid_elastic=2000.0, mid_area=1.0, side_elastic=2000.0, side_area=1.0)
    )

    assert base.status == AnalysisStatus.COMPLETED
    assert stiff.node_results[4].displacement == pytest.approx(
        tuple(value / 2.0 for value in base.node_results[4].displacement), rel=1e-6
    )
    for tag in (1, 2, 3):
        assert base.element_results[tag].local_forces == pytest.approx(
            stiff.element_results[tag].local_forces, rel=1e-8
        )


def test_per_member_ea_changes_force_share_on_an_indeterminate_truss() -> None:
    equal = MaterialFreeStaticsSolver().solve(
        _three_bar_truss(mid_elastic=1000.0, mid_area=1.0, side_elastic=1000.0, side_area=1.0)
    )
    stiffer_mid = MaterialFreeStaticsSolver().solve(
        _three_bar_truss(mid_elastic=2000.0, mid_area=1.0, side_elastic=1000.0, side_area=1.0)
    )

    assert equal.status == AnalysisStatus.COMPLETED
    assert stiffer_mid.status == AnalysisStatus.COMPLETED
    # A stiffer mid bar takes more of the vertical load than the equal-EA case.
    assert abs(stiffer_mid.element_results[2].local_forces[3]) > abs(
        equal.element_results[2].local_forces[3]
    )
    stiffness = 2000.0 * 1.0 + 2.0 * (1000.0 / math.sqrt(2.0)) * 0.5
    expected_uy = -10.0 / stiffness
    expected_n_mid = 2000.0 * expected_uy
    expected_n_side = 1000.0 * expected_uy / 2.0
    assert stiffer_mid.node_results[4].displacement[1] == pytest.approx(expected_uy, rel=1e-6)
    assert stiffer_mid.element_results[2].local_forces[3] == pytest.approx(expected_n_mid, rel=1e-6)
    assert stiffer_mid.element_results[1].local_forces[3] == pytest.approx(expected_n_side, rel=1e-6)


def test_indeterminate_truss_without_ea_fails_naming_members_and_keys() -> None:
    model = _three_bar_truss(mid_elastic=1000.0, mid_area=1.0, side_elastic=1000.0, side_area=1.0)
    model.elements[2].properties.pop("E")
    model.elements[3].properties["A"] = 0.0

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.FAILED
    joined = "\n".join(result.messages)
    assert "부재 2" in joined and "E 없음" in joined
    assert "부재 3" in joined and "A=" in joined


def test_determinate_truss_without_ea_marks_unit_stiffness_displacements() -> None:
    result = MaterialFreeStaticsSolver().solve(_determinate_a_frame(elastic=None, area=None))

    assert result.status == AnalysisStatus.COMPLETED
    assert result.displacement_stiffness is DisplacementStiffnessKind.UNIT_STIFFNESS
    assert UNIT_STIFFNESS_DISPLACEMENT_WARNING in result.messages
    assert result.node_results[1].reaction == pytest.approx((4.0, 6.0), abs=1e-6)
    assert result.node_results[2].reaction == pytest.approx((-4.0, 6.0), abs=1e-6)


def test_partial_ea_on_a_determinate_truss_does_not_mix_real_and_unit_stiffness() -> None:
    """One member with real EA and one without would otherwise produce a
    displacement field that is physical on some members and fake on others.
    Forces stay equilibrium-correct either way; the whole model is therefore
    built with the unit placeholder and flagged as non-physical.
    """
    model = _determinate_a_frame(elastic=None, area=None)
    model.elements[1].properties["E"] = 200_000.0
    model.elements[1].properties["A"] = 0.01

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.displacement_stiffness is DisplacementStiffnessKind.UNIT_STIFFNESS
    all_unit = MaterialFreeStaticsSolver().solve(_determinate_a_frame(elastic=None, area=None))
    assert result.node_results[3].displacement == pytest.approx(
        all_unit.node_results[3].displacement, rel=1e-6
    )


def test_real_ea_clears_the_unit_stiffness_flag() -> None:
    missing = MaterialFreeStaticsSolver().solve(_determinate_a_frame(elastic=None, area=None))
    assigned = MaterialFreeStaticsSolver().solve(_determinate_a_frame(elastic=200_000.0, area=0.01))

    assert missing.displacement_stiffness is DisplacementStiffnessKind.UNIT_STIFFNESS
    assert assigned.displacement_stiffness is DisplacementStiffnessKind.PHYSICAL
    assert UNIT_STIFFNESS_DISPLACEMENT_WARNING not in assigned.messages


def _mixed_frame_and_two_cables() -> StructuralModel:
    """node1/node2 fixed; a frame member ties them together (both ends
    rigid, no member load - trivially zero force, present only to make this
    a genuine mixed model); node3 hangs off BOTH by cable, braced in two
    non-parallel directions so it is kinematically stable without needing
    node1/node2's own frame connection.

    Load (5, -10) at node3 happens to point exactly along cable(1,3)'s own
    axis (unit vector (-0.4472, 0.8944) from node3 to node1, scaled by
    5*sqrt(5)) - by design, so both the cable tension and the (zero) force
    in cable(2,3) are hand-checkable without solving the stiffness matrix:
    cable(1,3) alone equilibrates the load, cable(2,3) carries nothing.
    """
    E = 2.1e8
    return StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 5.0, 0.0), 3: Node(3, 2.5, -5.0)},
        elements={
            1: Element(1, 1, 2, "frame", properties={"E": E, "A": 0.01, "I": 0.0001}),
            2: Element(2, 1, 3, "truss", properties={"E": E, "A": 0.0001}),
            3: Element(3, 2, 3, "truss", properties={"E": E, "A": 0.0001}),
        },
        boundaries=[
            BoundaryCondition(1, (True, True, True)),
            BoundaryCondition(2, (True, True, True)),
        ],
        nodal_loads=[NodalLoad(3, (5.0, -10.0, 0.0))],
    )


def test_stable_mixed_frame_and_cable_model_solves_with_real_stiffness() -> None:
    """A frame member and truss/cable members sharing nodes now solves (this
    used to be an outright rejection - see the mast+guy-cable use case this
    feature exists for) as long as every element carries real stiffness."""
    model = _mixed_frame_and_two_cables()

    assert check_determinacy(model).system == "mixed"
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED

    # Global equilibrium holds regardless of member stiffness: reactions sum
    # to minus the applied load.
    total_reaction = [
        sum(result.node_results[tag].reaction[axis] for tag in (1, 2)) for axis in (0, 1)
    ]
    assert total_reaction[0] == pytest.approx(-5.0, abs=1e-9)
    assert total_reaction[1] == pytest.approx(10.0, abs=1e-9)

    # Hand-checked: cable(1,3) alone equilibrates the load (T = 5*sqrt(5)),
    # cable(2,3) carries nothing, and the frame member (both ends fixed, no
    # member load) carries nothing either.
    cable_13 = result.element_results[2].local_forces
    cable_23 = result.element_results[3].local_forces
    frame_12 = result.element_results[1].local_forces
    assert cable_13[3] == pytest.approx(5.0 * math.sqrt(5.0), abs=1e-9)
    assert cable_23[3] == pytest.approx(0.0, abs=1e-9)
    assert all(value == pytest.approx(0.0, abs=1e-9) for value in frame_12)

    # The whole point of supporting mixed models: a truss/cable element can
    # never report a nonzero moment, unlike the frame member it shares a
    # node with (see moment slots - index 2/5 in this 2D 6-value shape).
    assert cable_13[2] == pytest.approx(0.0, abs=1e-9)
    assert cable_13[5] == pytest.approx(0.0, abs=1e-9)
    assert cable_23[2] == pytest.approx(0.0, abs=1e-9)
    assert cable_23[5] == pytest.approx(0.0, abs=1e-9)


def test_mixed_model_missing_stiffness_on_any_element_is_rejected() -> None:
    model = _mixed_frame_and_two_cables()
    # Strip the cable's own A - a mixed model gets no unit-stiffness
    # fallback the way a determinate pure truss/frame does (see
    # check_determinacy's "mixed" branch), so this must fail, not silently
    # solve with a placeholder.
    model.elements[2] = Element(2, 1, 3, "truss", properties={"E": 2.1e8})

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.FAILED
    joined = " ".join(result.messages)
    assert "혼합" in joined


def test_kinematically_unstable_mixed_model_fails_as_unstable_not_as_rejected() -> None:
    """A single cable can only resist force along its own axis - bracing a
    free joint with just one (no second, non-parallel cable, and no frame
    member reaching it either) leaves it a mechanism in every other
    direction. This must fail as a genuinely unstable structure now that
    mixed models are actually solved, not with the old blanket "mixed is
    unsupported" message."""
    model = StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0), 3: Node(3, 4.0, 3.0)},
        elements={
            1: Element(1, 1, 2, "frame", properties={"E": 200_000.0, "A": 0.01, "I": 0.0001}),
            2: Element(2, 2, 3, "truss", properties={"E": 200_000.0, "A": 0.01}),
        },
        boundaries=[BoundaryCondition(1, (True, True, True))],
        nodal_loads=[NodalLoad(3, (0.0, -10.0))],
    )

    assert check_determinacy(model).system == "mixed"
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.FAILED
    joined = " ".join(result.messages)
    assert "불안정" in joined
    assert "혼합" not in joined
