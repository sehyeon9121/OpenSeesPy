"""Load Case / Load Entry / Load Combination CRUD (canvas_load_entries.py) -
entirely separate from nodal_loads/element_loads, so also checks that adding
one never touches the other (the whole point of keeping 2D untouched)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import LoadCaseKind, MemberDistributedLoadEntry, NodalLoadEntry
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def test_add_load_case_is_the_active_case_by_default() -> None:
    canvas = _canvas()
    case_id = canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE, description="Office live load")
    assert case_id == "LL_OFFICE"
    assert canvas.load_cases["LL_OFFICE"].kind is LoadCaseKind.LIVE
    assert canvas.active_load_case_id == "LL_OFFICE"


def test_add_load_case_refuses_a_duplicate_name() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL_SELF")
    assert canvas.add_load_case("DL_SELF") is None
    assert len(canvas.load_cases) == 1


def test_two_load_entries_from_different_cases_coexist_on_the_same_node() -> None:
    """The whole point of the new store: nodal_loads/element_loads could
    only ever hold one load per tag - this must not have that limit."""
    canvas = _canvas()
    node = canvas.add_node(0.0, 0.0)
    canvas.add_load_case("DL_SELF", kind=LoadCaseKind.DEAD)
    canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)

    dead_id = canvas.add_load_entry("DL_SELF", "nodal", (node,), NodalLoadEntry(fz=-5.0))
    live_id = canvas.add_load_entry("LL_OFFICE", "nodal", (node,), NodalLoadEntry(fz=-10.0))

    assert dead_id != live_id
    assert len(canvas.load_entries) == 2
    assert canvas.load_entries[dead_id].payload.fz == -5.0
    assert canvas.load_entries[live_id].payload.fz == -10.0
    # And the pre-existing per-tag store is completely untouched.
    assert canvas.nodal_loads == {}


def test_update_load_entry_replaces_only_the_given_fields() -> None:
    canvas = _canvas()
    node = canvas.add_node(0.0, 0.0)
    canvas.add_load_case("LL_OFFICE")
    entry_id = canvas.add_load_entry("LL_OFFICE", "nodal", (node,), NodalLoadEntry(fz=-10.0))

    canvas.update_load_entry(entry_id, payload=NodalLoadEntry(fz=-20.0))

    entry = canvas.load_entries[entry_id]
    assert entry.payload.fz == -20.0
    assert entry.case_id == "LL_OFFICE"
    assert entry.target == (node,)


def test_duplicate_load_entry_gets_a_fresh_id_and_matching_payload() -> None:
    canvas = _canvas()
    node = canvas.add_node(0.0, 0.0)
    canvas.add_load_case("LL_OFFICE")
    original_id = canvas.add_load_entry("LL_OFFICE", "nodal", (node,), NodalLoadEntry(fz=-10.0))

    copy_id = canvas.duplicate_load_entry(original_id)

    assert copy_id is not None
    assert copy_id != original_id
    assert canvas.load_entries[copy_id].payload == canvas.load_entries[original_id].payload


def test_delete_load_case_cascades_to_its_entries_only() -> None:
    canvas = _canvas()
    node = canvas.add_node(0.0, 0.0)
    canvas.add_load_case("DL_SELF")
    canvas.add_load_case("LL_OFFICE")
    dead_id = canvas.add_load_entry("DL_SELF", "nodal", (node,), NodalLoadEntry(fz=-5.0))
    live_id = canvas.add_load_entry("LL_OFFICE", "nodal", (node,), NodalLoadEntry(fz=-10.0))

    canvas.delete_load_case("DL_SELF")

    assert "DL_SELF" not in canvas.load_cases
    assert dead_id not in canvas.load_entries
    assert live_id in canvas.load_entries


def test_rename_load_case_updates_every_entry_pointing_at_it() -> None:
    canvas = _canvas()
    node = canvas.add_node(0.0, 0.0)
    canvas.add_load_case("LL_OFFICE")
    entry_id = canvas.add_load_entry("LL_OFFICE", "nodal", (node,), NodalLoadEntry(fz=-10.0))

    assert canvas.rename_load_case("LL_OFFICE", "LL_RETAIL") is True

    assert "LL_OFFICE" not in canvas.load_cases
    assert canvas.load_cases["LL_RETAIL"].name == "LL_RETAIL"
    assert canvas.load_entries[entry_id].case_id == "LL_RETAIL"
    assert canvas.active_load_case_id == "LL_RETAIL"


def test_load_entry_crud_is_covered_by_undo_redo() -> None:
    canvas = _canvas()
    node = canvas.add_node(0.0, 0.0)
    canvas.add_load_case("LL_OFFICE")
    canvas.add_load_entry("LL_OFFICE", "nodal", (node,), NodalLoadEntry(fz=-10.0))
    assert len(canvas.load_entries) == 1

    canvas.undo()
    assert len(canvas.load_entries) == 0

    canvas.redo()
    assert len(canvas.load_entries) == 1


def test_add_load_combination_and_update_factors() -> None:
    canvas = _canvas()
    canvas.add_load_combination("ULS-01")

    canvas.update_load_combination("ULS-01", {LoadCaseKind.DEAD: 1.2, LoadCaseKind.LIVE: 1.6})

    combination = canvas.load_combinations["ULS-01"]
    assert combination.factor_for(LoadCaseKind.DEAD) == 1.2
    assert combination.factor_for(LoadCaseKind.LIVE) == 1.6


def test_duplicate_load_combination_copies_factors_under_a_new_name() -> None:
    canvas = _canvas()
    canvas.add_load_combination("ULS-01")
    canvas.update_load_combination("ULS-01", {LoadCaseKind.DEAD: 1.2})

    copy_name = canvas.duplicate_load_combination("ULS-01", "ULS-02")

    assert copy_name == "ULS-02"
    assert canvas.load_combinations["ULS-02"].factor_for(LoadCaseKind.DEAD) == 1.2
    assert canvas.load_combinations["ULS-01"] is not canvas.load_combinations["ULS-02"]


def test_create_load_case_from_combination_scales_selected_load_groups() -> None:
    canvas = _canvas()
    node = canvas.add_node(0.0, 0.0)
    canvas.add_load_case("DL", kind=LoadCaseKind.DEAD)
    canvas.add_load_case("LL", kind=LoadCaseKind.LIVE)
    canvas.add_load_entry("DL", "nodal", (node,), NodalLoadEntry(fz=-5.0))
    canvas.add_load_entry(
        "LL",
        "member_uniform",
        (7,),
        MemberDistributedLoadEntry(direction="y", start_value=-3.0, end_value=-3.0),
    )
    canvas.add_load_combination("ULS")
    canvas.update_load_combination("ULS", {LoadCaseKind.DEAD: 1.2, LoadCaseKind.LIVE: 1.6})

    count = canvas.create_load_case_from_combination(
        "ULS", "ULS_APPLIED", selected_groups={"nodal", "member"}
    )

    assert count == 2
    generated = [entry for entry in canvas.load_entries.values() if entry.case_id == "ULS_APPLIED"]
    nodal = next(entry for entry in generated if entry.kind == "nodal")
    member = next(entry for entry in generated if entry.kind == "member_uniform")
    assert nodal.payload.fz == -6.0
    assert member.payload.start_value == pytest.approx(-4.8)
    assert member.payload.end_value == pytest.approx(-4.8)
    assert canvas.active_load_case_id == "ULS_APPLIED"


def test_create_load_case_from_combination_requires_explicit_replace() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL", kind=LoadCaseKind.DEAD)
    canvas.add_load_combination("ULS")
    canvas.update_load_combination("ULS", {LoadCaseKind.DEAD: 1.2})
    canvas.add_load_case("ULS_APPLIED")

    assert canvas.create_load_case_from_combination("ULS", "ULS_APPLIED") is None
    assert (
        canvas.create_load_case_from_combination(
            "ULS", "ULS_APPLIED", replace_existing=True
        )
        == 0
    )


def test_deleting_a_node_prunes_its_orphaned_nodal_load_entry() -> None:
    """Regression test: delete_selected() used to leave load_entries
    untouched, and new nodes/elements are assigned max()+1 tags - so a
    deleted node's dangling entry would reappear (as an unwanted load
    glyph, and for member-scoped kinds feed build_model()) the moment a
    freshly drawn node/member happened to reuse its old tag."""
    canvas = _canvas()
    canvas.add_node(0.0, 0.0)
    target = canvas.add_node(5.0, 0.0)
    canvas.add_load_case("EQ")
    canvas.add_load_entry("EQ", "nodal", (target,), NodalLoadEntry(fz=-10.0, mx=5.0))
    assert len(canvas.load_entries) == 1

    canvas.selected_nodes = {target}
    canvas.delete_selected()
    assert canvas.load_entries == {}

    reused = canvas.add_node(9.0, 0.0)
    assert reused == target
    assert canvas.load_entries == {}


def test_deleting_an_element_prunes_its_orphaned_member_load_entry() -> None:
    canvas = _canvas()
    a = canvas.add_node(0.0, 0.0)
    b = canvas.add_node(5.0, 0.0)
    member = canvas.add_member(a, b)
    canvas.add_load_case("DL")
    canvas.add_load_entry(
        "DL", "member_partial", (member,), MemberDistributedLoadEntry(start_value=-1.0, end_value=-1.0)
    )
    assert len(canvas.load_entries) == 1

    canvas.selected_elements = {member}
    canvas.delete_selected()
    assert canvas.load_entries == {}

    c = canvas.add_node(9.0, 0.0)
    reused = canvas.add_member(a, c)
    assert reused == member
    assert canvas.load_entries == {}


def test_deleting_a_node_leaves_other_nodes_load_entries_alone() -> None:
    canvas = _canvas()
    keep = canvas.add_node(0.0, 0.0)
    doomed = canvas.add_node(5.0, 0.0)
    canvas.add_load_case("EQ")
    entry_id = canvas.add_load_entry("EQ", "nodal", (keep,), NodalLoadEntry(fz=-10.0))

    canvas.selected_nodes = {doomed}
    canvas.delete_selected()

    assert canvas.load_entries.keys() == {entry_id}


def test_generated_combination_can_be_activated_as_solver_loads() -> None:
    canvas = _canvas()
    canvas.ndm = 3
    node = canvas.add_node(0.0, 0.0)
    canvas.add_load_case("DL", kind=LoadCaseKind.DEAD)
    canvas.add_load_entry("DL", "nodal", (node,), NodalLoadEntry(fz=-10.0))
    canvas.add_load_combination("ULS")
    canvas.update_load_combination("ULS", {LoadCaseKind.DEAD: 1.2})

    canvas.create_load_case_from_combination(
        "ULS", "ULS_APPLIED", activate_for_analysis=True
    )

    assert canvas.nodal_loads[node].values == (0.0, 0.0, -12.0, 0.0, 0.0, 0.0)
