import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from _solve_helpers import solve_and_wait
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame

from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page(*, start_in_3d: bool = False) -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=start_in_3d)
    page.resize(1280, 800)
    page.show()
    return page


def test_direct_2d_workspace_uses_the_compact_modeling_and_result_shell() -> None:
    page = _page()

    assert page.findChild(QFrame, "direct2DPageHeader") is not None
    # 선택/그리기 and the UNDO/REDO/DELETE/FIT commands used to live in a
    # dedicated 72px rail; that column is gone now that they sit on the
    # category bar above the canvas instead (see test_2d_editor_panel_and_
    # selection_panel_are_independent_fixed_width_columns for the panels
    # that replaced it).
    assert page.findChild(QFrame, "direct2DToolRail") is None
    assert page.select_tool is not None
    assert page.model_type_selector.count() == 2
    # 2D direct modeling shares the exact same RESULT TYPES sidebar as 3D direct
    # modeling and "OpenSeesPy 파일 불러오기" now - the compact-only variant was
    # too narrow for its own button labels (content wider than its own
    # viewport, silently clipped with no horizontal scroll to reveal it).
    assert set(page.results.result_types.buttons) == {
        "overview",
        "deformation",
        "displacement",
        "reaction",
        "axial",
        "shear",
        "moment",
        "pushover",
        "tables",
        "mode_shapes",
        "buckling_modes",
        "time_history",
    }
    assert page.results.property("compact2d") is False
    assert page.footer_stack.currentIndex() == 0
    assert page.page_title.text() == "2D Structure Model"
    assert page.header_controls_stack.currentIndex() == 0

    page.workspace_stack.setCurrentIndex(1)

    assert page.footer_stack.currentIndex() == 1
    assert page.page_title.text() == "2D Structure Results"
    assert page.header_controls_stack.currentIndex() == 1
    assert page.findChild(QFrame, "direct2DResultHeader") is None

    page.workspace_stack.setCurrentIndex(0)

    assert page.page_title.text() == "2D Structure Model"
    assert page.header_controls_stack.currentIndex() == 0


def test_2d_uses_the_same_workbench_navigation_as_3d() -> None:
    """2D shares the 3D shell while each tab keeps its own 2D page."""
    page = _page()
    assert page.findChild(QFrame, "direct2DCanvasToolbar") is None
    assert page.findChild(QFrame, "modelingWorkbenchBar") is not None
    assert page.entry_bar.isVisible()
    assert list(page.workbench_buttons) == [
        "model",
        "node",
        "properties",
        "element",
        "boundary",
        "loads",
        "analysis",
        "results",
    ]
    page.workbench_buttons["node"].click()
    assert page.category_stack.currentIndex() == page.category_pages["add"]
    assert page.node_subcategory_row.isVisible()
    assert page.left_panel_stack.isVisible()
    assert page.left_panel_stack.width() == 320

    page.workbench_buttons["properties"].click()
    assert page.category_stack.currentIndex() == page.category_pages["member"]

    page.workbench_buttons["element"].click()
    assert page.category_stack.currentIndex() == page.category_pages["element_picker"]
    assert page.element_subcategory_row.isVisible()
    assert page.canvas.mode == "draw"

    page.workbench_buttons["boundary"].click()
    assert page.category_stack.currentIndex() == page.category_pages["support"]
    assert page.selection_filter.currentData() == "nodes"

    page.workbench_buttons["loads"].click()
    assert page.category_stack.currentIndex() == page.category_pages["load"]
    assert hasattr(page, "load_target_group")
    assert not hasattr(page, "load_command_combo")

    page.workbench_buttons["analysis"].click()
    assert page.category_stack.currentIndex() == page.category_pages["analysis"]
    assert page.canvas.ndm == 2

    page.workbench_buttons["model"].click()
    assert page.left_panel_stack.isHidden()


def test_3d_workspace_hides_the_context_dock_until_a_tool_needs_it() -> None:
    page = _page(start_in_3d=True)

    assert page.findChild(QFrame, "modelingWorkbenchBar") is not None
    # Tab order mirrors the actual modeling workflow: geometry, then
    # material/section, then supports, then loads, then analysis/results.
    assert list(page.workbench_buttons) == [
        "model",
        "node",
        "properties",
        "element",
        "boundary",
        "loads",
        "analysis",
        "results",
    ]
    assert page.workbench_buttons["model"].isChecked()
    assert page.findChild(QFrame, "direct2DToolRail") is None
    assert page.findChild(QFrame, "direct2DCanvasToolbar") is None
    assert page.entry_bar.isHidden()
    assert not hasattr(page, "model_explorer_tree")
    assert not hasattr(page, "model_settings_summary_button")
    assert page.selection_status_panel is not None
    # 모델 탭에는 중복 탐색기를 두지 않는다. 왼쪽 설정창은 컨텍스트 도구를
    # 선택할 때만 열리고, 선택 전용 인스펙터는 항상 오른쪽에 남는다.
    assert page.left_panel_stack.isHidden()
    assert page.findChild(QFrame, "direct2DPageHeader").isHidden()
    assert page.model_settings_dialog.isVisible() is False


