import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from _solve_helpers import solve_and_wait
from PySide6.QtCore import QObject, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from openframe.features.model.drawing import PlaneKind, WorkPlane
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.set_mode("draw")
    return canvas


def _page(*, start_in_3d: bool = False) -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=start_in_3d)
    page.resize(1400, 900)
    page.show()
    return page


def _enable_element_drawing(page: ModelingInterfacePage) -> None:
    """Save Properties definitions, then select them for Create Element."""
    panel = page.section_material_panel
    panel.material_name.setText("Default Material")
    panel.section_name.setText("Default Section")
    panel.material_save_button.click()
    panel.section_save_button.click()
    page.element_material_selector.setCurrentIndex(
        page.element_material_selector.findData("MAT-001")
    )
    page.element_section_selector.setCurrentIndex(
        page.element_section_selector.findData("SEC-001")
    )
    page.start_element_drawing_button.click()
    assert page._active_element_kwargs is not None
    assert page.canvas.mode == "draw"


def test_entering_3d_mode_does_not_disturb_geometry_already_drawn_in_2d() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 0.0)
    canvas.end_chain()

    canvas.enter_3d_mode()

    assert canvas.ndm == 3
    assert [(n.x, n.y, n.z) for n in canvas.nodes.values()] == pytest.approx(
        [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    )


def test_a_new_level_places_drawn_nodes_at_its_elevation() -> None:
    canvas = _canvas()
    canvas.enter_3d_mode()
    second_floor = canvas.add_level(3.5, "2F")
    canvas.set_active_plane(second_floor)

    canvas.place_point(2.0, 1.0)

    node = next(iter(canvas.nodes.values()))
    assert (node.x, node.y, node.z) == pytest.approx((2.0, 1.0, 3.5))


def test_nodes_on_another_level_are_invisible_to_the_active_plan() -> None:
    """What you cannot see, you cannot accidentally select or snap onto."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    ground = canvas.place_point(0.0, 0.0)
    second_floor = canvas.add_level(3.5, "2F")
    canvas.set_active_plane(second_floor)
    canvas.place_point(0.0, 0.0)  # same (x, y) as ground, different level

    canvas.select_all()

    assert ground not in canvas.selected_nodes
    assert canvas._plane_node_tags() == canvas.selected_nodes


def test_extruding_a_column_connects_a_plan_node_to_the_next_level() -> None:
    canvas = _canvas()
    canvas.enter_3d_mode()
    base = canvas.place_point(0.0, 0.0)
    second_floor = canvas.add_level(3.5, "2F")
    canvas.selected_nodes = {base}

    created = canvas.extrude_selection_to_plane(second_floor)

    assert created == 1
    assert len(canvas.elements) == 1
    element = next(iter(canvas.elements.values()))
    top = canvas.nodes[element.node_j if element.node_i == base else element.node_i]
    assert (top.x, top.y, top.z) == pytest.approx((0.0, 0.0, 3.5))


def test_extruding_onto_an_existing_node_reuses_it_instead_of_duplicating() -> None:
    canvas = _canvas()
    canvas.enter_3d_mode()
    base = canvas.place_point(1.0, 2.0)
    second_floor = canvas.add_level(3.0, "2F")
    canvas.set_active_plane(second_floor)
    existing_top = canvas.place_point(1.0, 2.0)
    canvas.set_active_plane(WorkPlane())
    canvas.selected_nodes = {base}

    canvas.extrude_selection_to_plane(second_floor)

    assert len(canvas.nodes) == 2
    element = next(iter(canvas.elements.values()))
    assert {element.node_i, element.node_j} == {base, existing_top}


def test_mirroring_on_a_vertical_elevation_plane_reflects_along_its_local_axis() -> None:
    """axis="y" on an XZ elevation plane must move Z, not global Y."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    front = canvas.add_level(0.0, "front", kind=PlaneKind.XZ)
    canvas.set_active_plane(front)
    low = canvas.place_point(1.0, 0.0)
    mid = canvas.place_point(1.0, 2.0)
    canvas.end_chain()
    canvas.selected_nodes = {low, mid}

    canvas.mirror_selection("y", 3.0)

    xs = {round(node.x, 9) for node in canvas.nodes.values()}
    ys = {round(node.y, 9) for node in canvas.nodes.values()}
    zs = sorted(round(node.z, 9) for node in canvas.nodes.values())
    assert xs == {1.0}
    assert ys == {0.0}, "an elevation plane's mirror must never touch global Y"
    assert zs == [0.0, 2.0, 4.0, 6.0]


def test_a_node_dropped_mid_height_on_a_column_splits_it_in_true_3d() -> None:
    """Colinearity is a real 3D fact — it must hold on an elevation view too.
    A brand-new node landing exactly on an existing member now splits it into
    two independent elements (see canvas_geometry.py's _add_node_at) rather
    than only marking an embedded pass-through point, so each half can carry
    its own load - this must work identically off the ground plane."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    base = canvas.place_point(0.0, 0.0)
    roof = canvas.add_level(6.0, "roof")
    canvas.selected_nodes = {base}
    canvas.extrude_selection_to_plane(roof)
    top = next(node.tag for node in canvas.nodes.values() if node.tag != base)

    mid = canvas._add_node_at((0.0, 0.0, 3.0))

    assert mid not in canvas.embedded_nodes
    assert len(canvas.elements) == 2
    spans = {(el.node_i, el.node_j) for el in canvas.elements.values()}
    assert spans == {(base, mid), (mid, top)}


def test_build_model_reports_3d_dimensionality_once_in_3d_mode() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 0.0)
    canvas.end_chain()

    assert canvas.build_model().ndm == 2

    canvas.enter_3d_mode()
    assert canvas.build_model().ndm == 3
    assert canvas.build_model().ndf == 6


def test_a_default_page_stays_2d_and_a_3d_page_starts_ready() -> None:
    """2D and 3D are separate pages/canvases now, not a toggle on one page —
    a default page never grows 3D UI, and a ``start_in_3d`` page begins
    already switched over, with no way back to 2D."""
    page = _page()
    assert page.canvas.ndm == 2
    assert page.level_bar.isVisible() is False
    assert page.preview_3d.isVisible() is False

    page_3d = _page(start_in_3d=True)

    assert page_3d.canvas.ndm == 3
    assert page_3d.level_bar.isVisible() is True
    assert page_3d.preview_3d.isVisible() is True
    assert page_3d.plane_selector.count() == 1  # the ground plane, seeded on entry


def test_adding_a_level_from_the_bar_populates_both_plane_selectors() -> None:
    page = _page(start_in_3d=True)

    page.new_plane_offset.setValue(3.5)
    page.new_plane_label.setText("2F")
    page._add_plane()

    assert page.plane_selector.count() == 2
    assert page.column_target.count() == 2
    assert page.canvas.work_plane.label == "2F"
    assert page.canvas.work_plane.offset == pytest.approx(3.5)


def test_drawing_a_plan_and_extruding_a_column_reaches_the_3d_preview() -> None:
    page = _page(start_in_3d=True)
    _enable_element_drawing(page)
    page.canvas.place_point(0.0, 0.0)
    page.canvas.place_point(4.0, 0.0)
    page.canvas.end_chain()

    page.new_plane_offset.setValue(3.0)
    page.new_plane_label.setText("2F")
    page._add_plane()
    # extrude the ground-plane nodes up to the new level. QComboBox.findData()
    # compares composite objects by identity, not value, so a freshly built
    # WorkPlane has to be matched by hand instead.
    ground = WorkPlane()
    for index in range(page.plane_selector.count()):
        if page.plane_selector.itemData(index) == ground:
            page.plane_selector.setCurrentIndex(index)
    page.canvas.selected_nodes = {1, 2}
    for index in range(page.column_target.count()):
        if page.column_target.itemText(index).startswith("2F"):
            page.column_target.setCurrentIndex(index)
    page._extrude_to_target_plane()

    model = page.canvas.build_model()
    assert model.ndm == 3
    assert len(model.elements) == 3  # the original beam plus two columns
    assert any(node.z == pytest.approx(3.0) for node in model.nodes.values())
    # The 3D preview is a QQuickWidget that composites asynchronously, so a pixel
    # grab is not a reliable check (matches how the other Quick3D tests in this
    # suite verify state); the scene bridge it feeds is inspectable directly.
    assert len(page.preview_3d.bridge.nodes) == len(model.nodes)
    assert len(page.preview_3d.bridge.members) == len(model.elements)


def test_a_3d_cantilever_column_is_drawn_loaded_and_solved_entirely_through_the_ui() -> None:
    """End to end: 3D mode, a column via extrude, a load from the panel, solve,
    and a correct reaction back in the results workspace — the same path a
    student clicking through the app would actually take.
    """
    page = _page(start_in_3d=True)
    base = page.canvas.place_point(0.0, 0.0)
    roof = page.canvas.add_level(4.0, "roof")
    page.canvas.selected_nodes = {base}
    page.canvas.extrude_selection_to_plane(roof)
    top = next(iter(page.canvas.elements.values())).node_j

    page.canvas.set_support(base, (True, True, True, True, True, True))
    page.canvas.selected_nodes = {top}
    page.canvas.selection_changed.emit()
    page.load_target_group.button(0).click()  # 집중하중 (node)
    page.load_fields["fx"].setValue(10.0)
    page._apply_load()

    solve_and_wait(page)

    assert page.workspace_stack.currentIndex() == 1
    reaction = page.results.viewport._result.node_results[base].reaction
    assert reaction[0] == pytest.approx(-10.0, abs=1.0e-6)
    assert abs(reaction[4]) == pytest.approx(40.0, abs=1.0e-6)  # P * L


def test_the_3d_preview_gets_camera_chrome_matching_the_imported_model_viewer() -> None:
    page = _page(start_in_3d=True)

    assert page.preview_3d_panel.isVisible() is True
    assert [page.preview_3d_camera.itemData(i) for i in range(page.preview_3d_camera.count())] == [
        "iso",
        "xy",
        "xz",
        "yz",
    ]

    page.preview_3d_camera.setCurrentIndex(page.preview_3d_camera.findData("xy"))
    assert page.preview_3d.bridge is not None  # camera preset call must not raise

    page._fit_3d_preview()  # must not raise even with an empty model


def test_continue_chain_to_node_connects_even_when_the_node_is_off_the_active_plane() -> None:
    """A 3D-viewport click on an existing node from another storey must reconnect
    to that exact node — going through the active plane's (u, v) math would
    reproduce the wrong point, since the node is not sitting on that plane."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    ground_node = canvas.place_point(0.0, 0.0)
    roof = canvas.add_level(5.0, "roof")
    canvas.selected_nodes = {ground_node}
    canvas.extrude_selection_to_plane(roof)
    top = next(iter(canvas.elements.values())).node_j

    canvas.place_point(2.0, 2.0)  # starts a fresh chain on the ground plane
    result = canvas.continue_chain_to_node(top)

    assert result == top
    assert len(canvas.nodes) == 3  # no duplicate node created for `top`
    member = next(e for e in canvas.elements.values() if top in (e.node_i, e.node_j))
    assert canvas.nodes[top].z == pytest.approx(5.0)
    assert member.node_i != member.node_j


def test_continue_chain_to_node_with_an_unknown_tag_is_a_no_op() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)

    result = canvas.continue_chain_to_node(999)

    assert result == 999
    assert len(canvas.elements) == 0


