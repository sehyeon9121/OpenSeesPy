import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage

from _solve_helpers import solve_and_wait


def _page(*, start_in_3d: bool = False) -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=start_in_3d)
    page.resize(1280, 800)
    page.show()
    return page


def test_the_right_panel_offers_only_the_two_always_on_widgets() -> None:
    """The right panel is deliberately fixed now: 좌표로 노드 추가 and 이동·복사·
    배열, both always visible, nothing else, no selection-gating. Every other
    editor (지점/노드 유형/부재/하중, 단면·재료 included) lives in the canvas-top
    bar's accordion instead (``_build_node_property_bar``)."""
    page = _page()

    assert page.node_x.isVisible() is True
    assert page.node_transform_operation.isVisible() is True
    assert "선택된 대상이 없습니다" in page.selection_summary.text()


def test_create_section_stays_visible_across_selection_changes() -> None:
    """The relative-offset workflow needs the fields to stay reachable right
    after picking the reference node - create must never disappear just
    because a selection was made, which is the bug this guards against."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)

    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    assert page.node_x.isVisible() is True


def test_the_right_panel_stays_fixed_when_a_node_is_selected() -> None:
    """Selecting a node used to swap the right panel to node-only properties;
    now the panel never changes shape at all - only the top-bar accordion and
    the selection summary respond to what is selected."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)

    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    assert "노드 1개 선택됨" in page.selection_summary.text()
    assert page.node_x.isVisible() is True
    assert page.node_transform_operation.isVisible() is True


def test_activating_a_tool_expands_its_own_slide_out_and_collapses_the_others() -> None:
    """지점/노드 유형/부재/하중 share one accordion (``_SlideOutGroup``): opening
    one must automatically close whichever was open before, or the top bar
    recreates the "everything laid out at once" clutter it exists to avoid."""
    page = _page()

    page._activate_support_tool()
    assert page.support_slide_out.toggle_button.isChecked() is True

    page._activate_load_tool()
    assert page.load_slide_out.toggle_button.isChecked() is True
    assert page.support_slide_out.toggle_button.isChecked() is False


def test_selecting_a_member_refreshes_the_member_bar_and_the_summary() -> None:
    page = _page()
    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(first, second)

    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    assert "부재 1개 선택됨" in page.selection_summary.text()
    assert page.member_end_i.text() == "N1 쪽 핀 해제 (모멘트 0)"
    assert page.member_end_j.text() == "N2 쪽 핀 해제 (모멘트 0)"


def test_toggling_the_member_end_checkbox_releases_that_end_only() -> None:
    page = _page()
    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(first, second)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    page.member_end_i.setChecked(True)

    element = page.canvas.elements[member]
    assert element.moment_release_i is True
    assert element.moment_release_j is False


def test_inserting_a_member_station_node_from_the_panel_reaches_the_canvas() -> None:
    """An explicit 부재 위 노드 삽입 splits the member into two independent
    elements immediately (not just an analysis-time embedded point), so each
    side can carry its own load - see canvas_geometry.py's _add_node_at."""
    page = _page()
    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(first, second)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    page.member_station.setValue(0.25)
    page._insert_member_station_node()

    assert len(page.canvas.embedded_nodes) == 0
    assert len(page.canvas.elements) == 2
    inserted = next(tag for tag, node in page.canvas.nodes.items() if tag not in (first, second))
    assert page.canvas.nodes[inserted].x == pytest.approx(1.0)
    spans = {(el.node_i, el.node_j) for el in page.canvas.elements.values()}
    assert spans == {(first, inserted), (inserted, second)}


def test_the_node_transform_tool_filters_selection_to_nodes_only() -> None:
    """이동·복사·배열 works on nodes, so activating it from the rail narrows the
    selection filter to nodes-only - the same "no dead zone left behind" rule
    the load/support tools follow, checked below by the returning-to-select test."""
    page = _page()

    page._activate_node_transform_tool()
    assert page.selection_filter.currentData() == "nodes"


def test_the_two_rail_tools_are_mutually_exclusive() -> None:
    page = _page()

    page._activate_draw_tool()
    assert page.canvas.mode == "draw"
    assert page.draw_tool.isChecked() is True
    assert page.select_tool.isChecked() is False

    page._activate_select_tool()
    assert page.canvas.mode == "select"
    assert page.select_tool.isChecked() is True
    assert page.draw_tool.isChecked() is False