def test_3d_work_tabs_switch_the_left_editor_and_canvas_tool_together() -> None:
    """Each tab both shows its own form in the left dock and puts the canvas
    in whichever tool that step needs - there is no separate 선택/Member
    row to click first any more."""
    page = _page(start_in_3d=True)
    viewport = page.canvas_stack.currentWidget()

    page.workbench_buttons["node"].click()
    assert page.category_stack.currentIndex() == page.category_pages["add"]
    assert page.canvas.mode == "select"
    assert page.canvas_stack.currentWidget() is viewport

    page.workbench_buttons["properties"].click()
    assert page.category_stack.currentIndex() == page.category_pages["member"]
    assert page.left_panel_stack.currentIndex() == page.left_editor_index
    assert page.left_panel_stack.width() == 320
    assert page.canvas.mode == "select"
    assert page.canvas_stack.currentWidget() is viewport

    page.workbench_buttons["boundary"].click()
    assert page.category_stack.currentIndex() == page.category_pages["support"]
    assert page.canvas.mode == "select"
    assert page.selection_filter.currentData() == "nodes"
    assert page.canvas_stack.currentWidget() is viewport

    page.workbench_buttons["loads"].click()
    assert page.category_stack.currentIndex() == page.category_pages["load"]
    assert page.canvas.mode == "select"
    assert page.canvas_stack.currentWidget() is viewport

    page.workbench_buttons["model"].click()
    assert page.left_panel_stack.isHidden()
    assert page.model_settings_dialog.isVisible()
    assert page.canvas_stack.currentWidget() is viewport
    page.model_settings_dialog.reject()


def test_node_and_element_tabs_separate_node_tools_from_element_translation() -> None:
    """MIDAS-style: node creation stays under Node; member translation is
    discoverable from Element's own action picker."""
    page = _page(start_in_3d=True)

    page.workbench_buttons["properties"].click()
    assert page.node_subcategory_row.isVisible() is False

    page.workbench_buttons["node"].click()
    assert page.node_subcategory_row.isVisible() is True
    assert page.node_subcategory_combo.currentData() == "add"
    assert page.canvas.mode == "select"
    assert page.node_subcategory_combo.findData("move") == -1

    page.node_subcategory_combo.setCurrentIndex(
        page.node_subcategory_combo.findData("arch")
    )
    assert page.category_stack.currentIndex() == page.category_pages["arch"]
    assert page.canvas.mode == "select"

    page.node_subcategory_combo.setCurrentIndex(
        page.node_subcategory_combo.findData("kind")
    )
    assert page.category_stack.currentIndex() == page.category_pages["kind"]
    assert page.canvas.mode == "select"

    page.node_subcategory_combo.setCurrentIndex(
        page.node_subcategory_combo.findData("add")
    )
    assert page.category_stack.currentIndex() == page.category_pages["add"]
    assert page.canvas.mode == "select"

    page.workbench_buttons["element"].click()
    assert page.element_subcategory_row.isVisible() is True
    assert page.element_subcategory_combo.currentData() == "element_picker"
    assert page.canvas.mode == "select", "drawing stays locked until properties are applied"

    page.element_subcategory_combo.setCurrentIndex(
        page.element_subcategory_combo.findData("move")
    )
    assert page.category_stack.currentIndex() == page.category_pages["move"]
    assert page.selection_filter.currentData() == "elements"


def test_element_tab_applied_section_is_picked_up_by_the_next_drawn_member() -> None:
    """Element assigns saved definitions to members drawn afterwards."""
    page = _page(start_in_3d=True)
    first = page.canvas._add_node_at((0.0, 0.0, 0.0))
    second = page.canvas._add_node_at((4.0, 0.0, 0.0))

    panel = page.section_material_panel
    panel.shape_combo.setCurrentText("Rectangle")
    panel.source_custom.setChecked(True)
    panel._dimension_spinboxes["b"].setValue(0.3)
    panel._dimension_spinboxes["h"].setValue(0.5)
    panel.material_e.setValue(200_000.0)
    panel.material_unit_weight.setValue(24.0)
    panel.material_name.setText("Test Material")
    panel.section_name.setText("Test Section")
    panel.material_save_button.click()
    panel.section_save_button.click()

    page.workbench_buttons["element"].click()
    assert page.category_stack.currentIndex() == page.category_pages["element_picker"]
    page.element_material_selector.setCurrentIndex(
        page.element_material_selector.findData("MAT-001")
    )
    page.element_section_selector.setCurrentIndex(
        page.element_section_selector.findData("SEC-001")
    )

    assert page._active_element_kwargs is not None
    assert "Test Material" in page.active_element_status.text()
    assert "Test Section" in page.active_element_status.text()
    page.start_element_drawing_button.click()

    assert page.canvas.mode == "draw"
    page._on_3d_node_picked(first, 0, 0)
    page._on_3d_node_picked(second, 0, 0)

    member = next(iter(page.canvas.elements.values()))
    assert member.properties["E"] == pytest.approx(200_000.0)
    assert member.properties["A"] == pytest.approx(0.15)


def test_3d_element_drawing_is_blocked_until_material_and_section_are_applied() -> None:
    page = _page(start_in_3d=True)
    first = page.canvas._add_node_at((0.0, 0.0, 0.0))
    second = page.canvas._add_node_at((4.0, 0.0, 0.0))

    page._activate_draw_tool()
    page._on_3d_node_picked(first, 0, 0)
    page._on_3d_node_picked(second, 0, 0)

    assert page.canvas.mode == "select"
    assert page.canvas.elements == {}
    assert "물성·단면" in page.active_element_status.text()


def test_2d_element_can_optionally_apply_saved_properties_to_new_members() -> None:
    """The shared Element UI may enrich 2D drawing without making it mandatory."""
    page = _page(start_in_3d=False)
    panel = page.section_material_panel
    panel.shape_combo.setCurrentText("Rectangle")
    panel.source_custom.setChecked(True)
    panel._dimension_spinboxes["b"].setValue(0.25)
    panel._dimension_spinboxes["h"].setValue(0.4)
    panel.material_e.setValue(210_000.0)
    panel.material_name.setText("2D Test Material")
    panel.section_name.setText("2D Test Section")
    panel.material_save_button.click()
    panel.section_save_button.click()

    page.workbench_buttons["element"].click()
    page.element_material_selector.setCurrentIndex(
        page.element_material_selector.findData("MAT-001")
    )
    page.element_section_selector.setCurrentIndex(
        page.element_section_selector.findData("SEC-001")
    )

    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(first, second)

    assert member is not None
    assert page.canvas.elements[member].properties["E"] == pytest.approx(210_000.0)
    assert page.canvas.elements[member].properties["A"] == pytest.approx(0.1)