def test_3d_mode_swaps_the_2d_canvas_out_for_the_3d_view_entirely() -> None:
    """No side-by-side split: the 3D view replaces the 2D plan as the primary
    surface, matching a SketchUp-style single freely-orbited viewport rather
    than a small preview beside a dominant 2D canvas. A default page's canvas
    stack never shows anything but the flat 2D plan; a 3D page's never shows
    anything but the 3D view — they are separate canvases, not a switch."""
    page = _page()
    assert page.canvas_stack.currentWidget() is page.canvas

    page_3d = _page(start_in_3d=True)
    assert page_3d.canvas_stack.currentWidget() is page_3d.preview_3d_panel


def test_the_draw_tool_enables_plane_picking_on_the_3d_view_not_node_picking() -> None:
    page = _page(start_in_3d=True)
    root = page.preview_3d.quick_widget.rootObject()

    _enable_element_drawing(page)
    assert root.property("planePickingEnabled") is True
    assert root.property("pickingEnabled") is False

    page._activate_select_tool()
    assert root.property("planePickingEnabled") is False
    assert root.property("pickingEnabled") is True


def test_clicking_empty_plane_space_in_3d_does_nothing() -> None:
    """An orbit drag in 3D routinely ends in a stray click on empty space -
    clicking the active plane used to drop a new node there every time,
    which meant every accidental release during a camera orbit created a
    node nobody meant to place. Node creation is exact-coordinate-only now
    (the Node tab's Create Node form); a plane click is a pure no-op."""
    page = _page(start_in_3d=True)
    _enable_element_drawing(page)

    page._on_3d_plane_picked(0.0, 0.0, 0.0)
    page._on_3d_plane_picked(4.0, 0.0, 0.0)

    assert page.canvas.nodes == {}
    assert page.canvas.elements == {}


