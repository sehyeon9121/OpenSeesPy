import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from openframe.features.analysis.statics import check_determinacy
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def test_student_can_draw_and_solve_a_free_form_simply_supported_beam() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.set_support(left, (True, True, False))
    canvas.set_support(right, (False, True, False))
    canvas.set_uniform_load(member, (0.0, -10.0))
    page.solve()

    assert page.workspace_stack.currentIndex() == 1
    assert page.viewport._result.node_results[left].reaction[1] == pytest.approx(20.0)
    assert page.viewport._result.node_results[right].reaction[1] == pytest.approx(20.0)


def test_drawn_hinge_becomes_a_member_release_and_makes_a_gerber_beam_solvable() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    fixed = canvas.add_node(0.0, 0.0)
    hinge = canvas.add_node(4.0, 0.0)
    roller = canvas.add_node(8.0, 0.0)
    canvas.add_member(fixed, hinge)
    suspended = canvas.add_member(hinge, roller)
    canvas.set_support(fixed, (True, True, True))
    canvas.set_support(roller, (False, True, False))
    canvas.set_uniform_load(suspended, (0.0, -10.0))
    canvas.selected_nodes = {hinge}
    canvas.set_selected_node_kind(True)

    model = canvas.build_model()
    assert model.elements[suspended].moment_release_i is True
    assert check_determinacy(model).degree == 0

    page.solve()

    assert page.workspace_stack.currentIndex() == 1
    assert page.viewport._result.node_results[fixed].reaction[1] == pytest.approx(20.0)
    assert page.viewport._result.node_results[fixed].reaction[2] == pytest.approx(80.0)
    assert page.viewport._result.node_results[roller].reaction[1] == pytest.approx(20.0)


def test_selected_node_deletion_also_removes_connected_entities() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    first = canvas.add_node(0.0, 0.0)
    second = canvas.add_node(2.0, 0.0)
    canvas.add_member(first, second)
    canvas.set_support(first, (True, True, True))
    canvas._selected = ("node", first)
    canvas.delete_selected()

    assert first not in canvas.nodes
    assert not canvas.elements
    assert first not in canvas.boundaries


def test_coordinate_node_creation_supports_midas_style_repetition() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()

    assert application is QApplication.instance()
    page.node_x.setValue(0.0)
    page.node_y.setValue(1.0)
    page.node_dx.setValue(2.0)
    page.node_dy.setValue(0.5)
    page.node_repeat.setValue(3)
    page._add_nodes_from_coordinates()

    assert [(node.x, node.y) for node in page.canvas.nodes.values()] == [
        (0.0, 1.0),
        (2.0, 1.5),
        (4.0, 2.0),
    ]


def test_selected_entities_receive_support_hinge_and_load_properties() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.selected_nodes = {left, right}
    canvas.selected_elements = {member}
    canvas.apply_support_to_selection((False, True, False))
    canvas.set_selected_node_kind(True)
    canvas.apply_nodal_load_to_selection((5.0, -10.0, 2.0))
    canvas.apply_uniform_load_to_selection((0.0, -3.0))

    model = canvas.build_model()
    assert len(model.boundaries) == 2
    assert len(model.nodal_loads) == 2
    assert model.element_loads[0].wy == pytest.approx(-3.0)
    assert model.metadata["hinge_nodes"] == f"{left},{right}"


def test_member_click_uses_the_same_near_node_snap_as_the_preview() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas
    page.resize(1000, 700)
    page.show()
    application.processEvents()
    canvas.add_node(0.0, 0.0)
    canvas.add_node(4.0, 0.0)
    canvas.set_mode("member")

    first = canvas.mapFromScene(0.0, 0.0)
    second_near = canvas.mapFromScene(4.0 * canvas._DRAW_SCALE, 0.0) + QPoint(10, 0)
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseMove(canvas.viewport(), second_near)
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=second_near)

    assert len(canvas.elements) == 1
    element = next(iter(canvas.elements.values()))
    assert (element.node_i, element.node_j) == (1, 2)


def test_drag_direction_and_filter_control_window_or_crossing_selection() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    small_window = QRectF(-15.0, -15.0, 30.0, 30.0)

    canvas.selection_filter = "elements"
    canvas._select_in_rect(small_window, crossing=False)
    assert canvas.selected_elements == set()
    canvas._select_in_rect(small_window, crossing=True)
    assert canvas.selected_elements == {member}

    canvas.clear_selection()
    canvas.selection_filter = "nodes"
    canvas._select_in_rect(small_window, crossing=True)
    assert canvas.selected_nodes == {left}
    assert canvas.selected_elements == set()


def test_context_support_and_directional_load_apply_without_panel_hopping() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}

    assert application is QApplication.instance()
    page._activate_support_tool()
    page.support_kind.setCurrentIndex(page.support_kind.findText("수직 롤러"))
    page.canvas.apply_support_to_selection(page.support_kind.currentData())
    page._activate_load_tool()
    page.load_target.setCurrentIndex(page.load_target.findData("node"))
    page.load_direction.setCurrentIndex(3)
    page.load_magnitude.setValue(12.5)
    page._apply_directional_load()

    model = page.canvas.build_model()
    assert model.boundaries[0].restraints == (False, True, False)
    assert model.nodal_loads[0].values == pytest.approx((0.0, -12.5, 0.0))