def test_3d_properties_can_reassign_material_and_section_to_selected_members() -> None:
    page = _page(start_in_3d=True)
    first = page.canvas._add_node_at((0.0, 0.0, 0.0))
    second = page.canvas._add_node_at((4.0, 0.0, 0.0))
    member = page.canvas.add_member(first, second)
    page.canvas.selected_elements = {member}
    page.canvas.selection_changed.emit()
    page.workbench_buttons["properties"].click()

    panel = page.section_material_panel
    panel.shape_combo.setCurrentText("Rectangle")
    panel.source_custom.setChecked(True)
    panel._dimension_spinboxes["b"].setValue(0.4)
    panel._dimension_spinboxes["h"].setValue(0.6)
    panel.material_e.setValue(205_000.0)
    panel.apply_button.click()

    changed = page.canvas.elements[member]
    assert changed.properties["E"] == pytest.approx(205_000.0)
    assert changed.properties["A"] == pytest.approx(0.24)


def test_switching_back_to_model_tab_opens_the_centered_model_settings_dialog() -> None:
    """Model settings are global and open as a focused dialog; assignment
    tools continue to use the left dock and never cover the selection pane."""
    page = _page(start_in_3d=True)

    page.workbench_buttons["properties"].click()
    page.workbench_buttons["model"].click()

    assert page.left_panel_stack.isHidden()
    assert page.model_settings_dialog.isVisible()
    assert 480 <= page.model_settings_dialog.width() <= 520
    page.model_settings_dialog.reject()


def test_3d_model_settings_apply_inside_the_workspace_and_round_trip() -> None:
    page = _page(start_in_3d=True)
    page.model_name_field.setText("Office Frame")
    page.force_unit_field.setCurrentText("N")
    page.length_unit_field.setCurrentText("mm")
    page.gravity_direction_field.setCurrentText("+Z")
    page.gravity_acceleration_field.setValue(9.8067)

    page._apply_model_settings_inline()

    assert page._model_name == "Office Frame"
    assert page._unit_system.force == "N"
    assert page._unit_system.length == "mm"
    assert page._gravity_direction == "+Z"
    assert page._gravity_acceleration == pytest.approx(-9.8067)
    assert "ops.model" in page.opensees_tcl_preview.text()
    data = page.to_project_dict()
    assert data["model_name"] == "Office Frame"
    assert data["gravity_direction"] == "+Z"
    assert data["gravity_acceleration"] == pytest.approx(-9.8067)

    restored = _page(start_in_3d=True)
    restored.load_project_dict(data)
    assert restored._model_name == "Office Frame"
    assert restored._unit_system.force == "N"
    assert restored._unit_system.length == "mm"
    assert restored._gravity_direction == "+Z"


def test_3d_property_editor_orders_material_before_section_and_properties() -> None:
    page = _page(start_in_3d=True)
    panel = page.section_material_panel

    assert panel._root_layout.indexOf(panel.material_group) == 0
    assert panel._root_layout.indexOf(panel.section_group) == 1
    assert panel._root_layout.indexOf(panel.properties_group) == 2
    assert panel.material_group.title_label.text() == "MATERIAL"
    assert panel.section_group.title_label.text() == "SECTION"
    assert panel.properties_group.title_label.text() == "SECTION PROPERTIES"
    # The "PROPERTIES" dropdown (see test_3d_properties_selector_switches_
    # which_card_is_shown below) defaults to its first item, MATERIAL, so
    # only that card's whole frame is shown - the other two are hidden
    # entirely, not just their body (a hidden body alone would still leave
    # an empty bordered card strip behind).
    assert panel.material_group.isHidden() is False
    assert panel.section_group.isHidden() is True
    assert panel.properties_group.isHidden() is True
    assert panel.apply_button.isHidden() is False


def test_3d_properties_selector_switches_which_card_is_shown() -> None:
    """The Properties tab replaces each MATERIAL/SECTION/SECTION PROPERTIES
    card's own clickable header with one "PROPERTIES" dropdown (same
    setupConfigBar/fieldLabel look as the Analysis tab's "ANALYSIS TYPE"
    bar) - selecting an item shows only that card's whole frame, hiding the
    other two outright (not just collapsing their body, which would leave
    an empty bordered strip for each). The 2D Properties tab now uses this
    same interaction and visual hierarchy."""
    page = _page(start_in_3d=True)
    panel = page.section_material_panel

    assert page.properties_selector.currentData() == "material"
    for group in (panel.material_group, panel.section_group, panel.properties_group):
        assert group._header.isHidden() is True

    page.properties_selector.setCurrentIndex(page.properties_selector.findData("section"))

    assert panel.material_group.isHidden() is True
    assert panel.section_group.isHidden() is False
    assert panel.properties_group.isHidden() is True

    page.properties_selector.setCurrentIndex(
        page.properties_selector.findData("section_properties")
    )

    assert panel.material_group.isHidden() is True
    assert panel.section_group.isHidden() is True
    assert panel.properties_group.isHidden() is False


def test_2d_properties_panel_uses_the_same_single_card_selector_as_3d() -> None:
    page = _page(start_in_3d=False)
    panel = page.section_material_panel

    assert page.properties_selector.currentData() == "material"
    for group in (panel.material_group, panel.section_group, panel.properties_group):
        assert group._header.isHidden()
    assert panel.material_group.isHidden() is False
    assert panel.section_group.isHidden()
    assert panel.properties_group.isHidden()