def test_clicking_two_existing_nodes_in_3d_still_connects_them_while_drawing() -> None:
    """Node creation moved to the Create Node form, but connecting two
    already-placed nodes by clicking them (in order) while drawing still
    works - that click can never be an accidental stray one since it has to
    land on an existing node to do anything at all."""
    page = _page(start_in_3d=True)
    first = page.canvas._add_node_at((0.0, 0.0, 0.0))
    second = page.canvas._add_node_at((4.0, 0.0, 0.0))
    _enable_element_drawing(page)

    page._on_3d_node_picked(first, 0, 0)
    page._on_3d_node_picked(second, 0, 0)

    assert len(page.canvas.nodes) == 2
    assert len(page.canvas.elements) == 1
    element = next(iter(page.canvas.elements.values()))
    assert {element.node_i, element.node_j} == {first, second}


def test_clicking_an_existing_node_in_3d_continues_the_chain_while_drawing() -> None:
    page = _page(start_in_3d=True)
    base = page.canvas.place_point(0.0, 0.0)
    roof = page.canvas.add_level(3.0, "roof")
    page.canvas.selected_nodes = {base}
    page.canvas.extrude_selection_to_plane(roof)
    top = next(iter(page.canvas.elements.values())).node_j
    page.canvas.end_chain()

    _enable_element_drawing(page)
    page.canvas.place_point(2.0, 2.0)
    page._on_3d_node_picked(top, 0, 0)

    member = next(e for e in page.canvas.elements.values() if top in (e.node_i, e.node_j))
    assert page.canvas.nodes[top].z == pytest.approx(3.0)
    assert member.node_i != member.node_j


