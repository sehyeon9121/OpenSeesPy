"""End-to-end flow through the MIDAS-style 3D Loads command picker."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.theme import apply_application_theme
from openframe.core.domain import LoadCaseKind, NodalLoadEntry
from openframe.features.model.presentation.load_combination_manager_dialog import (
    LoadCombinationManagerDialog,
)
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page() -> ModelingInterfacePage:
    application = QApplication.instance() or QApplication([])
    if not application.property("openframeThemeApplied"):
        apply_application_theme(application)
        application.setProperty("openframeThemeApplied", True)
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1400, 900)
    page.show()
    page.canvas.ndm = 3
    return page


def test_the_quick_input_load_bar_is_still_reachable_alongside_the_new_manager() -> None:
    """The mode toggle this feature adds must never hide the pre-existing,
    solver-connected load bar - see _build_3d_load_category's docstring."""
    page = _page()
    page._activate_load_tool()
    assert hasattr(page, "load_target_group")
    assert hasattr(page, "load_fields")


def test_creating_a_case_selecting_a_nodal_target_and_applying_shows_up_in_the_tree() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    case_id = page.canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)
    assert case_id == "LL_OFFICE"

    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("nodal"))
    page.load_fields["fz"].setValue(-10.0)
    page.load_apply_button.click()

    assert len(page.canvas.load_entries) == 1
    entry = next(iter(page.canvas.load_entries.values()))
    assert entry.case_id == "LL_OFFICE"
    assert entry.payload.fz == -10.0

    case_item = page._work_tree_case_items["LL_OFFICE"]
    assert case_item.text(0) == "LL_OFFICE"
    nodal_group = case_item.child(0)
    assert nodal_group.text(0).startswith("Nodal Loads (1)")
    assert nodal_group.child(0).text(0) == "NL-001"


def test_applying_without_a_target_selected_reports_a_warning_and_adds_nothing() -> None:
    page = _page()
    page.canvas.add_load_case("LL_OFFICE")
    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("member_point"))

    page.load3d_apply_button.click()

    assert page.canvas.load_entries == {}
    assert "선택" in page.load3d_status_label.text()


def test_member_uniform_load_applies_the_same_start_and_end_value() -> None:
    page = _page()
    a = page.canvas.add_node(0.0, 0.0)
    b = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(a, b)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("DL_SELF", kind=LoadCaseKind.DEAD)

    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("member_uniform"))
    page.load_fields["qy"].setValue(-3.0)
    page.load_apply_button.click()

    entry = next(iter(page.canvas.load_entries.values()))
    assert entry.kind == "member_uniform"
    assert entry.payload.start_value == entry.payload.end_value == -3.0
    assert entry.payload.start_position == 0.0
    assert entry.payload.end_position == 1.0


def test_member_partial_load_keeps_its_own_start_and_end_position() -> None:
    page = _page()
    a = page.canvas.add_node(0.0, 0.0)
    b = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(a, b)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE")

    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("member_partial"))
    page.load3d_member_start_value.setValue(-1.0)
    page.load3d_member_end_value.setValue(-2.0)
    page.load3d_member_start_position.setValue(0.25)
    page.load3d_member_end_position.setValue(0.75)
    page.load3d_apply_button.click()

    entry = next(iter(page.canvas.load_entries.values()))
    assert (entry.payload.start_value, entry.payload.end_value) == (-1.0, -2.0)
    assert (entry.payload.start_position, entry.payload.end_position) == (0.25, 0.75)


def test_shared_operation_mode_also_controls_case_based_member_loads() -> None:
    page = _page()
    a = page.canvas.add_node(0.0, 0.0)
    b = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(a, b)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE")
    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("member_partial"))

    page.load3d_member_start_value.setValue(-1.0)
    page.load3d_apply_button.click()
    page.load3d_member_start_value.setValue(-2.0)
    page.load3d_apply_button.click()
    assert len(page.canvas.load_entries) == 1
    assert next(iter(page.canvas.load_entries.values())).payload.start_value == -2.0

    page.load_apply_mode_buttons["add"].setChecked(True)
    page.load3d_apply_button.click()
    assert len(page.canvas.load_entries) == 2

    page.load_apply_mode_buttons["delete"].setChecked(True)
    page.load3d_apply_button.click()
    assert page.canvas.load_entries == {}