def test_3d_properties_tab_defines_and_applies_material_and_section() -> None:
    page = _page(start_in_3d=True)
    panel = page.section_material_panel

    # material_group is the only one of the three cards visible until the
    # PROPERTIES dropdown picks a different one (see test_3d_properties_
    # selector_switches_which_card_is_shown) - both material/section save
    # buttons still exist underneath regardless of which card currently shows.
    assert panel.material_group.isHidden() is False
    assert panel.material_save_button.isHidden() is False
    assert panel.section_save_button.isHidden() is False
    assert panel.apply_button.text() == "선택 부재에 물성·단면 적용"


def test_3d_element_create_requires_both_material_and_section() -> None:
    page = _page(start_in_3d=True)

    assert not hasattr(page, "element_section_material_panel")
    assert page.element_material_selector.count() == 1
    assert page.element_section_selector.count() == 1
    assert page.element_material_selector.currentData() is None
    assert page.element_section_selector.currentData() is None
    assert page.start_element_drawing_button.isEnabled() is False

    panel = page.section_material_panel
    panel.material_name.setText("SM355")
    panel.section_name.setText("H-400")
    panel.material_save_button.click()
    panel.section_save_button.click()

    assert page.element_material_selector.count() == 2
    assert page.element_section_selector.count() == 2
    page.element_material_selector.setCurrentIndex(1)
    assert page.start_element_drawing_button.isEnabled() is False
    page.element_section_selector.setCurrentIndex(1)
    assert page.start_element_drawing_button.isEnabled() is True


def test_saved_user_material_and_section_appear_in_the_work_tree_and_round_trip() -> None:
    page = _page(start_in_3d=True)
    material_panel = page.section_material_panel
    material_panel.material_name.setText("사용자 강재 SM355")
    material_panel.material_e.setValue(210_000_000.0)

    material_panel.material_save_button.click()

    assert page.work_tree_title.text() == "워크트리"
    assert page.work_tree_materials.childCount() == 1
    assert page.work_tree_materials.child(0).text(0) == "사용자 강재 SM355"
    assert page.work_tree_materials.child(0).text(1) == "MAT-001"

    section_panel = page.section_material_panel
    section_panel.section_name.setText("C1-기둥")
    section_panel.section_save_button.click()
    assert page.work_tree_sections.childCount() == 1
    assert page.work_tree_sections.child(0).text(0) == "C1-기둥"
    assert page.work_tree_sections.child(0).text(1) == "SEC-001"

    restored = _page(start_in_3d=True)
    restored.load_project_dict(page.to_project_dict())
    assert restored.work_tree_materials.childCount() == 1
    assert restored.work_tree_materials.child(0).text(0) == "사용자 강재 SM355"
    assert restored.work_tree_sections.childCount() == 1
    assert restored.work_tree_sections.child(0).text(0) == "C1-기둥"
    assert restored.element_material_selector.itemData(1) == "MAT-001"
    assert restored.element_section_selector.itemData(1) == "SEC-001"


def test_member_group_counts_are_derived_from_true_3d_geometry() -> None:
    page = _page(start_in_3d=True)

    base = page.canvas._add_node_at((0.0, 0.0, 0.0))
    top = page.canvas._add_node_at((0.0, 0.0, 3.0))
    page.canvas.add_member(base, top)
    far = page.canvas._add_node_at((4.0, 0.0, 3.0))
    page.canvas.add_member(top, far)

    counts = page._member_group_counts()
    assert counts == {"Columns": 1, "Beams": 1}


def test_member_info_card_shows_start_end_length_and_group_for_one_selected_member() -> None:
    page = _page(start_in_3d=True)
    base = page.canvas._add_node_at((0.0, 0.0, 0.0))
    top = page.canvas._add_node_at((0.0, 0.0, 3.0))
    column = page.canvas.add_member(base, top)

    assert page.member_info_card.isVisible() is False

    page.canvas.selected_elements = {column}
    page.canvas.selection_changed.emit()

    assert page.member_info_card.isVisible() is True
    assert page.member_start_node_label.text() == f"N{base}"
    assert page.member_end_node_label.text() == f"N{top}"
    assert page.member_length_label.text() == "3.000 m"
    assert page.member_group_label.text() == "Columns"

    page.canvas.selected_elements.clear()
    page.canvas.selection_changed.emit()
    assert page.member_info_card.isVisible() is False


def test_the_right_panel_starts_empty_until_a_category_is_picked() -> None:
    """Nothing is pinned any more: 노드 추가/이동·복사·배열/노드 분할 used to
    always occupy the 우측 패널, and 지점/노드 유형/부재/하중 lived in a
    canvas-top accordion. Now all seven are equal category pages and the
    panel shows none of them until a category button is clicked."""
    page = _page()

    assert page.category_stack.currentIndex() == page.category_pages["empty"]
    assert page.node_xy.isVisible() is False
    assert "선택된 대상이 없습니다" in page.selection_summary.text()
    assert {key for key, _label in page._CATEGORY_OPTIONS} == set(page.category_buttons)


def test_clicking_a_category_button_shows_only_that_pages_content() -> None:
    page = _page()

    page.category_buttons["add"].click()
    assert page.category_stack.currentIndex() == page.category_pages["add"]
    assert page.node_xy.isVisible() is True

    page.category_buttons["move"].click()
    assert page.category_stack.currentIndex() == page.category_pages["move"]
    assert page.node_transform_operation.isVisible() is True
    # Switching category is exclusive - the previous one's page stops being
    # the one shown (QStackedWidget only ever shows its current widget).
    assert page.category_stack.currentIndex() != page.category_pages["add"]


def test_category_stays_open_until_a_different_one_is_clicked() -> None:
    """Re-clicking the already-active category button must not close it -
    an exclusive QButtonGroup never lets the last checked button un-check
    itself, so the panel simply has nothing that "closes" it back to empty."""
    page = _page()
    page.category_buttons["add"].click()

    page.category_buttons["add"].click()

    assert page.category_stack.currentIndex() == page.category_pages["add"]
    assert page.node_xy.isVisible() is True