def test_clicking_an_existing_node_in_3d_selects_it_outside_draw_mode() -> None:
    page = _page(start_in_3d=True)
    node = page.canvas.add_node(0.0, 0.0)
    page._activate_select_tool()

    page._on_3d_node_picked(node, 0, 0)

    assert page.canvas.selected_nodes == {node}
    assert node in page.preview_3d.bridge.selectedNodeTags


def test_clicking_an_existing_member_in_3d_selects_and_highlights_it() -> None:
    page = _page(start_in_3d=True)
    left = page.canvas._add_node_at((0.0, 0.0, 0.0))
    right = page.canvas._add_node_at((4.0, 0.0, 0.0))
    member = page.canvas.add_member(left, right)
    page._activate_select_tool()

    page._on_3d_member_picked(member, 0, 0)

    assert page.canvas.selected_nodes == set()
    assert page.canvas.selected_elements == {member}
    assert member in page.preview_3d.bridge.selectedMemberTags


def test_changing_the_active_plane_keeps_the_3d_view_in_sync() -> None:
    page = _page(start_in_3d=True)
    page.new_plane_offset.setValue(2.5)
    page.new_plane_label.setText("2F")
    page._add_plane()

    root = page.preview_3d.quick_widget.rootObject()
    assert root.property("planeOffset") == pytest.approx(2.5)
    assert root.property("planeKind") == "xy"


def test_drawing_in_3d_does_not_reset_the_orbit_camera_on_every_click() -> None:
    """Regression guard: set_model() used to always reframe to ISO, which would
    fight the student's own orbiting after every single placed point."""
    page = _page(start_in_3d=True)
    root = page.preview_3d.quick_widget.rootObject()
    page.preview_3d.set_camera_preset("xy")
    assert root.property("cameraPitch") == pytest.approx(-89.0)

    first = page.canvas._add_node_at((0.0, 0.0, 0.0))
    second = page.canvas._add_node_at((3.0, 0.0, 0.0))
    _enable_element_drawing(page)
    page._on_3d_node_picked(first, 0, 0)
    page._on_3d_node_picked(second, 0, 0)

    assert root.property("cameraPitch") == pytest.approx(-89.0)


def test_hovering_while_drawing_previews_a_segment_from_the_chain_anchor() -> None:
    page = _page(start_in_3d=True)
    _enable_element_drawing(page)
    page.canvas.place_point(0.0, 0.0)  # opens a chain at (0, 0, 0)

    page._on_3d_plane_hovered(4.0, 0.0, 0.0)

    assert len(page.preview_3d.bridge.previewMembers) == 1
    assert page.preview_3d.bridge.previewMembers[0]["length"] == pytest.approx(4.0)


def test_hovering_an_existing_node_while_drawing_snaps_the_preview_onto_it() -> None:
    page = _page(start_in_3d=True)
    anchor = page.canvas._add_node_at((0.0, 0.0, 0.0))
    target = page.canvas._add_node_at((0.0, 0.0, 3.0))
    _enable_element_drawing(page)
    page._on_3d_node_picked(anchor, 0, 0)  # opens a chain at the anchor node

    # A hover point deliberately off the target node's exact coordinates -
    # snapping means the preview uses the node's own (x, y, z), not wherever
    # the ray happened to land near it.
    page._on_3d_node_hovered(target)

    assert len(page.preview_3d.bridge.previewMembers) == 1
    assert page.preview_3d.bridge.previewMembers[0]["length"] == pytest.approx(3.0)


def test_no_open_chain_produces_no_hover_preview() -> None:
    page = _page(start_in_3d=True)
    _enable_element_drawing(page)

    page._on_3d_plane_hovered(1.0, 2.0, 3.0)

    assert page.preview_3d.bridge.previewMembers == []


def test_hover_cleared_removes_the_preview() -> None:
    page = _page(start_in_3d=True)
    _enable_element_drawing(page)
    page.canvas.place_point(0.0, 0.0)
    page._on_3d_plane_hovered(4.0, 0.0, 0.0)
    assert page.preview_3d.bridge.previewMembers != []

    page._on_3d_hover_cleared()

    assert page.preview_3d.bridge.previewMembers == []


def test_committing_a_point_drops_the_stale_preview() -> None:
    """The rubber-band must not linger showing the segment that was just
    placed - the chain moved on, so the preview has to wait for a fresh
    hover before showing anything again."""
    page = _page(start_in_3d=True)
    _enable_element_drawing(page)
    page.canvas.place_point(0.0, 0.0)
    page._on_3d_plane_hovered(4.0, 0.0, 0.0)
    assert page.preview_3d.bridge.previewMembers != []

    page.canvas.place_point(4.0, 0.0)

    assert page.preview_3d.bridge.previewMembers == []


