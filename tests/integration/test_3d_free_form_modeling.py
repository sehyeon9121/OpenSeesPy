import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.features.model.drawing import PlaneKind, WorkPlane
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas

from _solve_helpers import solve_and_wait


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


def test_a_node_dropped_mid_height_on_a_column_embeds_in_true_3d() -> None:
    """Colinearity is a real 3D fact — it must hold on an elevation view too."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    base = canvas.place_point(0.0, 0.0)
    roof = canvas.add_level(6.0, "roof")
    canvas.selected_nodes = {base}
    canvas.extrude_selection_to_plane(roof)
    column = next(iter(canvas.elements))

    mid = canvas._add_node_at((0.0, 0.0, 3.0))

    assert canvas.embedded_nodes[mid] == (column, pytest.approx(0.5))


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
    page._activate_draw_tool()
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

    page._activate_draw_tool()
    assert root.property("planePickingEnabled") is True
    assert root.property("pickingEnabled") is False

    page._activate_select_tool()
    assert root.property("planePickingEnabled") is False
    assert root.property("pickingEnabled") is True


def test_clicking_the_active_plane_in_3d_places_a_point_through_the_same_chain_logic() -> None:
    """The 3D pick path and the 2D click path must produce identical model
    data — this is what lets every existing 2D drawing test's guarantees (snap,
    undo, member creation) carry over to 3D clicking for free."""
    page = _page(start_in_3d=True)
    page._activate_draw_tool()

    page._on_3d_plane_picked(0.0, 0.0, 0.0)
    page._on_3d_plane_picked(4.0, 0.0, 0.0)

    assert len(page.canvas.nodes) == 2
    assert len(page.canvas.elements) == 1
    element = next(iter(page.canvas.elements.values()))
    assert page.canvas.nodes[element.node_i].x == pytest.approx(0.0)
    assert page.canvas.nodes[element.node_j].x == pytest.approx(4.0)


def test_clicking_an_existing_node_in_3d_continues_the_chain_while_drawing() -> None:
    page = _page(start_in_3d=True)
    base = page.canvas.place_point(0.0, 0.0)
    roof = page.canvas.add_level(3.0, "roof")
    page.canvas.selected_nodes = {base}
    page.canvas.extrude_selection_to_plane(roof)
    top = next(iter(page.canvas.elements.values())).node_j
    page.canvas.end_chain()

    page._activate_draw_tool()
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

    page._activate_draw_tool()
    page._on_3d_plane_picked(0.0, 0.0, 0.0)
    page._on_3d_plane_picked(3.0, 0.0, 0.0)

    assert root.property("cameraPitch") == pytest.approx(-89.0)


def test_snapping_only_reaches_nodes_on_the_active_plane() -> None:
    canvas = _canvas()
    canvas.enter_3d_mode()
    canvas.place_point(2.0, 0.0)  # on the ground plane at (2, 0, 0)
    roof = canvas.add_level(5.0, "roof")
    canvas.set_active_plane(roof)

    snap = canvas.snap_at(2.02, 0.01)

    assert snap.node_tag is None, "a ground-floor node must not be reachable from the roof plan"