def test_arch_category_button_generates_an_arch_from_typed_span_and_rise() -> None:
    page = _page()
    page.category_buttons["arch"].click()

    page.arch_start_x.setValue(0.0)
    page.arch_start_y.setValue(0.0)
    page.arch_span.setValue(8.0)
    page.arch_rise.setValue(1.6)
    page.arch_segments.setValue(12)
    page._generate_arch()

    assert len(page.canvas.nodes) == 13
    assert len(page.canvas.elements) == 12
    assert page.canvas.selected_nodes  # ready to immediately add supports at the ends


def test_generated_arch_members_take_a_support_and_a_uniform_load_like_any_other_member() -> None:
    """The whole point of building an arch out of ordinary straight
    Nodes/Elements is that 지점 and 하중 need no arch-specific code at all -
    this is the end-to-end proof, not just a unit check on the geometry."""
    page = _page()
    page.category_buttons["arch"].click()
    page.arch_span.setValue(8.0)
    page.arch_rise.setValue(1.6)
    page.arch_segments.setValue(4)
    page._generate_arch()
    left_foot, *_middle, right_foot = sorted(page.canvas.nodes)
    first_member = next(iter(page.canvas.elements))

    page.category_buttons["support"].click()
    page.canvas.selected_nodes = {left_foot, right_foot}
    page.canvas.selection_changed.emit()
    page.support_buttons[4].click()  # 고정

    page.category_buttons["load"].click()
    page.canvas.selected_nodes = set()
    page.canvas.selected_elements = {first_member}
    page.canvas.selection_changed.emit()
    page.load_target_group.button(1).click()  # 등분포하중 (element)
    page.load_coordinate_system.setCurrentIndex(
        page.load_coordinate_system.findData("local")
    )
    page.load_fields["qy"].setValue(-5.0)
    page._apply_load()

    model = page.canvas.build_model()
    boundaries_by_node = {boundary.node_tag: boundary for boundary in model.boundaries}
    assert boundaries_by_node[left_foot].restraints == (True, True, True)
    assert boundaries_by_node[right_foot].restraints == (True, True, True)
    element_loads_by_tag = {load.element_tag: load for load in model.element_loads}
    assert element_loads_by_tag[first_member].wy == pytest.approx(-5.0)


def test_distributed_load_defaults_to_global_axes_and_converts_a_vertical_member() -> None:
    page = _page()
    canvas = page.canvas
    top = canvas.add_node(0.0, 4.0)
    bottom = canvas.add_node(0.0, 0.0)
    member = canvas.add_member(top, bottom)  # local +x points downward
    canvas.selected_elements = {member}
    canvas.selection_changed.emit()

    page.category_buttons["load"].click()
    page.load_target_group.button(1).click()  # uniform member load

    assert page.load_coordinate_system.currentData() == "global"
    assert page.load_coordinate_row.isVisible()
    assert page.load_form_layout.labelForField(page.load_fields["qx"]).text().startswith(
        "qX"
    )
    assert page.load_form_layout.labelForField(page.load_fields["qy"]).text().startswith(
        "qY"
    )

    page.load_fields["qx"].setValue(5.0)  # global +X, not member-local +x
    page._apply_load()

    load = canvas.element_loads[member]
    assert load.wx == pytest.approx(0.0)
    assert load.wy == pytest.approx(5.0)
    segments = canvas.load_arrow_segments(
        canvas.nodes[top], canvas.nodes[bottom], load, reach=1.0
    )
    tail, tip, _label = segments[0]
    assert (tip[0] - tail[0], tip[1] - tail[1]) == pytest.approx((1.0, 0.0))


def test_one_global_distributed_load_is_converted_per_selected_member() -> None:
    page = _page()
    canvas = page.canvas
    origin = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    top = canvas.add_node(8.0, 4.0)
    bottom = canvas.add_node(8.0, 0.0)
    horizontal = canvas.add_member(origin, right)
    vertical_down = canvas.add_member(top, bottom)
    canvas.selected_elements = {horizontal, vertical_down}

    canvas.apply_uniform_load_to_selection(
        (10.0, -4.0), coordinate_system="global"
    )

    horizontal_load = canvas.element_loads[horizontal]
    vertical_load = canvas.element_loads[vertical_down]
    assert (horizontal_load.wx, horizontal_load.wy) == pytest.approx((10.0, -4.0))
    assert (vertical_load.wx, vertical_load.wy) == pytest.approx((4.0, 10.0))


def test_global_trapezoidal_load_converts_both_member_ends() -> None:
    page = _page()
    canvas = page.canvas
    top = canvas.add_node(0.0, 4.0)
    bottom = canvas.add_node(0.0, 0.0)
    member = canvas.add_member(top, bottom)
    canvas.selected_elements = {member}

    canvas.apply_uniform_load_to_selection(
        (2.0, 0.0, 6.0, 0.0), coordinate_system="global"
    )

    load = canvas.element_loads[member]
    assert (load.wx, load.wy, load.wx_j, load.wy_j) == pytest.approx(
        (0.0, 2.0, 0.0, 6.0)
    )


def test_local_distributed_load_mode_preserves_the_existing_member_axis_input() -> None:
    page = _page()
    canvas = page.canvas
    top = canvas.add_node(0.0, 4.0)
    bottom = canvas.add_node(0.0, 0.0)
    member = canvas.add_member(top, bottom)
    canvas.selected_elements = {member}
    canvas.selection_changed.emit()
    page.category_buttons["load"].click()
    page.load_target_group.button(1).click()
    page.load_coordinate_system.setCurrentIndex(
        page.load_coordinate_system.findData("local")
    )

    assert page.load_form_layout.labelForField(page.load_fields["qx"]).text().startswith(
        "qx"
    )
    page.load_fields["qx"].setValue(5.0)
    page._apply_load()

    load = canvas.element_loads[member]
    assert (load.wx, load.wy) == pytest.approx((5.0, 0.0))


