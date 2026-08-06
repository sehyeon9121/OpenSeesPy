import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.features.model.drawing import PlaneKind, WorkPlane
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.set_mode("draw")
    return canvas


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
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


def test_the_3d_toggle_switches_the_canvas_and_reveals_the_level_bar() -> None:
    page = _page()
    assert page.canvas.ndm == 2
    assert page.level_bar.isVisible() is False
    assert page.preview_3d.isVisible() is False

    page.mode_3d_toggle.setChecked(True)

    assert page.canvas.ndm == 3
    assert page.level_bar.isVisible() is True
    assert page.preview_3d.isVisible() is True
    assert page.plane_selector.count() == 1  # the ground plane, seeded on entry


def test_adding_a_level_from_the_bar_populates_both_plane_selectors() -> None:
    page = _page()
    page.mode_3d_toggle.setChecked(True)

    page.new_plane_offset.setValue(3.5)
    page.new_plane_label.setText("2F")
    page._add_plane()

    assert page.plane_selector.count() == 2
    assert page.column_target.count() == 2
    assert page.canvas.work_plane.label == "2F"
    assert page.canvas.work_plane.offset == pytest.approx(3.5)


def test_drawing_a_plan_and_extruding_a_column_reaches_the_3d_preview() -> None:
    page = _page()
    page.mode_3d_toggle.setChecked(True)
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
    page = _page()
    page.mode_3d_toggle.setChecked(True)
    base = page.canvas.place_point(0.0, 0.0)
    roof = page.canvas.add_level(4.0, "roof")
    page.canvas.selected_nodes = {base}
    page.canvas.extrude_selection_to_plane(roof)
    top = next(iter(page.canvas.elements.values())).node_j

    page.canvas.set_support(base, (True, True, True, True, True, True))
    page.canvas.selected_nodes = {top}
    page.canvas.selection_changed.emit()
    page.load_target.setCurrentIndex(page.load_target.findData("node"))
    page.load_direction.setCurrentIndex(page.load_direction.findData("fx+"))
    page.load_magnitude.setValue(10.0)
    page._apply_directional_load()

    page.solve()

    assert page.workspace_stack.currentIndex() == 1
    reaction = page.results.viewport._result.node_results[base].reaction
    assert reaction[0] == pytest.approx(-10.0, abs=1.0e-6)
    assert abs(reaction[4]) == pytest.approx(40.0, abs=1.0e-6)  # P * L


def test_snapping_only_reaches_nodes_on_the_active_plane() -> None:
    canvas = _canvas()
    canvas.enter_3d_mode()
    canvas.place_point(2.0, 0.0)  # on the ground plane at (2, 0, 0)
    roof = canvas.add_level(5.0, "roof")
    canvas.set_active_plane(roof)

    snap = canvas.snap_at(2.02, 0.01)

    assert snap.node_tag is None, "a ground-floor node must not be reachable from the roof plan"