def test_choosing_the_free_support_removes_an_existing_one() -> None:
    """지점 조건 is now a row of instant-apply icon buttons (index 0 = 자유),
    not a combo + separate 적용 button — clicking one applies immediately."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.apply_support_to_selection((True, True, False))
    assert len(page.canvas.build_model().boundaries) == 1

    page.support_buttons[0].click()  # 자유

    assert page.canvas.build_model().boundaries == []
    assert "지점 0" in page.model_status.text()


def test_the_support_angle_field_reaches_the_canvas_as_an_inclined_boundary() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_buttons[2].click()  # 수직롤러
    page.support_angle.setValue(30.0)
    page.support_angle.editingFinished.emit()

    boundary = page.canvas.build_model().boundaries[0]
    assert boundary.angle == pytest.approx(30.0)
    assert boundary.is_inclined is True


def test_the_mirror_controls_reach_the_canvas() -> None:
    page = _page()
    left = page.canvas.add_node(0.0, 0.0)
    right = page.canvas.add_node(4.0, 0.0)
    page.canvas.add_member(left, right)
    page.canvas.selected_nodes = {left, right}
    page.canvas.selection_changed.emit()

    page.mirror_axis.setCurrentIndex(page.mirror_axis.findData("x"))
    page.mirror_value.setValue(4.0)
    page._apply_mirror()

    assert len(page.canvas.nodes) == 3
    assert len(page.canvas.elements) == 2


def test_the_array_copy_operation_reaches_the_canvas_and_reproduces_members() -> None:
    page = _page()
    left = page.canvas.add_node(0.0, 0.0)
    right = page.canvas.add_node(2.0, 0.0)
    page.canvas.add_member(left, right)
    page.canvas.selected_nodes = {left, right}
    page.canvas.selection_changed.emit()

    page.node_transform_operation.setCurrentIndex(
        page.node_transform_operation.findData("array")
    )
    page.node_transform_dx.setValue(2.0)
    page.node_transform_dy.setValue(0.0)
    page.node_transform_repeat.setValue(2)
    page._apply_node_transform()

    # dx equals the original bay width, so each new copy's near node lands exactly on
    # the previous bay's far node and is reused: 2 original + 1 new node per step.
    assert len(page.canvas.nodes) == 4
    assert len(page.canvas.elements) == 3


def test_the_subdivide_control_reaches_the_canvas() -> None:
    """Equal subdivision now creates independent elements immediately (see
    canvas_transforms.py's subdivide_member), not analysis-time embedded
    points - each of the 3 equal pieces must be independently loadable."""
    page = _page()
    left = page.canvas.add_node(0.0, 0.0)
    right = page.canvas.add_node(6.0, 0.0)
    member = page.canvas.add_member(left, right)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    page.member_segments.setValue(3)
    page._subdivide_member()

    assert len(page.canvas.embedded_nodes) == 0
    assert len(page.canvas.elements) == 3
    assert len(page.canvas.build_model().elements) == 3
    xs = sorted(node.x for node in page.canvas.nodes.values())
    assert xs == pytest.approx([0.0, 2.0, 4.0, 6.0])


def test_the_f_shortcut_recentres_the_canvas_on_the_model() -> None:
    from PySide6.QtCore import QPointF

    page = _page()
    page.canvas.resize(400, 300)
    page.canvas.place_point(0.0, 0.0)
    page.canvas.place_point(6.0, 4.0)
    page.canvas.end_chain()
    page.canvas.centerOn(QPointF(50_000.0, 50_000.0))

    page.fit_shortcut.activated.emit()

    center = page.canvas.mapToScene(page.canvas.viewport().rect().center())
    assert abs(center.x()) < 1000


def test_applying_a_load_sets_every_component_at_once_without_losing_earlier_ones() -> None:
    """Regression test for the overwrite bug: the old direction-dropdown form
    replaced the whole load on every apply, so setting Fx then Fy silently
    discarded Fx. Every component is now a field in the same form."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.load_fields["fx"].setValue(5.0)
    page.load_fields["fy"].setValue(-12.0)
    page.load_fields["mz"].setValue(3.0)
    page._apply_load()

    load = page.canvas.build_model().nodal_loads[0]
    # Mz is typed 시계방향(+)/반시계방향(-) - the opposite of the stored
    # right-hand-rule sign OpenSees itself needs - so a typed +3 stores as -3.
    assert load.values == pytest.approx((5.0, -12.0, -3.0))


def test_a_clockwise_moment_is_typed_positive_and_stores_as_the_right_hand_rule_negative() -> None:
    """시계방향(clockwise) is + in the field the user types, 반시계방향
    (counter-clockwise) is - - the opposite of the signed value OpenSees
    itself expects for a moment about +Z (+ = CCW). The flip has to happen
    exactly once, here, so everything downstream (the solver, saved
    projects) keeps working in the one standard convention."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.load_fields["mz"].setValue(10.0)  # 10, clockwise
    page._apply_load()
    assert page.canvas.build_model().nodal_loads[0].values[2] == pytest.approx(-10.0)

    page.canvas.selected_nodes = {node}
    page.load_fields["mz"].setValue(-4.0)  # 4, counter-clockwise
    page._apply_load()
    assert page.canvas.build_model().nodal_loads[0].values[2] == pytest.approx(4.0)


def test_magnitude_and_angle_convert_to_fx_fy_matching_standard_trig() -> None:
    """각도 uses the same convention as the draw-mode 길이<각도 entry: degrees
    counter-clockwise from global +X."""
    page = _page()

    page.load_magnitude.setValue(10.0)
    page.load_angle.setValue(30.0)
    page._apply_magnitude_angle_to_fxfy()

    assert page.load_fields["fx"].value() == pytest.approx(10.0 * math.cos(math.radians(30.0)))
    assert page.load_fields["fy"].value() == pytest.approx(10.0 * math.sin(math.radians(30.0)))


def test_perpendicular_to_member_button_fills_the_angle_field_from_member_slope() -> None:
    """A load perpendicular to a sloped member (e.g. wind pressure on a
    gable roof, textbook figures resolving a force into components
    perpendicular/parallel to the rafter) can be entered without computing
    the member's own slope angle by hand first."""
    page = _page()
    canvas = page.canvas
    horizontal_a = canvas.add_node(0.0, 0.0)
    horizontal_b = canvas.add_node(4.0, 0.0)
    horizontal_member = canvas.add_member(horizontal_a, horizontal_b)
    sloped_a = canvas.add_node(0.0, 4.0)
    sloped_b = canvas.add_node(4.0, 8.0)  # 45 degrees
    sloped_member = canvas.add_member(sloped_a, sloped_b)

    canvas.selected_elements = {horizontal_member}
    canvas.selected_nodes = {horizontal_a}  # the load's actual target node
    page._fill_angle_perpendicular_to_selected_member()
    assert page.load_angle.value() == pytest.approx(90.0)

    canvas.selected_elements = {sloped_member}
    page._fill_angle_perpendicular_to_selected_member()
    assert page.load_angle.value() == pytest.approx(135.0)

    # No selected member (0 or 2+) -> leaves whatever angle was already there.
    canvas.selected_elements = set()
    page._fill_angle_perpendicular_to_selected_member()
    assert page.load_angle.value() == pytest.approx(135.0)


def test_load_fields_gain_fz_mx_my_once_3d_mode_is_active() -> None:
    page = _page()
    assert set(page.load_fields) == {"fx", "fy", "mz"}

    page_3d = _page(start_in_3d=True)

    assert set(page_3d.load_fields) == {"fx", "fy", "fz", "mx", "my", "mz"}


def test_custom_support_lets_a_single_dof_be_restrained_on_its_own() -> None:
    """None of the five presets can restrain rotation alone; the custom option
    has to reach every combination, not just the common ones."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_buttons[5].click()  # 커스텀
    assert page.support_custom_row.isVisible() is True
    page.support_dof_checks["Rz"].setChecked(True)

    boundary = page.canvas.build_model().boundaries[0]
    assert boundary.restraints == (False, False, True)


def test_custom_support_reaches_all_six_dof_in_3d() -> None:
    page = _page(start_in_3d=True)
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_buttons[5].click()  # 커스텀
    for dof in ("Ux", "Uz", "Ry"):
        page.support_dof_checks[dof].setChecked(True)

    boundary = page.canvas.build_model().boundaries[0]
    assert boundary.restraints == (True, False, True, False, True, False)


def test_a_hinge_is_labelled_as_a_joint_distinct_from_an_ordinary_node() -> None:
    """MIDAS convention, per the user: 노드 (node) is a rigid connection point,
    절점 (joint) specifically means a hinge/pin release. The selection summary
    must say which one is selected, not lump both under one generic word."""
    page = _page()
    rigid = page.canvas.add_node(0.0, 0.0)
    hinge = page.canvas.add_node(4.0, 0.0)
    page.canvas.selected_nodes = {hinge}
    page.canvas.set_selected_node_kind(True)

    page.canvas.selected_nodes = {hinge}
    page.canvas.selection_changed.emit()
    assert "절점 1개" in page.selection_summary.text()
    assert "노드" not in page.selection_summary.text()

    page.canvas.selected_nodes = {rigid, hinge}
    page.canvas.selection_changed.emit()
    assert "노드 1개" in page.selection_summary.text()
    assert "절점 1개" in page.selection_summary.text()

    page.canvas.selected_nodes = {rigid}
    page.canvas.selection_changed.emit()
    assert "노드 1개" in page.selection_summary.text()
    assert "절점" not in page.selection_summary.text()


def test_node_kind_and_support_combos_resync_to_the_new_selection_not_the_last_edit() -> None:
    """A node clicked to build a member or place a nodal load must stay a plain
    rigid node. Before this fix, marking one node as a 절점 (hinge) left the
    노드 유형 buttons on 절점 forever — selecting an unrelated node afterwards
    still showed 절점, so a second stray click could hinge a node nobody meant
    to touch."""
    page = _page()
    hinge = page.canvas.add_node(0.0, 0.0)
    other = page.canvas.add_node(4.0, 0.0)
    page.canvas.selected_nodes = {hinge}
    page.canvas.set_selected_node_kind(True)

    page.canvas.selected_nodes = {other}
    page.canvas.selection_changed.emit()

    assert page.node_kind_rigid_button.isChecked() is True
    assert other not in page.canvas.hinge_nodes


def test_support_combo_resyncs_to_the_selected_nodes_actual_boundary_condition() -> None:
    page = _page()
    pinned = page.canvas.add_node(0.0, 0.0)
    free = page.canvas.add_node(4.0, 0.0)
    page.canvas.selected_nodes = {pinned}
    page.canvas.apply_support_to_selection((True, True, False), 0.0)

    page.canvas.selected_nodes = {pinned}
    page.canvas.selection_changed.emit()
    assert page.support_buttons[1].isChecked() is True  # 핀

    page.canvas.selected_nodes = {free}
    page.canvas.selection_changed.emit()
    assert page.support_buttons[0].isChecked() is True  # 자유


def test_escape_while_drawing_returns_to_select_and_syncs_the_rail_button() -> None:
    from PySide6.QtGui import QKeyEvent

    page = _page()
    page._activate_draw_tool()
    page.canvas.place_point(0.0, 0.0)
    page.canvas.place_point(4.0, 0.0)
    assert page.draw_tool.isChecked() is True

    page.canvas.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )

    assert page.canvas.mode == "select"
    assert page.select_tool.isChecked() is True
    assert page.draw_tool.isChecked() is False


def test_choosing_a_load_target_never_narrows_what_the_canvas_can_still_select() -> None:
    """Regression test: choosing 부재 as the load target used to narrow the
    selection filter to elements-only, permanently, since 하중 is now an
    always-open accordion section with no "leave this tool" step left to
    widen it back (that widening only ever happened in
    _activate_select_tool, reachable only via Escape-from-draw or the rail's
    선택 button) - so a later click on a node would be silently ignored with
    no visible reason why, reported as "노드를 선택하려고 드래그했는데 안
    잡힘, 그리기로 갔다가 취소해야 풀림" (the Escape-from-draw path happened
    to widen the filter back as a side effect, which is how that workaround
    ever "worked"). Picking a load target must never touch the filter at
    all now — 적용 already no-ops safely against whatever is selected."""
    page = _page()
    member_a = page.canvas.add_node(0.0, 0.0)
    member_b = page.canvas.add_node(4.0, 0.0)
    page.canvas.add_member(member_a, member_b)
    other_node = page.canvas.add_node(4.0, 3.0)

    page.load_target_group.button(1).click()  # 등분포하중 (element)
    assert page.canvas.selection_filter == "all"

    page.canvas.selected_nodes = set()
    page.canvas._toggle_selection(("node", other_node), Qt.KeyboardModifier.NoModifier)
    assert other_node in page.canvas.selected_nodes


def test_the_determinacy_badge_updates_while_the_model_is_being_drawn() -> None:
    page = _page()
    page._activate_draw_tool()
    page.canvas.place_point(0.0, 0.0)
    page.canvas.place_point(4.0, 0.0)

    assert "불안정" in page.determinacy_status.text()

    left = page.canvas.elements[1].node_i
    right = page.canvas.elements[1].node_j
    page.canvas.set_support(left, (True, True, False))
    page.canvas.set_support(right, (False, True, False))

    assert "정정구조" in page.determinacy_status.text()


def test_returning_to_the_model_and_back_shows_the_same_solved_results_without_resolving() -> None:
    """A solved model must stay viewable after a trip back to the canvas.

    Before this fix the only way back to the results page was the solve
    button itself, which re-checks determinacy against whatever the canvas
    holds *right now* — so a harmless excursion back to modeling (even one
    that leaves the canvas in a temporarily-unstable state, e.g. mid-edit)
    would blow away the already-computed, still-valid results with a fresh
    (and possibly spuriously unstable) solve."""
    page = _page()
    left = page.canvas.add_node(0.0, 0.0)
    right = page.canvas.add_node(4.0, 0.0)
    page.canvas.add_member(left, right)
    page.canvas.set_support(left, (True, True, False))
    page.canvas.set_support(right, (False, True, False))

    assert not page.view_results_button.isEnabled()
    solve_and_wait(page)
    assert page.workspace_stack.currentIndex() == 1
    assert page.view_results_button.isEnabled()
    solved_result = page.results.viewport._result

    page.workspace_stack.setCurrentIndex(0)
    # Leave the canvas in a state that would fail determinacy if re-checked.
    page.canvas.set_support(right, (False, False, False))
    assert "불안정" in page.determinacy_status.text()

    page.view_results_button.click()

    assert page.workspace_stack.currentIndex() == 1
    assert page.results.viewport._result is solved_result


def test_2d_results_hide_the_dormant_3d_view_selector() -> None:
    """The RESULT toolbar's VIEW field ("2D Front" / "3D Isometric (Future)")
    is inert chrome, not wired to the real projection control — showing a
    selectable "3D Isometric" option next to a purely 2D result is just
    confusing occupied space for a model that has no such view."""
    page = _page()
    left = page.canvas.add_node(0.0, 0.0)
    right = page.canvas.add_node(4.0, 0.0)
    page.canvas.add_member(left, right)
    page.canvas.set_support(left, (True, True, False))
    page.canvas.set_support(right, (False, True, False))

    solve_and_wait(page)

    assert not page.results.toolbar.view_mode.parentWidget().isVisible()


def test_adding_a_node_by_relative_coordinates_offsets_from_the_selected_node() -> None:
    page = _page()
    anchor = page.canvas.add_node(3.0, 4.0)
    page.canvas.selected_nodes = {anchor}
    page.canvas.selection_changed.emit()

    page.node_relative.setChecked(True)
    page.node_x.setValue(2.0)
    page.node_y.setValue(-1.0)
    page.node_repeat.setValue(1)
    page._add_nodes_from_coordinates()

    model = page.canvas.build_model()
    new_node = next(node for tag, node in model.nodes.items() if tag != anchor)
    assert (new_node.x, new_node.y) == pytest.approx((5.0, 3.0))


def test_relative_node_entry_falls_back_to_the_origin_without_a_single_selection() -> None:
    page = _page()
    page.node_relative.setChecked(True)
    page.node_x.setValue(2.0)
    page.node_y.setValue(-1.0)
    page.node_repeat.setValue(1)
    page._add_nodes_from_coordinates()

    model = page.canvas.build_model()
    (node,) = model.nodes.values()
    assert (node.x, node.y) == pytest.approx((2.0, -1.0))


def test_vertical_roller_restrains_horizontal_movement_not_vertical() -> None:
    """The user found the original naming counter-intuitive and asked for the
    axes to swap: 수직 롤러 (vertical roller) now blocks Ux, 수평 롤러
    (horizontal roller) now blocks Uy — the opposite of the original mapping."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_buttons[2].click()  # 수직롤러
    assert page.canvas.build_model().boundaries[0].restraints == (True, False, False)

    page.support_buttons[3].click()  # 수평롤러
    assert page.canvas.build_model().boundaries[0].restraints == (False, True, False)