def test_create_section_stays_visible_across_selection_changes() -> None:
    """The relative-offset workflow needs the fields to stay reachable right
    after picking the reference node - create must never disappear just
    because a selection was made, which is the bug this guards against."""
    page = _page()
    page.category_buttons["add"].click()
    node = page.canvas.add_node(0.0, 0.0)

    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    assert page.node_xy.isVisible() is True


def test_selecting_a_node_does_not_switch_the_active_category() -> None:
    """Selecting a node used to swap the right panel to node-only properties;
    selection now only ever refreshes whichever category is already showing
    (the selection summary text included) - it never picks a category on
    its own."""
    page = _page()
    page.category_buttons["move"].click()
    node = page.canvas.add_node(0.0, 0.0)

    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    assert "노드 1개 선택됨" in page.selection_summary.text()
    assert page.category_stack.currentIndex() == page.category_pages["move"]
    assert page.node_transform_operation.isVisible() is True


def test_activating_a_tool_shows_its_own_category_and_switches_off_the_others() -> None:
    """지점/하중 등은 하나의 예외적 QButtonGroup으로 배타적으로 전환된다: 하나를
    켜면 이전에 켜져 있던 다른 카테고리는 자동으로 꺼진다."""
    page = _page()

    page._activate_support_tool()
    assert page.category_buttons["support"].isChecked() is True
    assert page.category_stack.currentIndex() == page.category_pages["support"]

    page._activate_load_tool()
    assert page.category_buttons["load"].isChecked() is True
    assert page.category_buttons["support"].isChecked() is False
    assert page.category_stack.currentIndex() == page.category_pages["load"]


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


def test_the_node_transform_tool_leaves_the_selection_filter_alone() -> None:
    """이동·복사·배열 now understands a selected *member* too (its endpoints move
    or copy along with it, matching MIDAS's separate Node/Element move-copy
    mode) - unlike the load/support tools, activating it from the rail must
    not narrow the filter, or picking "부재만" would be undone immediately."""
    page = _page()

    page._activate_node_transform_tool()
    assert page.selection_filter.currentData() == "all"


def test_switching_away_from_support_category_widens_a_narrowed_filter() -> None:
    """지점 (rail button) narrows the selection filter to "노드만" so picking a
    node to support is easier. Without a reliable "leave 지점" step, that
    narrowed filter used to survive into every category opened afterward -
    the 이동·복사 category bar button, for instance, never touched the filter
    itself, so a member click there was silently ignored with no visible
    reason why. ``_show_category`` is the one choke point every category
    switch passes through (rail buttons and the category bar alike), so it
    is where the filter gets widened back - except when 지점's own page is
    what is being shown, since that would immediately undo the narrowing
    ``_activate_support_tool`` just set."""
    page = _page()
    page._activate_support_tool()
    assert page.selection_filter.currentData() == "nodes"

    page._show_category("move")

    assert page.selection_filter.currentData() == "all"


def test_showing_the_support_category_again_does_not_disturb_its_own_filter() -> None:
    page = _page()
    page._activate_support_tool()
    assert page.selection_filter.currentData() == "nodes"

    page._show_category("support")

    assert page.selection_filter.currentData() == "nodes"


def test_clicking_the_category_bars_own_support_button_narrows_the_filter_too() -> None:
    """The rail's dedicated 지점 shortcut (``_activate_support_tool``) is gone
    - the category bar's own 지점 button is now the only way in, so it must
    still narrow the filter to 노드만 and switch back to the select tool,
    not just flip the category page the plain ``_show_category`` way."""
    page = _page()

    page.category_buttons["support"].click()

    assert page.selection_filter.currentData() == "nodes"
    assert page.select_tool.isChecked() is True
    assert page.category_stack.currentIndex() == page.category_pages["support"]


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
    page.load_mode_toggle.setChecked(True)

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
    page.load_mode_toggle.setChecked(True)
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

    # No selected member and no selected node -> nothing to reference, leaves
    # whatever angle was already there.
    canvas.selected_elements = set()
    canvas.selected_nodes = set()
    page._fill_angle_perpendicular_to_selected_member()
    assert page.load_angle.value() == pytest.approx(135.0)


def test_perpendicular_button_auto_detects_the_member_from_a_lone_load_target_node() -> None:
    """The common case - a load at the end of a sloped member with only one
    member there (a rafter end, a cantilever tip, a truss apex) - must not
    require holding Ctrl and clicking the member too just to pick an
    unambiguous reference: selecting only the load-target node is enough."""
    page = _page()
    page.load_mode_toggle.setChecked(True)
    canvas = page.canvas
    sloped_a = canvas.add_node(0.0, 4.0)
    sloped_b = canvas.add_node(4.0, 8.0)  # 45 degrees
    canvas.add_member(sloped_a, sloped_b)

    canvas.selected_nodes = {sloped_a}
    canvas.selected_elements = set()
    page._fill_angle_perpendicular_to_selected_member()
    assert page.load_angle.value() == pytest.approx(135.0)


def test_perpendicular_button_warns_when_the_load_target_node_has_two_members() -> None:
    """A rigid-frame joint with two or more members at the load-target node
    is genuinely ambiguous - perpendicular to which one? - so the button
    must say so instead of guessing or silently doing nothing."""
    page = _page()
    page.load_mode_toggle.setChecked(True)
    canvas = page.canvas
    corner = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    up = canvas.add_node(0.0, 4.0)
    canvas.add_member(corner, right)
    canvas.add_member(corner, up)

    canvas.selected_nodes = {corner}
    canvas.selected_elements = set()
    page.load_angle.setValue(7.0)
    page._fill_angle_perpendicular_to_selected_member()

    assert page.load_angle.value() == pytest.approx(7.0)
    assert "기준 부재를 정할 수 없습니다" in page.selection_summary.text()


