import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from _solve_helpers import solve_and_wait, solve_modal_and_wait
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
    solve_and_wait(page)

    assert page.workspace_stack.currentIndex() == 1
    assert page.viewport._result.node_results[left].reaction[1] == pytest.approx(20.0)
    assert page.viewport._result.node_results[right].reaction[1] == pytest.approx(20.0)


def test_global_x_uniform_load_on_a_vertical_cantilever_has_global_reactions() -> None:
    """GLOBAL qX must remain horizontal through UI conversion and solve."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas
    assert application is QApplication.instance()

    base = canvas.add_node(0.0, 0.0)
    top = canvas.add_node(0.0, 4.0)
    column = canvas.add_member(base, top)
    canvas.set_support(base, (True, True, True))
    canvas.selected_elements = {column}
    canvas.apply_uniform_load_to_selection(
        (5.0, 0.0), coordinate_system="global"
    )

    solve_and_wait(page)

    reaction = page.viewport._result.node_results[base].reaction
    assert reaction[0] == pytest.approx(-20.0)
    assert reaction[1] == pytest.approx(0.0, abs=1.0e-10)
    assert reaction[2] == pytest.approx(40.0)


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

    solve_and_wait(page)

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


def test_a_slight_leftward_jitter_during_a_mostly_vertical_drag_stays_in_window_mode() -> None:
    """Regression test: the window/crossing decision used to compare raw
    scene-space x coordinates with no tolerance, so a drag meant to go
    straight down - which in practice almost never has an exactly-zero
    horizontal delta - could flip into crossing mode from a single pixel of
    hand tremor and start sweeping in members the box only grazed, not just
    the nodes the user meant to box. Reported as "위에서 아래로 드래그하면
    노드만 선택돼야 하는데 부재까지 같이 선택됨"."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    start = QPointF(0.0, 0.0)
    tiny_leftward_jitter = QPointF(-1.0, 200.0)
    assert canvas._is_crossing_drag(start, tiny_leftward_jitter) is False

    deliberate_left_drag = QPointF(-20.0, 200.0)
    assert canvas._is_crossing_drag(start, deliberate_left_drag) is True

    # End-to-end: a horizontal member straddling a thin, almost-vertical
    # selection box (crossed, not enclosed) must stay unselected once the
    # jitter no longer flips the drag into crossing mode.
    scale = canvas._DRAW_SCALE
    left = canvas.add_node(-5.0, 0.0)
    right = canvas.add_node(5.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.selection_filter = "elements"
    box_start = QPointF(-2.0 * scale, -6.0 * scale)
    box_end = QPointF(-1.0 * scale, 6.0 * scale)
    thin_vertical_box = QRectF(box_start, box_end).normalized()

    canvas._select_in_rect(
        thin_vertical_box, crossing=canvas._is_crossing_drag(box_start, box_end)
    )

    assert member not in canvas.selected_elements


def test_clicking_a_filtered_out_item_preserves_the_current_selection() -> None:
    """Regression test: _toggle_selection used to clear the current selection
    *before* checking whether the clicked item even passed the active
    selection_filter, so clicking the wrong kind of item (e.g. a node while
    something had narrowed the filter to elements-only) silently wiped out a
    perfectly valid member selection instead of just being ignored - reported
    as "부재를 선택해 둔 채로 노드를 클릭했더니 선택이 없어짐"."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.selected_elements = {member}
    canvas.selection_filter = "elements"

    canvas._toggle_selection(("node", left), Qt.KeyboardModifier.NoModifier)

    assert canvas.selected_elements == {member}
    assert canvas.selected_nodes == set()


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


def test_midpoint_snap_splits_the_visible_member_into_two_independent_pieces() -> None:
    """부재 위 노드 삽입 (here via the explicit midpoint shortcut) now splits
    the member for real, immediately - not just an analysis-time embedded
    point (canvas_geometry.py's _add_node_at) - so canvas.elements and the
    built model agree on the member count, and a point load at the new joint
    still reaches it correctly either way."""
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
    assert len(canvas.elements) == 2
    assert len(model.elements) == 2
    assert all(middle in {element.node_i, element.node_j} for element in model.elements.values())
    assert model.metadata["hinge_nodes"] == ""
    assert model.metadata["logical_member_count"] == "2"
    assert model.metadata["embedded_nodes"] == ""
    assert check_determinacy(model).degree == 0


def test_splitting_a_member_that_carries_a_trapezoidal_load_interpolates_each_new_piece() -> None:
    """Regression coverage for the same interpolation math this test always
    checked, now exercised where it actually happens - _split_element_at,
    called the moment an already-loaded member is explicitly split - instead
    of build_model()'s segment-splitting path, which this scenario no longer
    reaches (there is nothing left embedded to split at build time). Each new
    piece must carry its own local slice of the linearly-varying load, not a
    copy of the whole original span's i-end value."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(8.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.selected_elements = {member}
    canvas.apply_uniform_load_to_selection((0.0, 0.0, 0.0, -20.0))  # 0 at i -> -20 at j

    canvas.add_member_midpoint_node(member)  # splits the member at fraction 0.5

    assert len(canvas.elements) == 2
    assert len(canvas.element_loads) == 2
    first, second = canvas.element_loads[member], next(
        load for tag, load in canvas.element_loads.items() if tag != member
    )
    assert first.wy == pytest.approx(0.0)
    assert first.wy_j == pytest.approx(-10.0)
    assert second.wy == pytest.approx(-10.0)
    assert second.wy_j == pytest.approx(-20.0)

    # End to end: build_model() has nothing left embedded to split further,
    # so it must simply carry the two already-split loads through unchanged.
    model = canvas.build_model()
    assert len(model.element_loads) == 2


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


def test_rotate_copy_places_new_nodes_at_the_correct_angle_and_reproduces_members() -> None:
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas

    assert application is QApplication.instance()
    left = canvas.add_node(1.0, 0.0)
    right = canvas.add_node(2.0, 0.0)
    canvas.add_member(left, right)
    canvas.selected_nodes = {left, right}

    created_members = canvas.rotate_copy_selection(0.0, 0.0, 90.0, 2)

    assert created_members == 2
    assert len(canvas.nodes) == 6
    assert len(canvas.elements) == 3
    positions = {(round(n.x, 6), round(n.y, 6)) for n in canvas.nodes.values()}
    assert (0.0, 1.0) in positions  # (1,0) rotated 90 deg
    assert (0.0, 2.0) in positions  # (2,0) rotated 90 deg
    assert (-1.0, 0.0) in positions  # (1,0) rotated 180 deg
    assert (-2.0, 0.0) in positions  # (2,0) rotated 180 deg


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
    """Splitting a member via 부재 위 노드 삽입/등분할 is one undo step, same
    as everything else _add_node_at can trigger - undo must restore the
    original single element, not leave a half-split state behind."""
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
    assert not canvas.embedded_nodes
    assert len(canvas.elements) == 2
    middle = next(tag for tag in canvas.nodes if tag not in (left, right))
    spans = {(el.node_i, el.node_j) for el in canvas.elements.values()}
    assert spans == {(left, middle), (middle, right)}

    canvas.undo()
    assert len(canvas.nodes) == 2
    assert not canvas.embedded_nodes
    assert len(canvas.elements) == 1


def test_arbitrary_member_station_accepts_a_point_load_without_instability() -> None:
    """A point load at an inserted station lands on a real, independent node
    whether the member it came from stays whole or gets split for real
    (canvas_geometry.py's _add_node_at) - the split must not introduce any
    spurious instability, and reactions for this determinate beam must come
    out exactly as equilibrium alone dictates either way."""
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
    assert len(canvas.elements) == 2
    assert len(model.elements) == 2
    assert canvas.nodes[load_node].x == pytest.approx(3.0)
    assert check_determinacy(model).degree == 0
    solve_and_wait(page)
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


def test_node_transform_tool_activates_select_mode_without_narrowing_the_filter() -> None:
    """Move/copy/array/rotate/mirror all understand a selected *member* now (its
    two endpoints move/copy along with it - MIDAS's separate Node/Element
    move-copy mode), so activating the tool must leave whatever filter
    (전체/노드만/부재만) the user already had, unlike the support tool below."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()

    assert application is QApplication.instance()
    page._activate_node_transform_tool()
    assert page.canvas.mode == "select"
    assert page.canvas.selection_filter == "all"


def test_modal_solve_button_runs_an_eigenvalue_analysis_on_a_real_material_cantilever() -> None:
    """End-to-end through the actual UI trigger (solve_modal), not just the
    solver directly - a cantilever with a real section/material and nonzero
    density (so it has both stiffness and mass), matching this app's own
    apply_section_to_selection API a user would actually click through."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas
    base = canvas.add_node(0.0, 0.0)
    tip = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(base, tip)
    canvas.set_support(base, (True, True, True))
    canvas.selected_elements = {member}
    canvas.apply_section_to_selection(width=0.3, height=0.5, elastic=200_000.0, density=10.0)

    solve_modal_and_wait(page)

    assert application is QApplication.instance()
    assert page.workspace_stack.currentIndex() == 1
    result = page.viewport._result
    assert result.status.value == "completed"
    assert len(result.mode_shapes) == page.modal_num_modes.value()
    assert all(mode.angular_frequency > 0.0 for mode in result.mode_shapes)
    # Ascending order: fundamental (softest, longest period) mode first.
    periods = [mode.period for mode in result.mode_shapes]
    assert periods == sorted(periods, reverse=True)


def test_modal_solve_button_reports_missing_material_without_a_popup() -> None:
    """No section/density applied - the same everyday-not-an-error philosophy
    solve() already has for an indeterminate structure with no material."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas
    base = canvas.add_node(0.0, 0.0)
    tip = canvas.add_node(4.0, 0.0)
    canvas.add_member(base, tip)
    canvas.set_support(base, (True, True, True))

    solve_modal_and_wait(page)

    assert application is QApplication.instance()
    assert page.workspace_stack.currentIndex() == 0
    assert "재료" in page.determinacy_status.text()


def test_pdelta_toggle_amplifies_deflection_on_a_real_material_cantilever() -> None:
    """End-to-end through the actual UI trigger (solve(), not the solver
    directly): a cantilever with real section/material carrying a lateral load
    plus a large compressive axial load - the pdelta_toggle checkbox must
    change the result (larger deflection than the linear solve), and toggling
    it off again must reproduce the exact linear result."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas
    base = canvas.add_node(0.0, 0.0)
    tip = canvas.add_node(0.0, 4.0)
    member = canvas.add_member(base, tip)
    canvas.set_support(base, (True, True, True))
    canvas.selected_elements = {member}
    canvas.apply_section_to_selection(width=0.3, height=0.5, elastic=200_000.0)
    canvas.set_nodal_load(tip, (1.0, -2.0, 0.0))

    solve_and_wait(page)
    linear_ux = page.viewport._result.node_results[tip].displacement[0]

    page.pdelta_toggle.setChecked(True)
    solve_and_wait(page)

    assert application is QApplication.instance()
    result = page.viewport._result
    assert result.status.value == "completed"
    assert result.node_results[tip].displacement[0] > linear_ux

    page.pdelta_toggle.setChecked(False)
    solve_and_wait(page)
    assert page.viewport._result.node_results[tip].displacement[0] == pytest.approx(
        linear_ux, abs=1.0e-9
    )


def test_export_button_writes_a_runnable_script_and_emits_its_path(tmp_path: Path) -> None:
    """End-to-end through the actual UI trigger, matching how solve_modal's
    equivalent test works - a cantilever with a real section/material (the
    canvas's own solvers stop at determinate statics/eigenvalue analysis, so
    this is the only way a hand-drawn model reaches nonlinear static/time
    history: exported as a script and handed to the "OpenSeesPy 파일 불러오기"
    pipeline, which this signal is the hand-off point for)."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas
    base = canvas.add_node(0.0, 0.0)
    tip = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(base, tip)
    canvas.set_support(base, (True, True, True))
    canvas.selected_elements = {member}
    canvas.apply_section_to_selection(width=0.3, height=0.5, elastic=200_000.0, density=10.0)

    destination = tmp_path / "exported.py"
    exported_paths: list[Path] = []
    page.analysis_script_exported.connect(exported_paths.append)

    with patch(
        "openframe.features.model.presentation.modeling_interface_page.QFileDialog.getSaveFileName",
        return_value=(str(destination), "Python 파일 (*.py)"),
    ):
        page.export_analysis_button.click()

    assert application is QApplication.instance()
    assert exported_paths == [destination]
    script = destination.read_text(encoding="utf-8")
    assert "ops.model('basic', '-ndm', 2" in script
    assert f"ops.node({base}, 0.0, 0.0)" in script
    assert f"ops.node({tip}, 4.0, 0.0)" in script
    assert "내보내기 완료" in page.determinacy_status.text()


def test_export_button_reports_missing_material_without_opening_a_dialog() -> None:
    """No section applied - same everyday-not-an-error philosophy solve_modal's
    missing-material test already covers. The file dialog must never open for
    a model that cannot be exported, so patching it is deliberately omitted -
    the dialog would raise (or hang) here if the guard were ever removed."""
    application = QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    canvas = page.canvas
    base = canvas.add_node(0.0, 0.0)
    tip = canvas.add_node(4.0, 0.0)
    canvas.add_member(base, tip)
    canvas.set_support(base, (True, True, True))

    exported_paths: list[Path] = []
    page.analysis_script_exported.connect(exported_paths.append)

    page.export_analysis_button.click()

    assert application is QApplication.instance()
    assert exported_paths == []
    assert "내보내기 실패" in page.determinacy_status.text()
    assert "E/A/I" in page.determinacy_status.text()
