import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    page.resize(1280, 800)
    page.show()
    return page


def _visible(page: ModelingInterfacePage) -> set[str]:
    return {key for key, section in page._sections.items() if section.isVisible()}


def test_an_empty_selection_offers_the_always_on_sections() -> None:
    """create(좌표로 노드 추가)/material(재료 물성치)/node(지점 상세) 모두
    선택 여부와 무관하게 항상 보인다 - 학생이 지점을 설정하거나 좌표로 노드를
    추가하려고 먼저 뭔가를 선택할 필요 없이 바로 컨트롤을 볼 수 있게. 하중은
    이제 우측 패널이 아니라 캔버스 상단 막대의 슬라이드아웃에 있다."""
    page = _page()

    assert _visible(page) == {"create", "material", "node"}
    assert "선택된 대상이 없습니다" in page.selection_summary.text()


def test_create_section_stays_visible_across_selection_changes() -> None:
    """The relative-offset workflow needs the fields to stay reachable right
    after picking the reference node - create must never disappear just
    because a selection was made, which is the bug this guards against."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)

    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    assert "create" in _visible(page)


def test_selecting_a_node_swaps_the_panel_to_node_properties() -> None:
    """Move/copy/array/mirror stays collapsed by default: it is the panel's widest
    block and most selections only need a support or a load, not a geometry op."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)

    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    assert _visible(page) == {"create", "material", "node"}
    assert "노드 1개 선택됨" in page.selection_summary.text()

    page._toggle_transform_section()
    assert "transform" in _visible(page)
    assert "감추기" in page.transform_toggle.text()

    page._toggle_transform_section()
    assert "transform" not in _visible(page)


def test_selecting_a_member_adds_member_properties_alongside_the_always_on_sections() -> None:
    page = _page()
    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(first, second)

    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    assert _visible(page) == {"create", "material", "node", "member"}
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
    page = _page()
    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(first, second)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    page.member_station.setValue(0.25)
    page._insert_member_station_node()

    inserted = next(iter(page.canvas.embedded_nodes))
    assert page.canvas.embedded_nodes[inserted] == (member, pytest.approx(0.25))
    assert page.canvas.nodes[inserted].x == pytest.approx(1.0)


def test_a_pinned_section_stays_open_until_the_selection_moves() -> None:
    """node/load are always visible now, so pinning them has no visibility effect
    left to observe - transform (move/copy/array/mirror, collapsed by default) is
    the section that still actually toggles, so it's the one this test pins."""
    page = _page()

    page._activate_node_transform_tool()
    assert "transform" in _visible(page)

    page.canvas.selection_changed.emit()
    assert "transform" not in _visible(page)


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
    page = _page()
    left = page.canvas.add_node(0.0, 0.0)
    right = page.canvas.add_node(6.0, 0.0)
    member = page.canvas.add_member(left, right)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    page.member_segments.setValue(3)
    page._subdivide_member()

    assert len(page.canvas.embedded_nodes) == 2
    assert len(page.canvas.build_model().elements) == 3


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
    assert load.values == pytest.approx((5.0, -12.0, 3.0))


def test_load_fields_gain_fz_mx_my_once_3d_mode_is_active() -> None:
    page = _page()
    assert set(page.load_fields) == {"fx", "fy", "mz"}

    page.mode_3d_toggle.setChecked(True)

    assert set(page.load_fields) == {"fx", "fy", "fz", "mx", "my", "mz"}


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
    page = _page()
    page.mode_3d_toggle.setChecked(True)
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


def test_returning_to_select_widens_a_selection_filter_left_narrowed_by_a_load_target() -> None:
    """Regression test: choosing 부재 as the load target narrows the selection
    filter to elements-only so the load section stays relevant to what you just
    picked — but nothing ever widened it back. A later click on a node would
    then be silently ignored with no visible reason why, which is exactly what
    a user reported as "nodes suddenly can't be selected"."""
    page = _page()
    member_a = page.canvas.add_node(0.0, 0.0)
    member_b = page.canvas.add_node(4.0, 0.0)
    page.canvas.add_member(member_a, member_b)
    other_node = page.canvas.add_node(4.0, 3.0)

    page.load_target_group.button(1).click()  # 등분포하중 (element)
    assert page.canvas.selection_filter == "elements"

    page._activate_select_tool()
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
    page.solve()
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

    page.solve()

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
