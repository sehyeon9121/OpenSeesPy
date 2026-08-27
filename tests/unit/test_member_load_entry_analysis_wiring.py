"""Closed-form validation that Point/Partial/Moment/Self Weight/Floor
LoadEntry kinds actually reach the solver now - see the Loads-tab session
notes (openframe-loads-midas-style-form-pilot / this session's follow-up)
for why these previously never left ``canvas.load_entries``.

Two layers are tested separately:
- ``MaterialFreeStaticsSolver`` directly against a hand-built
  ``StructuralModel`` (``point_loads``, and ``UniformElementLoad``'s new
  ``xL1``/``xL2``) - validates solver.py's new eleLoad wiring against
  textbook cantilever formulas, independent of the canvas/LoadEntry layer.
- ``StaticsDrawingCanvas.build_model()`` from LoadEntry objects (the actual
  Direct Loads Apply path, ``_commit_load3d_entry``) through to solve -
  validates canvas_model_build.py's LoadEntry -> StructuralModel conversion.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    FloorLoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    Node,
    PointElementLoad,
    SelfWeightEntry,
    StructuralModel,
    UniformElementLoad,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas

E = 200_000_000.0  # kN/m^2
I = 0.0001  # m^4
A = 0.01  # m^2
L = 6.0


def _cantilever_canvas() -> tuple:
    from dataclasses import replace

    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    a = canvas.add_node(0.0, 0.0)
    b = canvas.add_node(L, 0.0)
    member = canvas.add_member(a, b)
    props = dict(canvas.elements[member].properties)
    props.update({"E": E, "A": A, "I": I, "density": 78.5})
    canvas.elements[member] = replace(canvas.elements[member], properties=props)
    canvas.boundaries[a] = BoundaryCondition(a, (True, True, True))
    case_id = canvas.add_load_case("DL")
    return canvas, a, b, member, case_id


def test_solver_applies_a_native_point_load_at_an_arbitrary_position() -> None:
    """Cantilever, point load P at the free end: tip deflection = P L^3 / (3EI)."""
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, L, 0.0)},
        elements={1: Element(1, 1, 2, "frame", {"E": E, "A": A, "I": I})},
        boundaries=[BoundaryCondition(1, (True, True, True))],
        point_loads=[PointElementLoad(1, position=1.0, py=-10.0)],
    )

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    expected = -10.0 * L**3 / (3 * E * I)
    assert result.node_results[2].displacement[1] == pytest.approx(expected)


def test_solver_applies_a_native_partial_span_uniform_load() -> None:
    """Cantilever with a constant w confined to xL1..xL2 - verified against
    OpenSeesPy's own native -beamUniform xL1/xL2 by reaction (total force =
    w * loaded length, moment = that force times its centroid's distance
    from the fixed end)."""
    xL1, xL2 = 0.3, 0.7
    w = -5.0
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 10.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame", {"E": E, "A": A, "I": I})},
        boundaries=[BoundaryCondition(1, (True, True, True))],
        element_loads=[UniformElementLoad(1, wy=w, xL1=xL1, xL2=xL2)],
    )

    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    loaded_length = 10.0 * (xL2 - xL1)
    total_force = w * loaded_length
    centroid = 10.0 * (xL1 + xL2) / 2.0
    assert result.node_results[1].reaction[1] == pytest.approx(-total_force)
    assert result.node_results[1].reaction[2] == pytest.approx(-total_force * centroid)


def test_build_model_applies_a_member_point_load_from_an_active_case_entry() -> None:
    canvas, a, b, member, case_id = _cantilever_canvas()
    P = -10.0
    canvas.add_load_entry(
        case_id, "member_point", (member,), MemberPointLoadEntry(direction="y", value=P, position=1.0)
    )

    result = MaterialFreeStaticsSolver().solve(canvas.build_model())

    expected = P * L**3 / (3 * E * I)
    assert result.node_results[b].displacement[1] == pytest.approx(expected)


def test_build_model_applies_a_member_moment_by_splitting_the_member() -> None:
    canvas, a, b, member, case_id = _cantilever_canvas()
    M = 20.0
    canvas.add_load_entry(
        case_id, "member_moment", (member,), MemberPointLoadEntry(direction="z", value=M, position=1.0)
    )

    model = canvas.build_model()
    result = MaterialFreeStaticsSolver().solve(model)

    expected = abs(M) * L**2 / (2 * E * I)
    assert abs(result.node_results[b].displacement[1]) == pytest.approx(expected)


def test_build_model_applies_a_constant_member_partial_load() -> None:
    canvas, a, b, member, case_id = _cantilever_canvas()
    w = -3.0
    canvas.add_load_entry(
        case_id,
        "member_partial",
        (member,),
        MemberDistributedLoadEntry(direction="y", start_value=w, end_value=w, start_position=0.0, end_position=1.0),
    )

    result = MaterialFreeStaticsSolver().solve(canvas.build_model())

    expected = w * L**4 / (8 * E * I)
    assert result.node_results[b].displacement[1] == pytest.approx(expected)


def test_build_model_applies_a_linearly_varying_partial_load_is_skipped() -> None:
    """start_value != end_value inside a partial span is explicitly deferred
    (see plan) - it must be silently skipped, not crash or apply the wrong
    load."""
    canvas, a, b, member, case_id = _cantilever_canvas()
    canvas.add_load_entry(
        case_id,
        "member_partial",
        (member,),
        MemberDistributedLoadEntry(
            direction="y", start_value=-1.0, end_value=-2.0, start_position=0.25, end_position=0.75
        ),
    )

    model = canvas.build_model()

    assert model.element_loads == []


def test_build_model_applies_a_case_self_weight_factor() -> None:
    canvas, a, b, member, case_id = _cantilever_canvas()
    canvas.add_load_entry(case_id, "self_weight", (), SelfWeightEntry(factor_y=-1.0, apply_to_all=True))

    model = canvas.build_model()

    density = 78.5
    expected_wy = -density * A
    assert len(model.element_loads) == 1
    assert model.element_loads[0].wy == pytest.approx(expected_wy)


def test_build_model_only_reads_the_active_case_not_every_case() -> None:
    canvas, a, b, member, case_id = _cantilever_canvas()
    other_case = canvas.add_load_case("LL")
    canvas.add_load_entry(
        other_case, "member_point", (member,), MemberPointLoadEntry(direction="y", value=-99.0, position=0.5)
    )
    canvas.active_load_case_id = case_id  # DL, not LL

    model = canvas.build_model()

    assert model.point_loads == []


def test_build_model_skips_a_hidden_entry() -> None:
    canvas, a, b, member, case_id = _cantilever_canvas()
    entry_id = canvas.add_load_entry(
        case_id, "member_point", (member,), MemberPointLoadEntry(direction="y", value=-10.0, position=0.5)
    )
    canvas.set_load_entry_hidden(entry_id, True)

    model = canvas.build_model()

    assert model.point_loads == []


def test_build_model_does_not_double_count_a_combination_activated_floor_case() -> None:
    """A floor entry reaches analysis exactly once now that build_model()
    reads it live off the active case - the old combination-bridge no
    longer also bakes it into a legacy element_loads snapshot (see
    canvas_load_entries.py's _activate_generated_case_for_analysis, floor
    branch removed)."""
    canvas, a, b, member, case_id = _cantilever_canvas()
    c = canvas.add_node(L, 4.0)
    other = canvas.add_member(b, c)
    props = dict(canvas.elements[other].properties)
    props.update({"E": E, "A": A, "I": I})
    from dataclasses import replace

    canvas.elements[other] = replace(canvas.elements[other], properties=props)
    canvas.add_floor_load_type("Slab", rows=())
    canvas.add_load_entry(
        case_id,
        "floor",
        (a, b, c),
        FloorLoadEntry(magnitude=2.0, direction="-z", target_nodes=(a, b, c)),
    )

    model = canvas.build_model()
    floor_loads = [load for load in model.element_loads if load.case_type.value == "OTHER"]
    # Exactly one contribution per boundary element touched by the floor -
    # not two (which double-counting via the old bridge would produce).
    contributing_tags = [load.element_tag for load in floor_loads if load.wz != 0.0 or load.wy != 0.0]
    assert len(contributing_tags) == len(set(contributing_tags))