def test_leaving_draw_mode_drops_the_preview() -> None:
    page = _page(start_in_3d=True)
    _enable_element_drawing(page)
    page.canvas.place_point(0.0, 0.0)
    page._on_3d_plane_hovered(4.0, 0.0, 0.0)
    assert page.preview_3d.bridge.previewMembers != []

    page._activate_select_tool()

    assert page.preview_3d.bridge.previewMembers == []


def test_the_3d_viewport_accepts_keyboard_focus_so_space_can_reach_it() -> None:
    """The Space-bar draw shortcut is scoped to preview_3d in 3D mode (see
    __init__) - a QShortcut with WidgetWithChildrenShortcut context only ever
    fires while that widget tree actually holds focus, so the quick widget
    must be focusable at all for a click there to grab it."""
    from PySide6.QtCore import Qt as QtCoreQt

    page = _page(start_in_3d=True)

    assert page.preview_3d.quick_widget.focusPolicy() != QtCoreQt.FocusPolicy.NoFocus
    assert page.draw_space_shortcut_3d.parent() is page.preview_3d


def test_escape_in_the_3d_view_exits_draw_mode() -> None:
    page = _page(start_in_3d=True)
    _enable_element_drawing(page)
    assert page.canvas.mode == "draw"

    # Draw mode intentionally focuses the numeric entry. Escape still needs
    # to leave drawing even though the QQuickWidget no longer owns focus.
    page.draw_entry.setFocus()
    QTest.keyClick(page.draw_entry, Qt.Key.Key_Escape)
    QApplication.processEvents()

    assert page.canvas.mode == "select"
    assert page.escape_shortcut_3d.parent() is page


def test_3d_view_exposes_clear_snap_and_directional_selection_feedback() -> None:
    page = _page(start_in_3d=True)
    root = page.preview_3d.quick_widget.rootObject()
    snap = root.findChild(QObject, "nodeSnapIndicator")
    box = root.findChild(QObject, "selectionRubberBand")

    assert snap is not None
    assert box is not None

    root.setProperty("selectionStartY", 20.0)
    root.setProperty("selectionCurrentY", 100.0)
    QApplication.processEvents()
    assert box.property("crossing") is False

    root.setProperty("selectionStartY", 100.0)
    root.setProperty("selectionCurrentY", 20.0)
    QApplication.processEvents()
    assert box.property("crossing") is True


def test_3d_box_selection_updates_and_highlights_nodes_and_members() -> None:
    page = _page(start_in_3d=True)
    left = page.canvas._add_node_at((0.0, 0.0, 0.0))
    right = page.canvas._add_node_at((4.0, 0.0, 0.0))
    member = page.canvas.add_member(left, right)

    page._on_3d_box_selected({left}, {member}, False)

    assert page.canvas.selected_nodes == {left}
    assert page.canvas.selected_elements == {member}
    assert left in page.preview_3d.bridge.selectedNodeTags
    assert member in page.preview_3d.bridge.selectedMemberTags


def test_3d_box_selection_ignores_narrowed_selection_filter() -> None:
    """Transform tabs auto-narrow selection_filter to "elements" or "nodes" for
    plain clicks, but a drag box must still apply both kinds from the QML
    viewport — half the result used to be dropped silently."""
    page = _page(start_in_3d=True)
    left = page.canvas._add_node_at((0.0, 0.0, 0.0))
    right = page.canvas._add_node_at((4.0, 0.0, 0.0))
    member = page.canvas.add_member(left, right)

    page._element_subcategory_clicked("duplicate")
    assert page.canvas.selection_filter == "elements"

    page._on_3d_box_selected({left, right}, {member}, False)

    assert page.canvas.selected_nodes == {left, right}
    assert page.canvas.selected_elements == {member}

    page._node_subcategory_clicked("duplicate_node")
    assert page.canvas.selection_filter == "nodes"

    page._on_3d_box_selected({left, right}, {member}, False)

    assert page.canvas.selected_nodes == {left, right}
    assert page.canvas.selected_elements == {member}