def test_clicking_a_tree_leaf_shows_its_properties_in_selection_status() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)
    page._activate_load_tool()
    page.load3d_nodal_fields["fz"].setValue(-10.0)
    page.load3d_apply_button.click()
    entry_id = next(iter(page.canvas.load_entries))

    leaf = page._work_tree_case_items["LL_OFFICE"].child(0).child(0)
    page._on_work_tree_item_clicked(leaf, 0)

    assert page._selected_load_id == entry_id
    labels = [label.text() for label in page.selection_status_panel.findChildren(type(page.selection_summary))]
    assert any("NL-001" in text for text in labels)
    assert any("LL_OFFICE" in text for text in labels)


def test_edit_button_pre_fills_the_form_and_apply_updates_the_same_entry() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE")
    page._activate_load_tool()
    page.load3d_nodal_fields["fz"].setValue(-10.0)
    page.load3d_apply_button.click()
    entry_id = next(iter(page.canvas.load_entries))

    page._edit_load_entry(entry_id)

    assert page.load3d_nodal_fields["fz"].value() == -10.0
    assert page.load3d_apply_button.text() == "수정 적용"

    page.load3d_nodal_fields["fz"].setValue(-25.0)
    page.load3d_apply_button.click()

    assert len(page.canvas.load_entries) == 1  # updated in place, not duplicated
    assert page.canvas.load_entries[entry_id].payload.fz == -25.0
    assert page.load3d_apply_button.text() == "적용"


def test_delete_from_selection_status_removes_the_entry_and_the_tree_leaf() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE")
    page._activate_load_tool()
    page.load3d_apply_button.click()
    entry_id = next(iter(page.canvas.load_entries))
    page._show_selected_load(entry_id)

    page.selection_status_panel.load_delete_requested.emit(entry_id)

    assert page.canvas.load_entries == {}
    case_item = page._work_tree_case_items["LL_OFFICE"]
    assert case_item.childCount() == 0


def test_duplicate_context_menu_action_creates_a_second_entry_on_the_same_target() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE")
    page._activate_load_tool()
    page.load3d_apply_button.click()
    original_id = next(iter(page.canvas.load_entries))

    copy_id = page.canvas.duplicate_load_entry(original_id)

    assert copy_id is not None
    assert len(page.canvas.load_entries) == 2
    assert page.canvas.load_entries[copy_id].target == page.canvas.load_entries[original_id].target


def test_display_mode_combination_disables_the_apply_button() -> None:
    page = _page()
    page.canvas.add_load_combination("ULS-01")
    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("member_point"))

    combination_index = page.load_display_combo.findData("combination")
    page.load_display_combo.setCurrentIndex(combination_index)

    assert page.canvas.load_display_mode == "combination"
    assert page.load_readonly_hint.isVisible()
    assert not page.load3d_apply_button.isEnabled()


def test_combination_button_lives_in_the_left_panel_not_the_top_task_bar() -> None:
    """Relocated on user request: the Combination picker/manager button used
    to sit in the top load task bar next to Display. Management and active
    Load Case now live in the left editor; the canvas row is display-only."""
    page = _page()
    page._activate_load_tool()

    assert hasattr(page, "load_combination_combo")
    assert page.load_combination_combo.parentWidget() is not None
    # The top bar no longer owns a "조합 관리" button - only the left panel's
    # combination editor button does.
    from PySide6.QtWidgets import QComboBox, QPushButton

    assert not any(button.text() == "조합 관리" for button in page.findChildren(QPushButton))
    assert any(button.text() == "편집" for button in page.findChildren(QPushButton))
    assert page.load_case_combo not in page.load_task_bar.findChildren(QComboBox)


