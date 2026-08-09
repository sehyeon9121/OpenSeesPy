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


def test_crossing_selection_only_picks_members_the_rectangle_actually_crosses() -> None:
    """Regression test: QLineF.intersects() reports UnboundedIntersection whenever
    the two *infinite* lines would cross somewhere, even nowhere near either
    actual segment. The crossing-selection check used to accept that ("!=
    NoIntersection"), so a small crossing-mode drag selected almost every non-
    parallel member in the model, not just the ones the rectangle visibly
    touched - reported as "dragging bottom-to-top selects every member"."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    # Crossed: a horizontal member straddling the origin, well outside the
    # small window at both ends but passing straight through its middle.
    crossed_left = canvas.add_node(-2.0, 0.0)
    crossed_right = canvas.add_node(2.0, 0.0)
    crossed_member = canvas.add_member(crossed_left, crossed_right)

    # Untouched: a diagonal member far from the window, chosen so its infinite
    # line extension (not the actual segment) passes through the window - the
    # exact shape that used to trigger the bug.
    far_a = canvas.add_node(5.0, -10.0)
    far_b = canvas.add_node(5.5, -11.0)
    untouched_member = canvas.add_member(far_a, far_b)

    small_window = QRectF(-10.0, -10.0, 20.0, 20.0)
    canvas.selection_filter = "elements"
    canvas._select_in_rect(small_window, crossing=True)

    assert canvas.selected_elements == {crossed_member}
    assert untouched_member not in canvas.selected_elements


def test_context_support_and_directional_load_apply_without_panel_hopping() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}

    assert application is QApplication.instance()
    page._activate_support_tool()
    page.support_buttons[2].click()  # 수직롤러
    page._activate_load_tool()
    page.load_target_group.button(0).click()  # 집중하중 (node)
    page.load_fields["fy"].setValue(-12.5)
    page._apply_load()

    model = page.canvas.build_model()
    assert model.boundaries[0].restraints == (True, False, False)
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


def test_splitting_a_trapezoidal_load_interpolates_each_segment_not_copies_the_whole_span() -> None:
    """Regression test: build_model() used to rebuild every analysis segment's
    load from just (wx, wy) - the member's own *i-end* values - dropping
    wx_j/wy_j entirely, so a triangular/trapezoidal load collapsed back into a
    uniform one (at the i-end's value) the moment a member carrying one was
    split by an embedded node. Each segment must instead carry its own local
    slice of the linearly-varying load."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(8.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.add_member_midpoint_node(member)  # splits the member at fraction 0.5
    canvas.selected_elements = {member}
    canvas.apply_uniform_load_to_selection((0.0, 0.0, 0.0, -20.0))  # 0 at i -> -20 at j

    model = canvas.build_model()
    assert len(model.elements) == 2
    loads_by_tag = {load.element_tag: load for load in model.element_loads}
    assert len(loads_by_tag) == 2

    # build_model() keeps the original tag for the first segment (fraction
    # 0.0->0.5 of the original member) and mints a new tag for the second
    # (0.5->1.0), so each one's i/j values must be the load interpolated at
    # its own pair of fractions, not the whole member's i/j values copied twice.
    first, second = loads_by_tag[member], next(
        load for tag, load in loads_by_tag.items() if tag != member
    )
    assert first.wy == pytest.approx(0.0)
    assert first.wy_j == pytest.approx(-10.0)
    assert second.wy == pytest.approx(-10.0)
    assert second.wy_j == pytest.approx(-20.0)


def test_self_weight_is_off_by_default_and_absent_from_the_solved_model() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    assert canvas.include_self_weight is False
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.elements[member].properties["A"] = 2.0
    canvas.elements[member].properties["density"] = 1.0

    model = canvas.build_model()
    assert model.element_loads == []


def test_self_weight_reactions_match_hand_calculation_for_a_horizontal_beam() -> None:
    """Simply-supported horizontal beam, L=4, A=2, density=1 -> total weight
    w*L = 2*4 = 8, split evenly by symmetry: 4 at each support, matching the
    textbook simply-supported-UDL reaction R = wL/2."""
    from openframe.features.analysis.statics import MaterialFreeStaticsSolver

    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.set_support(left, (True, True, False))
    canvas.set_support(right, (False, True, False))
    canvas.elements[member].properties["A"] = 2.0
    canvas.elements[member].properties["density"] = 1.0
    canvas.include_self_weight = True

    result = MaterialFreeStaticsSolver().solve(canvas.build_model())
    assert result.status.value == "completed"
    reactions = {tag: node.reaction for tag, node in result.node_results.items()}
    assert reactions[left] == pytest.approx((0.0, 4.0, 0.0), abs=1e-9)
    assert reactions[right] == pytest.approx((0.0, 4.0, 0.0), abs=1e-9)


def test_self_weight_on_a_vertical_column_is_pure_axial_with_no_bending() -> None:
    """A column's own weight acts along its own centroidal axis, so a
    cantilever column under self-weight alone should show zero moment and
    zero horizontal reaction at its base - the total weight (density*A*L =
    1*2*3 = 6) shows up entirely as vertical reaction."""
    from openframe.features.analysis.statics import MaterialFreeStaticsSolver

    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    base = canvas.add_node(0.0, 0.0)
    top = canvas.add_node(0.0, 3.0)
    member = canvas.add_member(base, top)
    canvas.set_support(base, (True, True, True))
    canvas.elements[member].properties["A"] = 2.0
    canvas.elements[member].properties["density"] = 1.0
    canvas.include_self_weight = True

    result = MaterialFreeStaticsSolver().solve(canvas.build_model())
    assert result.status.value == "completed"
    reaction = result.node_results[base].reaction
    assert reaction == pytest.approx((0.0, 6.0, 0.0), abs=1e-9)


def test_self_weight_requires_both_density_and_area_or_is_silently_skipped() -> None:
    """A member with no density set (the common case, since density defaults
    to nothing) must not contribute a phantom load just because the global
    checkbox is on - only members that actually opted in via the section
    panel's density field participate."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    canvas.add_member(left, right)
    canvas.include_self_weight = True

    model = canvas.build_model()
    assert model.element_loads == []


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