def test_delete_and_ctrl_z_reach_the_canvas_while_the_3d_viewport_has_focus() -> None:
    """Delete/Ctrl+Z/Ctrl+Y are scoped to self.canvas, which stays hidden in
    3D mode and can therefore never hold keyboard focus - so a node/member
    selected via preview_3d's own drag-box (see test above) could be
    highlighted but never actually deleted or undone. A second copy of the
    shortcuts scoped to preview_3d (same pattern as draw_space_shortcut_3d)
    fixes that."""
    page = _page(start_in_3d=True)
    left = page.canvas._add_node_at((0.0, 0.0, 0.0))
    right = page.canvas._add_node_at((4.0, 0.0, 0.0))
    member = page.canvas.add_member(left, right)
    page._on_3d_box_selected({left, right}, {member}, False)

    page.preview_3d.quick_widget.setFocus()
    QApplication.processEvents()

    QTest.keyClick(page.preview_3d.quick_widget, Qt.Key.Key_Delete)
    assert page.canvas.elements == {}

    QTest.keyClick(page.preview_3d.quick_widget, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert member in page.canvas.elements

    QTest.keyClick(page.preview_3d.quick_widget, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert page.canvas.elements == {}


def test_empty_space_click_in_the_3d_view_clears_the_selection() -> None:
    """The QML view's own onClicked emits emptySpaceClicked() when a plain
    click (not a drag-box) hits neither a node nor a member - the 3D
    equivalent of clicking empty space on the 2D canvas, which already
    deselects there. Simulated directly on the relayed Quick3DViewport
    signal, the same way the box-selection tests above simulate
    selectionBoxFinished, since real 3D picking needs a GPU-backed pick()
    this offscreen test environment cannot reliably provide."""
    page = _page(start_in_3d=True)
    left = page.canvas._add_node_at((0.0, 0.0, 0.0))
    right = page.canvas._add_node_at((4.0, 0.0, 0.0))
    member = page.canvas.add_member(left, right)
    page._on_3d_box_selected({left, right}, {member}, False)
    assert page.canvas.selected_nodes and page.canvas.selected_elements

    page.preview_3d.empty_space_clicked.emit()

    assert not page.canvas.selected_nodes
    assert not page.canvas.selected_elements
    assert member in page.canvas.elements  # deselects only, never deletes


def test_escape_in_the_3d_view_clears_selection_when_not_drawing() -> None:
    """Companion to test_escape_in_the_3d_view_exits_draw_mode above: once
    already in select mode (not drawing), Escape must clear the current
    selection instead of just re-entering the tool it is already in -
    _handle_escape_shortcut_3d is the second copy of the 2D canvas's own
    Escape-to-deselect (canvas_input_events.py) scoped to the whole 3D page,
    since self.canvas never holds focus in 3D mode."""
    page = _page(start_in_3d=True)
    left = page.canvas._add_node_at((0.0, 0.0, 0.0))
    right = page.canvas._add_node_at((4.0, 0.0, 0.0))
    member = page.canvas.add_member(left, right)
    page._on_3d_box_selected({left, right}, {member}, False)
    assert page.canvas.mode == "select"

    page._handle_escape_shortcut_3d()

    assert not page.canvas.selected_nodes
    assert not page.canvas.selected_elements
    assert member in page.canvas.elements


def test_snapping_only_reaches_nodes_on_the_active_plane() -> None:
    canvas = _canvas()
    canvas.enter_3d_mode()
    canvas.place_point(2.0, 0.0)  # on the ground plane at (2, 0, 0)
    roof = canvas.add_level(5.0, "roof")
    canvas.set_active_plane(roof)

    snap = canvas.snap_at(2.02, 0.01)

    assert snap.node_tag is None, "a ground-floor node must not be reachable from the roof plan"


def test_moving_a_member_off_the_active_plane_preserves_its_true_height() -> None:
    """transform_selected_nodes("move", ...) used to round-trip every node
    through _uv()/WorkPlane.to_3d(), which always snaps the third coordinate
    to the *active plane's own offset* - fine for a node that actually sits
    on that plane, but it silently dropped an elevated member (e.g. a beam
    at Z=3 while the ground plane at Z=0 is still active) down onto the
    active plane's height instead of moving it sideways in place."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    left = canvas._add_node_at((0.0, 0.0, 3.0))
    right = canvas._add_node_at((4.0, 0.0, 3.0))
    member = canvas.add_member(left, right)
    canvas.selected_nodes = {left, right}
    canvas.selected_elements = {member}

    canvas.transform_selected_nodes("move", 1.0, 0.0)

    assert canvas.nodes[left].x == pytest.approx(1.0)
    assert canvas.nodes[left].z == pytest.approx(3.0)
    assert canvas.nodes[right].x == pytest.approx(5.0)
    assert canvas.nodes[right].z == pytest.approx(3.0)


def test_copying_a_member_off_the_active_plane_preserves_its_true_height() -> None:
    """Same bug as the move test above, for "copy" - the copied nodes (and
    therefore the copied member) used to land on the active plane's Z
    instead of the source member's own Z."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    left = canvas._add_node_at((0.0, 0.0, 3.0))
    right = canvas._add_node_at((4.0, 0.0, 3.0))
    member = canvas.add_member(left, right)
    canvas.selected_nodes = {left, right}
    canvas.selected_elements = {member}

    created = canvas.transform_selected_nodes("copy", 5.0, 0.0)

    assert created == 2
    new_nodes = [node for tag, node in canvas.nodes.items() if tag not in (left, right)]
    assert len(new_nodes) == 2
    assert all(node.z == pytest.approx(3.0) for node in new_nodes)
    assert {round(node.x, 6) for node in new_nodes} == {5.0, 9.0}
    assert len(canvas.elements) == 2, "the copied member itself must exist, not just its nodes"


def test_copying_a_member_onto_an_existing_members_line_still_creates_the_copy() -> None:
    """A copy offset that happens to land the new start node exactly on an
    *existing* member's own line makes _add_node_at split that member into
    two pieces (its own documented behaviour - landing on a line means "put
    a real joint here"). When the split member was the very one being
    copied, re-fetching it from self.elements by its old tag *after* the
    split silently returned the wrong (truncated) piece, whose endpoints no
    longer both appear in the copy's node mapping - so the actual copied
    member was never created at all, even though its two nodes were.
    Copying a 4m member by exactly half its own span (2.0) reproduces this
    directly: the new start node lands exactly on the original's midpoint."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    left = canvas._add_node_at((0.0, 0.0, 3.0))
    right = canvas._add_node_at((4.0, 0.0, 3.0))
    member = canvas.add_member(left, right)
    canvas.selected_nodes = {left, right}
    canvas.selected_elements = {member}

    created = canvas.transform_selected_nodes("copy", 2.0, 0.0)

    assert created == 2
    copy_start = next(
        node for tag, node in canvas.nodes.items() if tag not in (left, right) and node.x == 2.0
    )
    copy_end = next(
        node for tag, node in canvas.nodes.items() if tag not in (left, right) and node.x == 6.0
    )
    matches_copy = [
        element
        for element in canvas.elements.values()
        if {canvas.nodes[element.node_i].x, canvas.nodes[element.node_j].x}
        == {copy_start.x, copy_end.x}
    ]
    assert len(matches_copy) == 1, "the copied member must exist even though its start landed on the original's line"


def test_array_and_rotate_copy_also_preserve_true_height_off_the_active_plane() -> None:
    """array_copy_selection and rotate_copy_selection share the same
    _uv()-based node placement as move/copy - regression coverage that they
    were not (and stay not) affected by the same active-plane-snapping bug."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    left = canvas._add_node_at((0.0, 0.0, 3.0))
    right = canvas._add_node_at((4.0, 0.0, 3.0))
    member = canvas.add_member(left, right)

    canvas.selected_nodes = {left, right}
    canvas.selected_elements = {member}
    canvas.array_copy_selection(0.0, 5.0, count=1)
    array_copies = [node for tag, node in canvas.nodes.items() if tag not in (left, right)]
    assert len(array_copies) == 2
    assert all(node.z == pytest.approx(3.0) for node in array_copies)

    canvas2 = _canvas()
    canvas2.enter_3d_mode()
    left2 = canvas2._add_node_at((0.0, 0.0, 3.0))
    right2 = canvas2._add_node_at((4.0, 0.0, 3.0))
    member2 = canvas2.add_member(left2, right2)
    canvas2.selected_nodes = {left2, right2}
    canvas2.selected_elements = {member2}
    canvas2.rotate_copy_selection(0.0, 10.0, 30.0, count=1)
    rotate_copies = [node for tag, node in canvas2.nodes.items() if tag not in (left2, right2)]
    assert len(rotate_copies) == 2
    assert all(node.z == pytest.approx(3.0) for node in rotate_copies)


def test_move_and_copy_can_now_offset_along_the_plane_normal_axis() -> None:
    """Regression test: dx/dy could only move within the active work plane -
    there was no way to reach the third (out-of-plane) axis at all, reported
    as "복사 기능에서 z축으로 복사하는 기능이 없음" / "노드 부분에서도 z축으로
    복사, 이동, 정렬, 회전 그런 기능도 element에서도 없는걸 확인". The active
    plane here is the default ground XY plane, so its normal is Z."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    node = canvas._add_node_at((1.0, 2.0, 0.0))

    canvas.selected_nodes = {node}
    canvas.transform_selected_nodes("move", 0.0, 0.0, dz=5.0)
    assert canvas.nodes[node].z == pytest.approx(5.0)
    assert canvas.nodes[node].x == pytest.approx(1.0)
    assert canvas.nodes[node].y == pytest.approx(2.0)

    canvas2 = _canvas()
    canvas2.enter_3d_mode()
    left = canvas2._add_node_at((0.0, 0.0, 0.0))
    right = canvas2._add_node_at((4.0, 0.0, 0.0))
    member = canvas2.add_member(left, right)
    canvas2.selected_nodes = {left, right}
    canvas2.selected_elements = {member}
    canvas2.transform_selected_nodes("copy", 0.0, 0.0, repeat=1, dz=3.0)
    copies = [node for tag, node in canvas2.nodes.items() if tag not in (left, right)]
    assert len(copies) == 2
    assert {round(node.z, 6) for node in copies} == {3.0}
    assert len(canvas2.elements) == 2  # original span + the copied one


def test_array_and_rotate_copy_can_also_step_along_the_plane_normal_axis() -> None:
    """Same dz support as move/copy, for array_copy_selection (repeating a
    whole storey's frame straight up) and rotate_copy_selection (a
    helical/spiral step, e.g. a spiral stair)."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    left = canvas._add_node_at((0.0, 0.0, 0.0))
    right = canvas._add_node_at((4.0, 0.0, 0.0))
    member = canvas.add_member(left, right)
    canvas.selected_nodes = {left, right}
    canvas.selected_elements = {member}
    canvas.array_copy_selection(0.0, 0.0, count=2, dz=3.0)
    heights = sorted(
        round(node.z, 6) for tag, node in canvas.nodes.items() if tag not in (left, right)
    )
    assert heights == [3.0, 3.0, 6.0, 6.0]

    canvas2 = _canvas()
    canvas2.enter_3d_mode()
    node = canvas2._add_node_at((10.0, 0.0, 0.0))
    canvas2.selected_nodes = {node}
    canvas2.rotate_copy_selection(0.0, 0.0, 90.0, count=2, dz=1.0)
    steps = sorted(
        round(n.z, 6) for tag, n in canvas2.nodes.items() if tag != node
    )
    assert steps == [1.0, 2.0]


def _find_offset_line(section) -> QLineEdit:
    field = section.findChild(QLineEdit)
    assert field is not None
    return field


def _find_apply_button(section) -> QPushButton:
    button = section.findChild(QPushButton)
    assert button is not None
    return button


def _section_label_texts(section) -> list[str]:
    return [label.text() for label in section.findChildren(QLabel)]


def test_2d_transform_panels_do_not_expose_or_apply_a_z_offset() -> None:
    page = _page(start_in_3d=False)

    for key in (
        "translate_node",
        "duplicate_node",
        "array_node",
        "duplicate",
        "array",
    ):
        section = page.category_stack.widget(page.category_pages[key])
        offset_field = _find_offset_line(section)
        assert offset_field.text() == "0, 0"
        assert offset_field.placeholderText() == "dX, dY"
        assert all("dZ" not in text for text in _section_label_texts(section))

    for key in ("move", "rotate_node", "rotate"):
        section = page.category_stack.widget(page.category_pages[key])
        assert all("dZ" not in text for text in _section_label_texts(section))

    node = page.canvas._add_node_at((1.0, 2.0))
    page.canvas.selected_nodes = {node}
    section = page.category_stack.widget(page.category_pages["translate_node"])
    offset_field = _find_offset_line(section)
    offset_field.setText("3, -1, 99")
    QTest.mouseClick(_find_apply_button(section), Qt.MouseButton.LeftButton)

    moved = page.canvas.nodes[node]
    assert moved.x == pytest.approx(4.0)
    assert moved.y == pytest.approx(1.0)
    assert moved.z == pytest.approx(0.0)


def test_3d_transform_panels_keep_three_axis_inputs() -> None:
    page = _page(start_in_3d=True)

    for key in (
        "move",
        "duplicate",
        "array",
        "translate_node",
        "duplicate_node",
        "array_node",
    ):
        section = page.category_stack.widget(page.category_pages[key])
        offset_field = _find_offset_line(section)
        assert offset_field.text() == "0, 0, 0"
        assert offset_field.placeholderText() == "dX, dY, dZ"

    for key in ("rotate_node", "rotate"):
        section = page.category_stack.widget(page.category_pages[key])
        assert "반복당 dZ" in _section_label_texts(section)


def test_element_translate_panel_parses_a_single_dx_dy_dz_line() -> None:
    """End-to-end regression test for the single-line "dX, dY, dZ" input
    that replaced the old two-spinbox dX/dY form (requested: "dx, dy가
    따로 되어 있어서 불편하다 ... 0,0,0 0,0,0 이런식으로 입력하게 바꿔줘"),
    including the new dZ (plane-normal) offset it also unlocked."""
    page = _page(start_in_3d=True)
    node = page.canvas._add_node_at((1.0, 2.0, 0.0))
    page.canvas.selected_nodes = {node}

    section = page.category_stack.widget(page.category_pages["move"])
    page.category_stack.setCurrentWidget(section)
    offset_field = _find_offset_line(section)
    assert offset_field.text() == "0, 0, 0"
    offset_field.setText("3, -1, 5")
    QTest.mouseClick(_find_apply_button(section), Qt.MouseButton.LeftButton)

    moved = page.canvas.nodes[node]
    assert moved.x == pytest.approx(4.0)
    assert moved.y == pytest.approx(1.0)
    assert moved.z == pytest.approx(5.0)


def test_node_array_copy_panel_accepts_a_dz_offset() -> None:
    """Same single-line input, for the Node tab's Array Copy page - repeat
    count together with a dZ offset must step a copy up in Z each time."""
    page = _page(start_in_3d=True)
    left = page.canvas._add_node_at((0.0, 0.0, 0.0))
    right = page.canvas._add_node_at((4.0, 0.0, 0.0))
    page.canvas.add_member(left, right)
    page.canvas.selected_nodes = {left, right}

    section = page.category_stack.widget(page.category_pages["array_node"])
    page.category_stack.setCurrentWidget(section)
    offset_field = _find_offset_line(section)
    offset_field.setText("0, 0, 3")
    QTest.mouseClick(_find_apply_button(section), Qt.MouseButton.LeftButton)

    heights = sorted(
        round(node.z, 6) for tag, node in page.canvas.nodes.items() if tag not in (left, right)
    )
    assert heights == [3.0, 3.0]