def test_loads_uses_one_command_picker_and_shows_only_the_selected_command_form() -> None:
    page = _page()
    page._activate_load_tool()

    assert page.load_command_combo.currentData() == "nodal"
    assert page.load_command_stack.currentIndex() == page.load_command_pages["quick"]
    assert page.load_command_form_title.text() == "Nodal Load"
    assert page.load_task_bar.isVisible()

    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("floor"))

    assert page.load_command_stack.currentIndex() == page.load_command_pages["entry"]
    assert page.load3d_form_stack.currentIndex() == page.load3d_form_pages["floor"]
    assert page.load3d_command_title.text() == "Floor Load"


def test_load_manager_uses_width_safe_comboboxes_instead_of_clipped_button_rows() -> None:
    page = _page()
    page._activate_load_tool()
    for key in (
        "self_weight",
        "nodal",
        "member_point",
        "member_uniform",
        "member_linear",
        "member_partial",
        "member_moment",
        "floor",
        "load_cases",
        "wind",
        "seismic",
        "load_combinations",
        "make_combination",
    ):
        page.load_command_combo.setCurrentIndex(page.load_command_combo.findData(key))
        assert page.category_stack.sizeHint().width() <= page.left_panel_stack.width() - 24

    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("member_partial"))
    assert page.load3d_member_subtype_combo.isVisible()


def test_switching_to_3d_quick_entry_does_not_leave_duplicate_form_labels_visible() -> None:
    from PySide6.QtWidgets import QLabel

    page = _page()
    page._activate_load_tool()
    visible_labels = [
        label.text()
        for label in page.category_stack.currentWidget().findChildren(QLabel)
        if label.isVisible()
    ]

    for component in ("Fx", "Fy", "Fz", "Mx", "My", "Mz"):
        assert sum(text.startswith(f"{component} (") for text in visible_labels) == 1


def test_properties_style_selector_keeps_load_command_hierarchy_in_each_label() -> None:
    """One MIDAS-style picker carries both hierarchy and command."""
    page = _page()
    commands = [
        (page.load_command_combo.itemData(i), page.load_command_combo.itemText(i))
        for i in range(page.load_command_combo.count())
        if page.load_command_combo.itemData(i) is not None
    ]

    assert commands == [
        ("load_cases", "[정의] 하중케이스"),
        ("self_weight", "[직접 하중] 자중"),
        ("nodal", "[직접 하중] 절점하중"),
        ("member_point", "[직접 하중] 부재 집중하중"),
        ("member_uniform", "[직접 하중] 부재 균등분포하중"),
        ("member_linear", "[직접 하중] 부재 선형분포하중"),
        ("member_partial", "[직접 하중] 부재 부분분포하중"),
        ("member_moment", "[직접 하중] 부재 집중모멘트"),
        ("floor", "[직접 하중] 바닥하중 할당"),
        ("wind", "[자동 생성] 풍하중"),
        ("seismic", "[자동 생성] 정적 지진하중"),
        ("load_combinations", "[하중 조합] 하중조합"),
        ("make_combination", "[하중 조합] 조합으로 케이스 생성"),
    ]


def test_make_load_case_by_combination_command_materializes_scaled_loads() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.add_load_case("DL", kind=LoadCaseKind.DEAD)
    page.canvas.add_load_entry("DL", "nodal", (node,), NodalLoadEntry(fz=-10.0))
    page.canvas.add_load_combination("ULS")
    page.canvas.update_load_combination("ULS", {LoadCaseKind.DEAD: 1.2})
    page.load_command_combo.setCurrentIndex(
        page.load_command_combo.findData("make_combination")
    )
    page.make_load_case_name.setText("ULS_APPLIED")

    page.make_load_create_button.click()

    generated = [
        entry for entry in page.canvas.load_entries.values() if entry.case_id == "ULS_APPLIED"
    ]
    assert len(generated) == 1
    assert generated[0].payload.fz == -12.0
    assert page.canvas.nodal_loads[node].values[2] == -12.0
    assert "하중 1개" in page.make_load_status.text()


