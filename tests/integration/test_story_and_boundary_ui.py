"""3D-only UI wiring for the three "building" features added this session:
Story Manager (+ its Story workbench tab), elastic spring supports (the custom
support row's new stiffness fields), and rigid end offsets (the member
panel's new offset-length fields). Spring/offset fields must stay entirely
invisible in 2D - see feedback_3d_workspace_only_dont_touch_2d.md.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from openframe.core.domain import UnitSystem
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page(*, start_in_3d: bool = False) -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=start_in_3d)
    page.resize(1280, 800)
    page.show()
    return page


def test_story_tab_exists_on_both_2d_and_3d_workbench() -> None:
    page_2d = _page()
    page_3d = _page(start_in_3d=True)
    assert "story" in page_2d.workbench_buttons
    assert "story" in page_3d.workbench_buttons


def test_story_tab_left_dock_launches_story_manager_in_3d() -> None:
    page = _page(start_in_3d=True)
    page._activate_workbench_tab("story", show_settings=False)

    assert page.category_stack.currentIndex() == page.category_pages["story"]
    assert page.left_panel_stack.isVisible()
    button = page.findChild(QPushButton, "storyManagerButton")
    assert button is not None
    assert "Story Manager" in button.text()


def test_story_manager_dialog_edits_the_canvas() -> None:
    from openframe.features.model.presentation.story_manager_dialog import StoryManagerDialog

    page = _page(start_in_3d=True)
    dialog = StoryManagerDialog(page.canvas, parent=page)
    dialog.name_input.setText("1층")
    dialog._add_story()

    assert "1층" in page.canvas.stories


def test_spring_fields_only_exist_in_3d_support_panel() -> None:
    page_2d = _page()
    page_2d._show_category("support")
    assert not hasattr(page_2d, "support_spring_fields")

    page_3d = _page(start_in_3d=True)
    page_3d._show_category("support")
    assert hasattr(page_3d, "support_spring_fields")
    # Story Manager moved off Supports into its own workbench tab.
    assert page_3d.category_stack.currentIndex() == page_3d.category_pages["support"]
    page_3d._activate_workbench_tab("story", show_settings=False)
    assert page_3d.findChild(QPushButton, "storyManagerButton") is not None


def test_spring_stiffness_field_applies_only_to_an_unrestrained_dof() -> None:
    page = _page(start_in_3d=True)
    page._show_category("support")
    node = page.canvas._add_node_at((0.0, 0.0, 0.0))
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_buttons[6].click()  # 커스텀
    page.support_dof_checks["Ux"].setChecked(True)
    page.support_dof_checks["Uz"].setChecked(True)
    page.support_spring_fields["Uy"].setValue(750.0)
    page._apply_support()

    boundary = page.canvas.boundaries[node]
    assert boundary.restraints == (True, False, True, False, False, False)
    assert boundary.spring_stiffnesses[1] == pytest.approx(750.0)


def test_switching_to_a_fixed_preset_drops_any_previously_set_spring() -> None:
    page = _page(start_in_3d=True)
    page._show_category("support")
    node = page.canvas._add_node_at((0.0, 0.0, 0.0))
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_buttons[6].click()  # 커스텀
    page.support_spring_fields["Uy"].setValue(750.0)
    page._apply_support()
    assert page.canvas.boundaries[node].spring_stiffnesses

    page.support_buttons[2].click()  # 고정
    page._apply_support()

    assert page.canvas.boundaries[node].spring_stiffnesses == ()


def test_rigid_offset_fields_apply_along_the_members_own_axis() -> None:
    page = _page(start_in_3d=True)
    page._show_category("member")
    a = page.canvas._add_node_at((0.0, 0.0, 0.0))
    b = page.canvas._add_node_at((0.0, 0.0, 4.0))
    member = page.canvas.add_member(a, b)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    page.member_offset_i.setValue(0.3)
    page.member_offset_j.setValue(0.5)
    page._apply_member_rigid_offsets()

    element = page.canvas.elements[member]
    assert element.offset_i == pytest.approx((0.0, 0.0, 0.3))
    assert element.offset_j == pytest.approx((0.0, 0.0, -0.5))


def test_rigid_offset_row_is_hidden_in_2d() -> None:
    page = _page()
    page._show_category("member")
    a = page.canvas.add_node(0.0, 0.0)
    b = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(a, b)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()

    assert page.member_offset_row.isVisible() is False


def test_spring_field_labels_show_translational_vs_rotational_units() -> None:
    page = _page(start_in_3d=True)
    page._show_category("support")

    assert page.support_spring_field_labels["Uy"].text() == "Uy (kN/m)"
    assert page.support_spring_field_labels["Rz"].text() == "Rz (kN·m)"


def test_rigid_offset_labels_show_the_length_unit() -> None:
    page = _page(start_in_3d=True)
    page._show_category("member")

    assert page.member_offset_i_label.text() == "i단 강체길이 (m)"
    assert page.member_offset_j_label.text() == "j단 강체길이 (m)"


def test_changing_units_updates_spring_and_offset_labels() -> None:
    page = _page(start_in_3d=True)
    page._show_category("support")
    page._show_category("member")

    page.set_unit_system(UnitSystem(force="N", length="mm"))

    assert page.support_spring_field_labels["Uy"].text() == "Uy (N/mm)"
    assert page.support_spring_field_labels["Rz"].text() == "Rz (N·mm)"
    assert page.member_offset_i_label.text() == "i단 강체길이 (mm)"