def test_truss_mode_toggle_governs_members_drawn_from_then_on_only() -> None:
    """Turning 트러스 모드 on/off is a drawing-time choice, like a pen colour —
    it must not retroactively change members already on the canvas."""
    page = _page()
    assert page.canvas.element_family == "frame"

    a = page.canvas.add_node(0.0, 0.0)
    b = page.canvas.add_node(4.0, 0.0)
    frame_member = page.canvas.add_member(a, b)

    page.truss_mode_toggle.setChecked(True)
    assert page.canvas.element_family == "truss"

    c = page.canvas.add_node(2.0, 3.0)
    truss_member_1 = page.canvas.add_member(a, c)
    truss_member_2 = page.canvas.add_member(b, c)

    page.truss_mode_toggle.setChecked(False)
    assert page.canvas.element_family == "frame"
    d = page.canvas.add_node(2.0, -3.0)
    frame_member_2 = page.canvas.add_member(a, d)

    model = page.canvas.build_model()
    assert model.elements[frame_member].element_type == "frame"
    assert model.elements[truss_member_1].element_type == "truss"
    assert model.elements[truss_member_2].element_type == "truss"
    assert model.elements[frame_member_2].element_type == "frame"


def test_a_determinate_truss_solves_with_one_constant_axial_value_per_member() -> None:
    """A truss member has no bending — its N/V/M diagram is flat, which the
    existing diagram machinery already collapses to a single labelled value
    at the member's midpoint (see FrameDiagramRenderer._draw_values), giving
    the 부재력 표시 a truss needs without any separate rendering path."""
    page = _page()
    page.truss_mode_toggle.setChecked(True)
    a = page.canvas.add_node(0.0, 0.0)
    b = page.canvas.add_node(4.0, 0.0)
    c = page.canvas.add_node(2.0, 3.0)
    page.canvas.add_member(a, b)
    page.canvas.add_member(a, c)
    page.canvas.add_member(b, c)
    page.canvas.selected_nodes = {a}
    page.canvas.apply_support_to_selection((True, True, False))
    page.canvas.selected_nodes = {b}
    page.canvas.apply_support_to_selection((False, True, False))
    page.canvas.selected_nodes = {c}
    page.canvas.apply_nodal_load_to_selection((0.0, -10.0, 0.0))

    solve_and_wait(page)

    assert page.workspace_stack.currentIndex() == 1
    result = page.results.viewport._result
    from openframe.features.results.diagrams.build import member_diagrams

    for element_result in result.element_results.values():
        axial, shear, moment = member_diagrams(element_result)
        assert axial.points[0].value == pytest.approx(axial.points[-1].value)
        assert all(point.value == pytest.approx(0.0, abs=1.0e-9) for point in shear.points)
        assert all(point.value == pytest.approx(0.0, abs=1.0e-9) for point in moment.points)