def test_applying_a_floor_load_type_creates_one_entry_per_case_at_once() -> None:
    """MIDAS' "Floor Load Type" flow: pick a bundled type instead of typing
    one magnitude, Apply once, get one FloorLoadEntry per case in the type."""
    from openframe.core.domain import FloorLoadTypeRow

    page = _page()
    n1 = page.canvas.add_node(0.0, 0.0)
    n2 = page.canvas.add_node(4.0, 0.0)
    n3 = page.canvas.add_node(4.0, 4.0)
    page.canvas.add_load_case("DL_CONCRETE", kind=LoadCaseKind.DEAD)
    page.canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)
    page.canvas.add_floor_load_type(
        "사무실 바닥",
        rows=(
            FloorLoadTypeRow("DL_CONCRETE", 2.0),
            FloorLoadTypeRow("LL_OFFICE", 2.5),
        ),
    )
    page.canvas.selected_nodes = {n1, n2, n3}
    page.canvas.selection_changed.emit()
    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("floor"))

    type_index = page.load3d_floor_type_combo.findData("사무실 바닥")
    assert type_index >= 0
    page.load3d_floor_type_combo.setCurrentIndex(type_index)
    page.load3d_floor_type_apply_button.click()

    entries = list(page.canvas.load_entries.values())
    assert len(entries) == 2
    assert {entry.case_id for entry in entries} == {"DL_CONCRETE", "LL_OFFICE"}
    assert "2개" in page.load3d_status_label.text()


def test_saving_a_combination_in_the_dialog_populates_the_combo_and_work_tree() -> None:
    page = _page()
    page._activate_load_tool()

    dialog = LoadCombinationManagerDialog(page.canvas)
    dialog.panel.add_row("ULS-01", {LoadCaseKind.DEAD: 1.2, LoadCaseKind.LIVE: 1.6})
    dialog._save()

    assert "ULS-01" in page.canvas.load_combinations
    assert [page.load_combination_combo.itemText(i) for i in range(page.load_combination_combo.count())] == [
        "ULS-01"
    ]
    assert page.work_tree_load_combinations.childCount() == 1
    assert page.work_tree_load_combinations.child(0).text(0) == "ULS-01"
    assert page.work_tree_load_combinations.text(1) == "1"

    case_index = page.load_display_combo.findData("case")
    page.load_display_combo.setCurrentIndex(case_index)
    assert not page.load_readonly_hint.isVisible()
    assert page.load3d_apply_button.isEnabled()


def test_right_panel_shows_load_inspector_only_while_loads_tab_is_active() -> None:
    """Requirement: Work Tree/Selection Status stay as-is for every other
    workbench tab, and only swap for the Load Inspector while Loads is
    active - see _build_3d_selection_panel/_activate_workbench_tab."""
    page = _page()

    page._activate_workbench_tab("loads")
    assert page.right_panel_stack.currentIndex() == page.right_panel_pages["load_inspector"]

    page._activate_workbench_tab("node")
    assert page.right_panel_stack.currentIndex() == page.right_panel_pages["default"]

    page._activate_workbench_tab("loads")
    assert page.right_panel_stack.currentIndex() == page.right_panel_pages["load_inspector"]


def test_load_inspector_tree_selects_the_same_entry_as_the_work_tree() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)
    page._activate_load_tool()
    page.load3d_nodal_fields["fz"].setValue(-10.0)
    page.load3d_apply_button.click()
    entry_id = next(iter(page.canvas.load_entries))

    leaf = page._load_inspector_case_items["LL_OFFICE"].child(0).child(0)
    page._on_work_tree_item_clicked(leaf, 0)

    assert page._selected_load_id == entry_id
    labels = [
        label.text()
        for label in page.load_inspector_status_panel.findChildren(type(page.selection_summary))
    ]
    assert any("NL-001" in text for text in labels)


