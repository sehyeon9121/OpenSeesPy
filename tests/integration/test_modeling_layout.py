import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
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


def test_an_empty_selection_offers_creation_only() -> None:
    page = _page()

    assert _visible(page) == {"create"}
    assert "선택된 대상이 없습니다" in page.selection_summary.text()


def test_selecting_a_node_swaps_the_panel_to_node_properties() -> None:
    """Move/copy/array/mirror stays collapsed by default: it is the panel's widest
    block and most selections only need a support or a load, not a geometry op."""
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)

    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    assert _visible(page) == {"node", "load"}
    assert "절점 1개 선택됨" in page.selection_summary.text()

    page._toggle_transform_section()
    assert "transform" in _visible(page)
    assert "감추기" in page.transform_toggle.text()

    page._toggle_transform_section()
    assert "transform" not in _visible(page)


def test_selecting_a_member_offers_loads_and_member_properties_but_not_node_properties() -> None:
    page = _page()
    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(first, second)

    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    assert _visible(page) == {"load", "member"}
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
    page = _page()

    page._activate_support_tool()
    assert "node" in _visible(page)

    page.canvas.selection_changed.emit()
    assert "node" not in _visible(page)


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
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.apply_support_to_selection((True, True, False))
    assert len(page.canvas.build_model().boundaries) == 1

    page.support_kind.setCurrentIndex(page.support_kind.findText("자유 (지점 없음)"))
    page.canvas.apply_support_to_selection(page.support_kind.currentData())

    assert page.canvas.build_model().boundaries == []
    assert "지점 0" in page.model_status.text()


def test_the_support_angle_field_reaches_the_canvas_as_an_inclined_boundary() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_kind.setCurrentIndex(page.support_kind.findText("수직 롤러"))
    page.support_angle.setValue(30.0)
    page.canvas.apply_support_to_selection(
        page.support_kind.currentData(), page.support_angle.value()
    )

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