def test_delete_and_ctrl_z_restore_the_selected_member() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    page.show()
    application.processEvents()
    left = page.canvas.add_node(0.0, 0.0)
    right = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(left, right)
    page.canvas.selected_elements = {member}

    QTest.keyClick(page.canvas, Qt.Key.Key_Delete)
    assert not page.canvas.elements
    QTest.keyClick(page.canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert member in page.canvas.elements
    QTest.keyClick(page.canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert not page.canvas.elements


def test_repeated_node_creation_is_one_undo_operation() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()

    assert application is QApplication.instance()
    page.node_repeat.setValue(4)
    page.node_dx.setValue(1.5)
    page._add_nodes_from_coordinates()
    assert len(page.canvas.nodes) == 4

    page.canvas.undo()
    assert not page.canvas.nodes


def test_midpoint_snap_adds_an_analysis_node_without_splitting_the_visible_member() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    middle = canvas.add_member_midpoint_node(member)
    canvas.set_support(left, (True, True, False))
    canvas.set_support(right, (False, True, False))
    canvas.set_nodal_load(middle, (0.0, -10.0, 0.0))

    model = canvas.build_model()
    assert len(canvas.elements) == 1
    assert len(model.elements) == 2
    assert all(middle in {element.node_i, element.node_j} for element in model.elements.values())
    assert model.metadata["hinge_nodes"] == ""
    assert model.metadata["logical_member_count"] == "1"
    assert model.metadata["embedded_nodes"] == f"{middle}:{member}:0.5"
    assert check_determinacy(model).degree == 0


def test_collinear_node_is_auto_attached_without_splitting_the_visible_member() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    middle = canvas.add_node(2.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    canvas.add_member(left, right)

    assert len(canvas.elements) == 1
    element = next(iter(canvas.elements.values()))
    assert (element.node_i, element.node_j) == (left, right)
    assert canvas.embedded_nodes[middle] == (element.tag, 0.5)
    assert len(canvas.build_model().elements) == 2


def test_midpoint_tool_snaps_near_member_center_and_is_undoable() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas
    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.set_mode("member_midpoint")
    near_midpoint = QPointF(2.0 * canvas._DRAW_SCALE, 8.0)
    snapped_member = canvas._member_near_scene(near_midpoint)
    assert snapped_member == member
    canvas.add_member_midpoint_node(snapped_member)
    assert len(canvas.nodes) == 3
    assert next(iter(canvas.embedded_nodes.values())) == (member, 0.5)
    assert len(canvas.elements) == 1

    canvas.undo()
    assert len(canvas.nodes) == 2
    assert not canvas.embedded_nodes
    assert len(canvas.elements) == 1


def test_arbitrary_member_station_accepts_a_point_load_without_instability() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(10.0, 0.0)
    member = canvas.add_member(left, right)
    load_node = canvas.add_member_station_node(member, 0.3)
    canvas.set_support(left, (True, True, False))
    canvas.set_support(right, (False, True, False))
    canvas.set_nodal_load(load_node, (0.0, -15.0, 0.0))

    model = canvas.build_model()
    assert len(canvas.elements) == 1
    assert len(model.elements) == 2
    assert canvas.nodes[load_node].x == pytest.approx(3.0)
    assert check_determinacy(model).degree == 0
    page.solve()
    assert page.viewport._result.node_results[left].reaction[1] == pytest.approx(10.5)
    assert page.viewport._result.node_results[right].reaction[1] == pytest.approx(4.5)


def test_selected_node_can_move_without_losing_member_connectivity_and_undo() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.selected_nodes = {right}
    assert canvas.transform_selected_nodes("move", 1.5, 0.5) == 1
    assert (canvas.nodes[right].x, canvas.nodes[right].y) == pytest.approx((5.5, 0.5))
    assert canvas.elements[member].node_j == right

    canvas.undo()
    assert (canvas.nodes[right].x, canvas.nodes[right].y) == pytest.approx((4.0, 0.0))


def test_selected_nodes_can_be_copied_repeatedly_as_one_undo_operation() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    source = canvas.add_node(0.25, 0.5)
    canvas.selected_nodes = {source}
    canvas.set_selected_node_kind(True)
    assert canvas.transform_selected_nodes("copy", 1.25, 0.5, repeat=3) == 3
    assert [(node.x, node.y) for node in canvas.nodes.values()] == pytest.approx(
        [(0.25, 0.5), (1.5, 1.0), (2.75, 1.5), (4.0, 2.0)]
    )
    assert canvas.hinge_nodes == {1, 2, 3, 4}

    canvas.undo()
    assert list(canvas.nodes) == [source]


def test_blank_space_drag_selects_nodes_even_while_member_tool_is_active() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    page.resize(1000, 700)
    page.show()
    application.processEvents()
    canvas = page.canvas
    node = canvas.add_node(0.0, 0.0)
    canvas.set_mode("member")
    start = canvas.mapFromScene(-30.0, -30.0)
    end = canvas.mapFromScene(30.0, 30.0)

    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas.viewport(), end)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)

    assert canvas.selected_nodes == {node}
    assert canvas.mode == "member"


def test_node_transform_tool_activates_node_drag_selection_without_support_tool() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()

    assert application is QApplication.instance()
    page._activate_node_transform_tool()
    assert page.canvas.mode == "select"
    assert page.canvas.selection_filter == "nodes"