def test_perpendicular_button_auto_detects_at_a_node_splitting_a_straight_member() -> None:
    """부재 노드 삽입 (splitting a drawn member partway along its span - see
    ``add_member_station_node``) leaves two members at the new node, but
    both halves sit on the exact same line, so this is not the ambiguous
    two-member case: perpendicular-to-either gives the same angle."""
    page = _page()
    page.load_mode_toggle.setChecked(True)
    canvas = page.canvas
    bottom = canvas.add_node(0.0, 0.0)
    top = canvas.add_node(4.0, 4.0)  # 45 degrees
    member = canvas.add_member(bottom, top)
    split_node = canvas.add_member_station_node(member, 0.5)

    canvas.selected_nodes = {split_node}
    canvas.selected_elements = set()
    page._fill_angle_perpendicular_to_selected_member()

    assert page.load_angle.value() == pytest.approx(135.0)
    assert "기준 부재를 정할 수 없습니다" not in page.selection_summary.text()


def test_node_loads_default_to_component_fx_fy_input() -> None:
    """Fx/Fy is the default 집중하중 input, same as every other axis field in
    this app - '부재 수직' (크기+자동 각도) is opt-in via the toggle, for
    loads naturally given relative to a sloped member instead."""
    page = _page()
    page.category_buttons["load"].click()

    assert page.load_input_mode == "component"
    assert set(page.load_fields) == {"fx", "fy", "mz"}
    assert not hasattr(page, "load_magnitude")
    assert not hasattr(page, "load_angle")
    assert page.load_mode_toggle.isVisible()
    visible_widgets = {
        page.load_form_layout.itemAt(i).widget() for i in range(page.load_form_layout.count())
    }
    assert page.load_fields["fx"] in visible_widgets
    assert page.load_fields["fy"] in visible_widgets


def test_toggling_to_perpendicular_mode_hides_fx_fy() -> None:
    page = _page()

    page.load_mode_toggle.setChecked(True)

    assert page.load_input_mode == "perpendicular"
    visible_widgets = {
        page.load_form_layout.itemAt(i).widget() for i in range(page.load_form_layout.count())
    }
    assert page.load_fields["fx"] not in visible_widgets
    assert page.load_fields["fy"] not in visible_widgets
    assert page.load_magnitude in visible_widgets
    assert page.load_angle in visible_widgets


def test_selecting_a_node_silently_follows_it_with_the_perpendicular_angle() -> None:
    """The angle used to require an explicit button press per selection -
    now it just follows whichever node/member is selected, with no ⚠
    warning noise for an ordinary click that doesn't land on a reference."""
    page = _page()
    page.load_mode_toggle.setChecked(True)
    canvas = page.canvas
    a = canvas.add_node(0.0, 0.0)
    b = canvas.add_node(4.0, 4.0)  # 45 degrees
    canvas.add_member(a, b)

    canvas.selected_nodes = {b}
    canvas.selection_changed.emit()
    assert page.load_angle.value() == pytest.approx(135.0)
    assert "⚠" not in page.selection_summary.text()

    # Selecting something with no usable reference must not warn either -
    # only the explicit "각도 재계산" path does that.
    canvas.selected_nodes = set()
    canvas.selection_changed.emit()
    assert "⚠" not in page.selection_summary.text()


def test_perpendicular_load_end_to_end_stores_and_previews_the_resultant() -> None:
    """크기 + auto-angle -> 적용 must store the same Fx/Fy the old
    magnitude/angle calculator computed, and preview it live beforehand."""
    page = _page()
    page.load_mode_toggle.setChecked(True)
    canvas = page.canvas
    a = canvas.add_node(0.0, 4.0)
    b = canvas.add_node(4.0, 8.0)  # 45 degrees
    canvas.add_member(a, b)

    canvas.selected_nodes = {a}
    canvas.selection_changed.emit()
    assert page.load_angle.value() == pytest.approx(135.0)

    page.load_magnitude.setValue(10.0)
    expected_fx = 10.0 * math.cos(math.radians(135.0))
    expected_fy = 10.0 * math.sin(math.radians(135.0))
    assert page.load_fields["fx"].value() == pytest.approx(expected_fx)
    assert page.load_fields["fy"].value() == pytest.approx(expected_fy)
    assert canvas._pending_load_preview == ({a}, pytest.approx((expected_fx, expected_fy, 0.0)))

    page._apply_load()
    assert canvas.nodal_loads[a].values == pytest.approx((expected_fx, expected_fy, 0.0))


def test_applying_a_node_load_with_nothing_selected_warns_instead_of_silently_doing_nothing() -> None:
    """A plain click on a member (no Ctrl) clears an already-selected node -
    see ``_toggle_selection`` - so it is easy to reach 적용 with no node
    selected after using 선택 부재에 수직. That used to no-op with zero
    feedback, which reads as "the button is broken"."""
    page = _page()
    page.load_fields["fx"].setValue(5.0)

    page._apply_load()

    assert not page.canvas.build_model().nodal_loads
    assert "선택된 노드가 없어" in page.selection_summary.text()


def test_applying_a_member_section_with_nothing_selected_warns_instead_of_silently_doing_nothing() -> None:
    """apply_section_to_selection no-ops with nothing selected (see its own
    docstring) - the same "reads as broken" trap _apply_load already guards
    against, now closed for 선택 부재에 적용 too."""
    page = _page()

    page._apply_member_section()

    assert "선택된 부재가 없어" in page.selection_summary.text()