def test_truss_results_table_lists_joints_force_and_tension_compression_zero() -> None:
    """부재력 표: for a truss, the TABLE tab must read as a 부재 번호 / 절점 (i-j) /
    축력 / 인장·압축·0부재 sheet — not the frame table's N/V/M-i columns, since V
    and M are always zero and say nothing about a two-force member."""
    page = _page()
    page.truss_mode_toggle.setChecked(True)
    a = page.canvas.add_node(0.0, 0.0)
    b = page.canvas.add_node(4.0, 0.0)
    c = page.canvas.add_node(2.0, 3.0)
    d = page.canvas.add_node(2.0, 5.0)
    tension_member = page.canvas.add_member(a, b)
    compression_member = page.canvas.add_member(a, c)
    page.canvas.add_member(b, c)
    zero_force_member = page.canvas.add_member(c, d)
    page.canvas.add_member(b, d)
    page.canvas.selected_nodes = {a}
    page.canvas.apply_support_to_selection((True, True, False))
    page.canvas.selected_nodes = {b}
    page.canvas.apply_support_to_selection((False, True, False))
    page.canvas.selected_nodes = {c}
    page.canvas.apply_nodal_load_to_selection((0.0, -10.0, 0.0))

    solve_and_wait(page)
    panel = page.results.data_panel
    panel.set_result_type("axial")
    table = panel.result_table

    assert [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())] == [
        "부재",
        "절점 (i-j)",
        f"축력 N ({page._unit_system.force})",
        "상태",
    ]

    def row_for(element_tag: int) -> list[str]:
        for row in range(table.rowCount()):
            if table.item(row, 0).text() == str(element_tag):
                return [table.item(row, column).text() for column in range(table.columnCount())]
        raise AssertionError(f"no row for element {element_tag}")

    assert row_for(tension_member)[1] == f"{a}-{b}"
    assert row_for(tension_member)[3] == "인장"
    assert row_for(compression_member)[3] == "압축"
    assert row_for(zero_force_member)[3] == "0부재"