def test_load_inspector_context_menu_edit_lands_on_direct_loads_category() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE")
    page._activate_load_tool()
    page.load3d_apply_button.click()
    entry_id = next(iter(page.canvas.load_entries))

    page.load_command_combo.setCurrentIndex(
        page.load_command_combo.findData("load_combinations")
    )
    assert page.load_category_stack.currentIndex() == page.load_category_pages["combinations"]

    page._edit_load_entry(entry_id)

    assert page.load_command_combo.currentData() == "nodal"
    assert page.load_category_stack.currentIndex() == page.load_category_pages["direct"]


def test_generators_category_only_shows_placeholders() -> None:
    page = _page()
    page._activate_load_tool()

    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("wind"))
    assert page.load_category_stack.currentIndex() == page.load_category_pages["generators"]
    assert [
        page.load_generators_subnav_combo.itemText(i)
        for i in range(page.load_generators_subnav_combo.count())
    ] == ["Wind Load", "Static Seismic Load"]

    entries_before = dict(page.canvas.load_entries)
    page.load_generators_subnav_combo.setCurrentIndex(
        page.load_generators_subnav_combo.findData("seismic")
    )
    assert page.canvas.load_entries == entries_before


def test_definitions_and_combinations_categories_reach_existing_pages() -> None:
    page = _page()
    page._activate_load_tool()

    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("load_cases"))
    assert page.load_category_stack.currentIndex() == page.load_category_pages["definitions"]

    page.load_command_combo.setCurrentIndex(
        page.load_command_combo.findData("load_combinations")
    )
    assert page.load_category_stack.currentIndex() == page.load_category_pages["combinations"]
    assert page.load_combinations_stack.currentIndex() == page.load_combinations_pages["load_combinations"]

    page.load_combinations_subnav_combo.setCurrentIndex(
        page.load_combinations_subnav_combo.findData("make_combination")
    )
    assert page.load_combinations_stack.currentIndex() == page.load_combinations_pages["make_combination"]


def test_add_mode_sums_onto_the_existing_nodal_load() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE")
    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("nodal"))

    page.load_fields["fz"].setValue(-10.0)
    page.load_apply_button.click()
    assert page.canvas.nodal_loads[node].values[2] == -10.0

    page.load_apply_mode_buttons["add"].setChecked(True)
    page.load_fields["fz"].setValue(-5.0)
    page.load_apply_button.click()

    assert page.canvas.nodal_loads[node].values[2] == -15.0


def test_replace_mode_is_the_default_and_overwrites() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("nodal"))

    assert page.load_apply_mode_buttons["replace"].isChecked()
    page.load_fields["fz"].setValue(-10.0)
    page.load_apply_button.click()
    page.load_fields["fz"].setValue(-3.0)
    page.load_apply_button.click()

    assert page.canvas.nodal_loads[node].values[2] == -3.0


def test_delete_mode_clears_both_the_solver_load_and_its_tree_entry() -> None:
    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.canvas.add_load_case("LL_OFFICE")
    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("nodal"))
    page.load_fields["fz"].setValue(-10.0)
    page.load_apply_button.click()
    assert node in page.canvas.nodal_loads
    entries_before = len(page.canvas.load_entries)

    page.load_apply_mode_buttons["delete"].setChecked(True)
    assert not page.load_fields["fz"].isEnabled()
    page.load_apply_button.click()

    assert node not in page.canvas.nodal_loads
    assert entries_before == 1
    assert len(page.canvas.load_entries) == 0


def test_diagram_swaps_between_nodal_and_uniform_targets() -> None:
    page = _page()
    page._activate_load_tool()
    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("nodal"))
    nodal_pixmap = page.load_diagram_label.pixmap()
    assert nodal_pixmap is not None and not nodal_pixmap.isNull()

    page.load_command_combo.setCurrentIndex(page.load_command_combo.findData("member_uniform"))
    uniform_pixmap = page.load_diagram_label.pixmap()
    assert uniform_pixmap is not None and not uniform_pixmap.isNull()
    assert uniform_pixmap.toImage() != nodal_pixmap.toImage()


def test_load_case_name_label_tracks_the_active_case() -> None:
    page = _page()
    page.canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)
    page._activate_load_tool()

    assert page.load_case_combo.currentText() == "LL_OFFICE"