def test_applying_a_member_section_confirms_how_many_members_it_reached() -> None:
    page = _page()
    canvas = page.canvas
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.selected_elements = {member}
    canvas.selection_changed.emit()

    panel = page.section_material_panel
    panel._dimension_spinboxes["b"].setValue(0.3)
    panel._dimension_spinboxes["h"].setValue(0.5)
    panel.material_e.setValue(200_000.0)
    panel.material_unit_weight.setValue(24.0)
    page._apply_member_section()

    element = canvas.elements[member]
    assert element.properties["E"] == pytest.approx(200_000.0)
    assert element.properties["A"] == pytest.approx(0.15)
    assert element.properties["density"] == pytest.approx(24.0)
    assert "부재 1개" in page.selection_summary.text()
    assert "적용했습니다" in page.selection_summary.text()


def test_load_fields_gain_fz_mx_my_once_3d_mode_is_active() -> None:
    page = _page()
    assert set(page.load_fields) == {"fx", "fy", "mz"}

    page_3d = _page(start_in_3d=True)

    assert set(page_3d.load_fields) == {"fx", "fy", "fz", "mx", "my", "mz"}


def test_custom_support_lets_a_single_dof_be_restrained_on_its_own() -> None:
    """None of the five presets can restrain rotation alone; the custom option
    has to reach every combination, not just the common ones."""
    page = _page()
    page.category_buttons["support"].click()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_buttons[5].click()  # 커스텀
    assert page.support_custom_row.isVisible() is True
    page.support_dof_checks["Rz"].setChecked(True)

    boundary = page.canvas.build_model().boundaries[0]
    assert boundary.restraints == (False, False, True)


def test_rotate_support_angle_buttons_step_30_degrees_and_apply() -> None:
    """A button click never fires editingFinished on its own the way typing
    into the field and tabbing away does, so the rotate buttons must apply
    the new angle themselves rather than silently changing the field."""
    page = _page()
    page.category_buttons["support"].click()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()
    page.support_buttons[1].click()  # 핀

    page._rotate_support_angle(30.0)
    assert page.support_angle.value() == pytest.approx(30.0)
    assert page.canvas.boundaries[node].angle == pytest.approx(30.0)

    page._rotate_support_angle(-30.0)
    assert page.support_angle.value() == pytest.approx(0.0)
    assert page.canvas.boundaries[node].angle == pytest.approx(0.0)

    # Wraps around both ends of the range instead of clamping dead at ±360,
    # which would make the button stop doing anything near the boundary.
    page._rotate_support_angle(-30.0)
    assert page.support_angle.value() == pytest.approx(330.0)
    assert page.canvas.boundaries[node].angle == pytest.approx(330.0)


def test_custom_support_reaches_all_six_dof_in_3d() -> None:
    page = _page(start_in_3d=True)
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.support_buttons[6].click()  # 커스텀 (3D: 자유/핀/고정/X·Y·Z롤러/커스텀)
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
    page.node_xy.setText("2, -1")
    page.node_repeat.setValue(1)
    page._add_nodes_from_coordinates()

    model = page.canvas.build_model()
    new_node = next(node for tag, node in model.nodes.items() if tag != anchor)
    assert (new_node.x, new_node.y) == pytest.approx((5.0, 3.0))


def test_relative_node_entry_falls_back_to_the_origin_without_a_single_selection() -> None:
    page = _page()
    page.node_relative.setChecked(True)
    page.node_xy.setText("2, -1")
    page.node_repeat.setValue(1)
    page._add_nodes_from_coordinates()

    model = page.canvas.build_model()
    (node,) = model.nodes.values()
    assert (node.x, node.y) == pytest.approx((2.0, -1.0))


@pytest.mark.parametrize("text", ["1, 2", "1,2", "1 2", "(1, 2)", "(1,2)", "  1 , 2  "])
def test_coordinate_field_accepts_midas_style_formats(text: str) -> None:
    page = _page()
    page.node_xy.setText(text)
    page.node_repeat.setValue(1)
    page._add_nodes_from_coordinates()

    (node,) = page.canvas.build_model().nodes.values()
    assert (node.x, node.y) == pytest.approx((1.0, 2.0))


def test_coordinate_field_rejects_malformed_input_without_adding_a_node() -> None:
    page = _page()
    page.category_buttons["add"].click()
    page.node_xy.setText("1, 2, 3")

    page._add_nodes_from_coordinates()

    assert not page.canvas.build_model().nodes
    assert "형식" in page.create_section_hint.text()


@pytest.mark.parametrize(
    "text",
    ["0 0 10", "0, 0, 10", "0,0,10", "(0, 0, 10)", "[0 0 10]"],
)
def test_3d_coordinate_field_accepts_combined_xyz_formats(text: str) -> None:
    page = _page(start_in_3d=True)
    page.node_xyz.setText(text)
    page.node_repeat.setValue(1)

    page._add_nodes_from_coordinates()

    (node,) = page.canvas.build_model().nodes.values()
    assert (node.x, node.y, node.z) == pytest.approx((0.0, 0.0, 10.0))


def test_3d_coordinate_field_rejects_a_separate_xy_only_value() -> None:
    page = _page(start_in_3d=True)
    page.node_xyz.setText("0, 10")

    page._add_nodes_from_coordinates()

    assert not page.canvas.build_model().nodes
    assert "X, Y, Z" in page.create_section_hint.text()


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
    """부재력 표: for a truss, the Result Tables member-force sheet must read as a
    부재 번호 / 절점 (i-j) / 축력 / 인장·압축·0부재 sheet — not the frame table's
    N/V/M-i-j columns, since V and M are always zero and say nothing about a
    two-force member."""
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
    table = page.results.tables_panel.member_force_truss_table

    assert [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())] == [
        "부재",
        "절점 (i-j)",
        f"축력 N ({page._unit_system.force})",
        "상태",
        f"σ ({page._unit_system.stress})",
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
