import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from _solve_helpers import solve_and_wait
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from openframe.features.analysis.statics import check_determinacy
from openframe.features.model.drawing import PlaneKind
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
    page.show()
    return page


def test_one_chain_of_clicks_creates_both_nodes_and_members() -> None:
    canvas = _canvas()

    canvas.place_point(0.0, 0.0)
    canvas.place_point(0.0, 4.0)
    canvas.place_point(5.0, 4.0)

    assert len(canvas.nodes) == 3
    assert len(canvas.elements) == 2
    assert canvas.is_drawing is True
    assert canvas.chain_anchor == pytest.approx((5.0, 4.0))


def test_add_arch_places_endpoints_and_crown_on_a_circular_arc() -> None:
    """The whole point is that a user only ever types span + rise, not a
    radius - so what actually gets verified here is that the generated
    facet nodes are truly points on the circle those two numbers imply:
    both span endpoints back at (start_x, start_y)/(start_x+span, start_y),
    and the midspan node exactly ``rise`` above the chord."""
    canvas = _canvas()

    created = canvas.add_arch(start_x=0.0, start_y=0.0, span=8.0, rise=1.6, segments=12)

    assert len(created) == 13  # segments + 1 nodes
    assert len(canvas.elements) == 12
    start_node = canvas.nodes[created[0]]
    end_node = canvas.nodes[created[-1]]
    assert (start_node.x, start_node.y) == pytest.approx((0.0, 0.0))
    assert (end_node.x, end_node.y) == pytest.approx((8.0, 0.0))
    crown = canvas.nodes[created[6]]  # segments/2 -> midspan
    assert (crown.x, crown.y) == pytest.approx((4.0, 1.6))
    # Every generated element joins two consecutive facet nodes - a simple
    # open chain, not e.g. a closed loop or skipped points.
    for element, node_i, node_j in zip(canvas.elements.values(), created, created[1:]):
        assert (element.node_i, element.node_j) == (node_i, node_j)


def test_add_arch_selects_the_generated_nodes() -> None:
    canvas = _canvas()

    created = canvas.add_arch(start_x=0.0, start_y=0.0, span=6.0, rise=1.0, segments=6)

    assert canvas.selected_nodes == set(created)
    assert not canvas.selected_elements


def test_add_arch_rejects_a_non_positive_span_or_too_few_segments() -> None:
    canvas = _canvas()

    assert canvas.add_arch(start_x=0.0, start_y=0.0, span=0.0, rise=1.0, segments=8) == ()
    assert canvas.add_arch(start_x=0.0, start_y=0.0, span=8.0, rise=1.0, segments=0) == ()
    assert not canvas.nodes


def test_add_arch_falls_back_to_a_straight_chord_when_rise_is_zero() -> None:
    """A zero/negative rise has no circle to fit (division by zero in the
    circular-segment formula) - rather than reject the call outright, this
    degrades to evenly spaced points on the straight chord."""
    canvas = _canvas()

    created = canvas.add_arch(start_x=0.0, start_y=2.0, span=4.0, rise=0.0, segments=4)

    ys = {round(canvas.nodes[tag].y, 9) for tag in created}
    assert ys == {2.0}


def test_escape_ends_the_chain_so_the_next_click_starts_a_new_run() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(2.0, 0.0)

    canvas.end_chain()
    canvas.place_point(6.0, 0.0)

    assert canvas.is_drawing is True
    assert len(canvas.nodes) == 3
    assert len(canvas.elements) == 1


def test_escape_in_draw_mode_requests_a_return_to_select_instead_of_just_clearing() -> None:
    """Pressing Escape while a chain is open used to only clear the chain and
    leave the draw tool active, so getting back to selecting meant reaching for
    the 선택 button too. One Escape should be enough."""
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 0.0)
    requests: list[None] = []
    canvas.escape_requested.connect(lambda: requests.append(None))

    canvas.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))

    assert requests, "escape_requested must fire while the draw tool is active"
    assert canvas.mode == "draw", "the canvas itself does not switch modes — the page does, via the signal"


def test_escape_outside_draw_mode_still_just_clears_a_pending_preview() -> None:
    canvas = _canvas()
    canvas.set_mode("select")
    requests: list[None] = []
    canvas.escape_requested.connect(lambda: requests.append(None))

    canvas.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))

    assert not requests


def test_axis_lines_span_the_visible_rect_when_the_origin_is_in_view() -> None:
    x_axis, y_axis = StaticsDrawingCanvas.axis_lines((-100.0, -50.0, 100.0, 50.0), (0.0, 0.0))

    assert x_axis == (-100.0, 0.0, 100.0, 0.0)
    assert y_axis == (0.0, -50.0, 0.0, 50.0)


def test_axis_lines_omit_an_axis_panned_off_screen() -> None:
    """After panning far from the origin, the X or Y line should not still be
    drawn at some meaningless coordinate outside the visible rect."""
    x_axis, y_axis = StaticsDrawingCanvas.axis_lines((500.0, 500.0, 700.0, 600.0), (0.0, 0.0))

    assert x_axis is None
    assert y_axis is None


def test_axis_lines_follow_the_active_work_planes_local_origin() -> None:
    """A front elevation plane's local origin is a different point than the
    ground plan's — the axes must track whichever plane is active, not always
    global (0, 0)."""
    canvas = _canvas()
    canvas.enter_3d_mode()
    front = canvas.add_level(2.0, "front", kind=PlaneKind.XZ)
    canvas.set_active_plane(front)

    origin_scene = canvas._scene_point(0.0, 0.0)
    x_axis, _ = canvas.axis_lines((-1000.0, -1000.0, 1000.0, 1000.0), (origin_scene.x(), origin_scene.y()))

    assert x_axis == (-1000.0, origin_scene.y(), 1000.0, origin_scene.y())


def test_typed_polar_entry_draws_a_gable_frame_with_its_sloped_rafters() -> None:
    """The shape that clicking cannot reach: 5 m half span rising 2 m each side."""
    canvas = _canvas()

    canvas.place_point(0.0, 0.0)
    assert canvas.commit_entry("0,4") is True
    assert canvas.commit_entry("5.385<21.8") is True
    assert canvas.commit_entry("5.385<-21.8") is True
    assert canvas.commit_entry("@0,-4") is True

    apex = canvas.nodes[canvas.elements[2].node_j]
    eaves = canvas.nodes[canvas.elements[3].node_j]
    assert (apex.x, apex.y) == pytest.approx((5.0, 6.0), abs=1.0e-3)
    assert (eaves.x, eaves.y) == pytest.approx((10.0, 4.0), abs=1.0e-3)
    assert len(canvas.elements) == 4


def test_a_rejected_entry_leaves_the_model_untouched() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)

    assert canvas.commit_entry("나중에") is False
    assert canvas.commit_entry("4<") is False
    assert len(canvas.nodes) == 1
    assert canvas.elements == {}


def test_drawing_onto_an_existing_node_reuses_it_instead_of_stacking_a_duplicate() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 0.0)
    canvas.end_chain()

    canvas.place_point(4.0, 3.0)
    snap = canvas.snap_at(4.02, 0.01)
    canvas.place_point(snap.x, snap.y, snap=snap)

    assert len(canvas.nodes) == 3
    assert len(canvas.elements) == 2


def test_drawing_across_a_member_lands_on_it_and_splits_it_for_real() -> None:
    """Starting a new chain point on an existing member is a deliberate
    request for a joint there (unlike drawing a brand-new member *through* an
    already-existing, unrelated node - see test_collinear_node_is_auto_
    attached_without_splitting_the_visible_member) - it splits the member
    into two independent elements immediately, not just an analysis-time
    embedded point."""
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 0.0)
    canvas.end_chain()

    snap = canvas.snap_at(1.4, 0.03)
    tag = canvas.place_point(snap.x, snap.y, snap=snap)

    assert tag not in canvas.embedded_nodes
    assert canvas.nodes[tag].x == pytest.approx(1.4)
    assert len(canvas.elements) == 2
    assert len(canvas.build_model().elements) == 2


def test_one_click_is_one_undo_step_even_when_it_adds_a_node_and_a_member() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(3.0, 0.0)

    canvas.undo()

    assert len(canvas.nodes) == 1
    assert canvas.elements == {}


def test_live_readout_reports_the_length_and_angle_of_the_pending_member() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 4.0)
    canvas._snap = canvas.snap_at(5.0, 6.0)

    length, angle = canvas.pending_length_and_angle()

    assert length == pytest.approx(5.385, abs=1.0e-3)
    assert angle == pytest.approx(21.8, abs=0.1)


def test_uniform_load_arrows_stand_perpendicular_to_a_sloped_rafter() -> None:
    from openframe.core.domain import Node, UniformElementLoad

    start = Node(1, 0.0, 4.0)
    end = Node(2, 5.0, 6.0)
    load = UniformElementLoad(1, wy=-8.0)

    segments = StaticsDrawingCanvas.load_arrow_segments(start, end, load, reach=1.0)

    tail, tip, _ = segments[0]
    arrow = (tip[0] - tail[0], tip[1] - tail[1])
    member = (end.x - start.x, end.y - start.y)
    assert arrow[0] * member[0] + arrow[1] * member[1] == pytest.approx(0.0, abs=1.0e-9)
    assert arrow[1] < 0.0


def test_uniform_load_on_a_horizontal_beam_still_points_straight_down() -> None:
    from openframe.core.domain import Node, UniformElementLoad

    segments = StaticsDrawingCanvas.load_arrow_segments(
        Node(1, 0.0, 0.0), Node(2, 4.0, 0.0), UniformElementLoad(1, wy=-10.0), reach=1.0
    )

    tail, tip, _ = segments[0]
    assert (tip[0] - tail[0]) == pytest.approx(0.0)
    assert (tip[1] - tail[1]) == pytest.approx(-1.0)


def test_member_end_release_is_independent_of_node_level_hinges() -> None:
    canvas = _canvas()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)

    canvas.set_member_end_release(member, "i", True)

    assert canvas.elements[member].moment_release_i is True
    assert canvas.elements[member].moment_release_j is False
    model = canvas.build_model()
    assert model.elements[member].moment_release_i is True


def test_member_end_release_lands_on_the_outer_segment_after_a_station_split() -> None:
    """Splitting a member for a mid-span support must not swallow its end release."""
    canvas = _canvas()
    left = canvas.add_node(0.0, 0.0)
    right = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(left, right)
    canvas.set_member_end_release(member, "j", True)

    canvas.add_member_station_node(member, 0.5)

    model = canvas.build_model()
    segments = [element for element in model.elements.values()]
    assert len(segments) == 2
    releases = {element.tag: (element.moment_release_i, element.moment_release_j) for element in segments}
    # The original member tag keeps the i-end (unreleased); the new far segment
    # carries the j-end release that was drawn on the whole member.
    assert releases[member] == (False, False)
    far_segment = next(tag for tag in releases if tag != member)
    assert releases[far_segment] == (False, True)


def _wheel(delta: int, x: float = 120.0, y: float = 90.0) -> QWheelEvent:
    point = QPointF(x, y)
    return QWheelEvent(
        point,
        point,
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_wheel_zoom_keeps_the_point_under_the_cursor_fixed_while_drawing() -> None:
    """Regression test: our mouseMoveEvent override returns early in draw mode
    without reaching QGraphicsView's own implementation, which is what
    AnchorUnderMouse alone depends on to know where the cursor is — so zooming
    while the draw tool is active used to re-centre on the viewport instead of
    the cursor. Qt's own scrollbar-based panning only lands on whole scrollbar
    steps, so a small sub-pixel residual is expected and does not accumulate —
    only a large jump (the actual bug) should fail this.
    """
    canvas = _canvas()
    canvas.resize(400, 300)
    canvas.show()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(6.0, 0.0)
    canvas.fit_model()
    cursor = QPoint(120, 90)

    before = canvas.mapToScene(cursor)
    canvas.wheelEvent(_wheel(120, cursor.x(), cursor.y()))
    after = canvas.mapToScene(cursor)

    assert (after.x(), after.y()) == pytest.approx((before.x(), before.y()), abs=1.5)


def test_wheel_zoom_out_also_keeps_the_cursor_point_fixed() -> None:
    canvas = _canvas()
    canvas.resize(400, 300)
    canvas.show()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(6.0, 0.0)
    canvas.fit_model()
    cursor = QPoint(200, 60)

    before = canvas.mapToScene(cursor)
    canvas.wheelEvent(_wheel(-120, cursor.x(), cursor.y()))
    after = canvas.mapToScene(cursor)

    assert (after.x(), after.y()) == pytest.approx((before.x(), before.y()), abs=1.5)


def test_repeated_wheel_zoom_does_not_drift_the_cursor_anchor() -> None:
    """The small per-step quantization noise must stay bounded, not compound
    into a visible drift after many scroll notches."""
    canvas = _canvas()
    canvas.resize(400, 300)
    canvas.show()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(6.0, 0.0)
    canvas.fit_model()
    cursor = QPoint(150, 100)

    start = canvas.mapToScene(cursor)
    for _ in range(10):
        canvas.wheelEvent(_wheel(120, cursor.x(), cursor.y()))
    end = canvas.mapToScene(cursor)

    assert (end.x(), end.y()) == pytest.approx((start.x(), start.y()), abs=2.0)


def test_the_origin_axes_do_not_inflate_fit_models_bounding_rect() -> None:
    """The axes are painted in drawBackground, not added as scene items — if
    they were ever turned into QGraphicsItems instead, itemsBoundingRect() would
    include their huge span and fit_model() would zoom out to nothing."""
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 3.0)
    canvas.end_chain()

    bounds = canvas.scene_model.itemsBoundingRect()

    assert bounds.width() < 1000
    assert bounds.height() < 1000


def test_fit_model_recentres_the_view_after_the_structure_is_scrolled_off_screen() -> None:
    canvas = _canvas()
    canvas.resize(400, 300)
    canvas.show()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(6.0, 4.0)
    canvas.end_chain()

    canvas.centerOn(QPointF(50_000.0, 50_000.0))  # scroll far away, as if lost
    lost_center = canvas.mapToScene(canvas.viewport().rect().center())
    assert abs(lost_center.x()) > 1000  # confirm we really did get lost first

    canvas.fit_model()

    recovered_center = canvas.mapToScene(canvas.viewport().rect().center())
    # The model spans x in [0, 6] and y in [-4, 0] (scene y is flipped), so its
    # midpoint is near (3, -2); fit_model should bring the view back near there.
    assert recovered_center.x() == pytest.approx(3.0 * canvas._DRAW_SCALE, abs=200.0)


def test_a_hinge_marker_is_visually_distinct_from_a_rigid_node_not_just_a_colour_change() -> None:
    """Regression test: _redraw used to set a hinge-coloured pen and then
    unconditionally overwrite it with the plain blue pen right after, so a
    hinge rendered as an ordinary node with a slightly bigger, hollow outline —
    easy to miss entirely. A hinge must be a different symbol (ring + pin dot),
    not a subtler shade of the regular filled dot."""
    from PySide6.QtWidgets import QGraphicsEllipseItem

    canvas = _canvas()
    rigid = canvas.place_point(0.0, 0.0)
    hinge = canvas.place_point(4.0, 0.0)
    canvas.selected_nodes = {hinge}
    canvas.set_selected_node_kind(True)
    canvas.selected_nodes.clear()
    canvas._redraw()

    ellipses = [
        item
        for item in canvas.scene_model.items()
        if isinstance(item, QGraphicsEllipseItem) and item.data(0) == ("node", hinge)
    ]
    assert len(ellipses) == 2, "a hinge draws two parts: the ring and the pin dot"
    pen_colors = {item.pen().color().name() for item in ellipses}
    assert "#f97316" in pen_colors, "the ring must actually carry the hinge accent colour"

    rigid_ellipses = [
        item
        for item in canvas.scene_model.items()
        if isinstance(item, QGraphicsEllipseItem) and item.data(0) == ("node", rigid)
    ]
    assert len(rigid_ellipses) == 1
    assert rigid_ellipses[0].pen().color().name() == "#174ea6"


def test_a_hinge_node_is_labelled_as_a_joint_on_the_canvas_itself() -> None:
    """The scene label, not just the property panel, must say 절점 for a hinge —
    a student scanning the drawing should not have to select a node to learn
    it is a hinge."""
    from PySide6.QtWidgets import QGraphicsTextItem

    canvas = _canvas()
    rigid = canvas.place_point(0.0, 0.0)
    hinge = canvas.place_point(4.0, 0.0)
    canvas.selected_nodes = {hinge}
    canvas.set_selected_node_kind(True)

    labels = {
        item.toPlainText()
        for item in canvas.scene_model.items()
        if isinstance(item, QGraphicsTextItem)
    }
    assert f"절점{hinge}" in labels
    assert f"N{rigid}" in labels
    assert f"N{hinge}" not in labels


def test_an_inclined_nodal_load_draws_one_combined_arrow_not_two_crossed_ones() -> None:
    """Fx and Fy both nonzero (e.g. from 부재 수직 입력) is one inclined force,
    not two independent ones - drawing it as two separate axis-aligned
    Fx/Fy arrows crossing at the node used to look like unrelated clutter
    rather than one inclined load. The label reads as magnitude+angle, not
    raw Fx/Fy, since the user typing a load never sees Fx/Fy either (see
    _build_perpendicular_load_fields)."""
    from PySide6.QtWidgets import QGraphicsTextItem

    canvas = _canvas()
    node = canvas.place_point(0.0, 0.0)
    canvas.selected_nodes = {node}
    canvas.apply_nodal_load_to_selection((-5.14137, 8.57708, 0.0))

    labels = {
        item.toPlainText()
        for item in canvas.scene_model.items()
        if isinstance(item, QGraphicsTextItem)
    }
    load_labels = {label for label in labels if label.startswith("P ")}
    assert load_labels == {"P 10 ∠120.9°"}


def test_load_fields_show_a_dashed_preview_before_apply_is_clicked() -> None:
    """Typing Fx/Fy (directly, or via 크기·각도) must show the arrow
    immediately, not only after 적용 — otherwise a wrong angle is only
    discovered after it is already committed."""
    from PySide6.QtWidgets import QGraphicsTextItem

    page = _page()
    node = page.canvas.add_node(0.0, 0.0)
    page.canvas.selected_nodes = {node}
    page.canvas.selection_changed.emit()

    page.load_fields["fx"].setValue(3.0)
    page.load_fields["fy"].setValue(4.0)

    assert page.canvas._pending_load_preview == ({node}, (3.0, 4.0, 0.0))
    labels = {
        item.toPlainText()
        for item in page.canvas.scene_model.items()
        if isinstance(item, QGraphicsTextItem)
    }
    assert any("미적용" in label for label in labels)
    # 적용 commits it and the preview - now redundant with the real arrow -
    # is cleared rather than left drawn on top of it.
    page._apply_load()
    assert page.canvas._pending_load_preview is None
    assert page.canvas.nodal_loads[node].values == (3.0, 4.0, 0.0)


def test_magnitude_and_angle_live_update_fx_fy_without_a_separate_convert_click() -> None:
    """Fx·Fy로 변환 used to be a manual step easy to forget, leaving 적용 to
    silently save zero - 크기/각도 now sync into Fx/Fy on every edit."""
    page = _page()
    page.load_mode_toggle.setChecked(True)

    page.load_magnitude.setValue(10.0)
    page.load_angle.setValue(30.0)

    assert page.load_fields["fx"].value() == pytest.approx(10.0 * math.cos(math.radians(30.0)))
    assert page.load_fields["fy"].value() == pytest.approx(10.0 * math.sin(math.radians(30.0)))


def test_the_draw_tool_and_its_entry_field_are_wired_to_the_canvas() -> None:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()

    page._activate_draw_tool()
    assert page.canvas.mode == "draw"

    page.draw_entry.setText("0,0")
    page._commit_draw_entry()
    page.draw_entry.setText("4<60")
    page._commit_draw_entry()

    assert page.draw_entry.text() == ""
    assert len(page.canvas.nodes) == 2
    assert len(page.canvas.elements) == 1
    assert page.canvas.chain_anchor == pytest.approx((2.0, 3.4641), abs=1.0e-3)

    page.draw_entry.setText("가나다")
    page._commit_draw_entry()
    assert "인식하지 못했습니다" in page.draw_readout.text()
    assert len(page.canvas.nodes) == 2


def test_ortho_lock_from_the_toolbar_reaches_the_canvas() -> None:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage()
    page._activate_draw_tool()

    page.ortho_lock.setChecked(True)
    page.ortho_increment.setCurrentIndex(page.ortho_increment.findData(45.0))

    assert page.canvas.ortho is True
    assert page.canvas.ortho_increment == pytest.approx(45.0)


def test_mirroring_half_a_gable_frame_reconnects_at_the_shared_apex() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.commit_entry("0,4")
    canvas.commit_entry("5,6")  # absolute: the apex must land exactly on x=5 to reconnect
    canvas.end_chain()
    apex = canvas.elements[2].node_j
    canvas.selected_nodes = set(canvas.nodes)

    created = canvas.mirror_selection("x", 5.0)

    assert created == 3
    assert len(canvas.nodes) == 5
    assert len(canvas.elements) == 4
    apex_uses = sum(
        1 for element in canvas.elements.values() if apex in (element.node_i, element.node_j)
    )
    assert apex_uses == 2, "both the original and mirrored rafter must meet at the one apex node"
    right_eave = canvas.nodes[canvas.elements[4].node_i]
    assert (right_eave.x, right_eave.y) == pytest.approx((10.0, 4.0), abs=1.0e-9)


def test_mirroring_notifies_the_page_so_its_panel_can_follow_the_new_selection() -> None:
    """A stale panel that still shows the pre-mirror selection is a real bug this
    guards against: the page only learns about a selection change through the
    signal, never by polling."""
    canvas = _canvas()
    left = canvas.place_point(0.0, 0.0)
    right = canvas.place_point(4.0, 0.0)
    canvas.end_chain()
    canvas.selected_nodes = {left, right}
    seen: list[None] = []
    canvas.selection_changed.connect(lambda: seen.append(None))

    canvas.mirror_selection("y", 2.0)

    assert seen, "mirror_selection must emit selection_changed"
    assert canvas.selected_nodes != {left, right}


def test_node_copy_notifies_the_page_of_the_newly_created_selection() -> None:
    canvas = _canvas()
    source = canvas.place_point(0.0, 0.0)
    canvas.selected_nodes = {source}
    seen: list[None] = []
    canvas.selection_changed.connect(lambda: seen.append(None))

    canvas.transform_selected_nodes("copy", 1.0, 0.0)

    assert seen, "copying nodes must emit selection_changed"


def test_selecting_a_member_and_copying_carries_both_its_endpoints() -> None:
    """MIDAS's separate Node/Element move-copy mode: selecting the *member*
    (not its two endpoint nodes by hand) and copying must duplicate both ends
    and reconnect them - this is what "부재만" in the selection filter is for."""
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 0.0)
    canvas.end_chain()
    member = next(iter(canvas.elements))
    canvas.selected_nodes = set()
    canvas.selected_elements = {member}

    created = canvas.transform_selected_nodes("copy", 0.0, 3.0)

    assert created == 2, "both endpoints of the selected member must be copied"
    assert len(canvas.elements) == 2, "the selected member must be reconnected at the copy"
    new_member = next(tag for tag in canvas.elements if tag != member)
    new_element = canvas.elements[new_member]
    copied_left = canvas.nodes[new_element.node_i]
    copied_right = canvas.nodes[new_element.node_j]
    assert {copied_left.y, copied_right.y} == {3.0}
    assert canvas.selected_elements == {new_member}


def test_element_copy_preserves_structural_properties_and_optional_attributes() -> None:
    from openframe.core.domain import (
        BoundaryCondition,
        Element,
        NodalLoad,
        UniformElementLoad,
    )

    canvas = _canvas()
    left = canvas.place_point(0.0, 0.0)
    right = canvas.place_point(4.0, 0.0)
    canvas.end_chain()
    member = next(iter(canvas.elements))
    canvas.elements[member] = Element(
        member,
        left,
        right,
        "frame",
        properties={"E": 210_000_000.0, "A": 0.12, "section_id": "SEC-7"},
        moment_release_i=True,
        local_axis_angle=30.0,
    )
    canvas.boundaries[left] = BoundaryCondition(left, (True, True, True))
    canvas.nodal_loads[right] = NodalLoad(right, (5.0, 0.0, 0.0))
    canvas.element_loads[member] = UniformElementLoad(member, wy=-12.0)
    canvas.selected_elements = {member}

    canvas.transform_selected_nodes(
        "copy",
        0.0,
        3.0,
        copy_node_attributes=True,
        copy_element_loads=True,
    )

    copied_tag = next(tag for tag in canvas.elements if tag != member)
    copied = canvas.elements[copied_tag]
    assert copied.properties == canvas.elements[member].properties
    assert copied.properties is not canvas.elements[member].properties
    assert copied.moment_release_i is True
    assert copied.local_axis_angle == pytest.approx(30.0)
    assert canvas.element_loads[copied_tag].wy == pytest.approx(-12.0)
    assert copied.node_i in canvas.boundaries
    assert copied.node_j in canvas.nodal_loads


def test_selecting_only_nodes_still_copies_without_inventing_a_member() -> None:
    """The existing, tested plain-copy contract must survive untouched: two
    endpoint nodes picked by hand (not the member itself) copy as bare points."""
    canvas = _canvas()
    left = canvas.place_point(0.0, 0.0)
    right = canvas.place_point(4.0, 0.0)
    canvas.end_chain()
    canvas.selected_nodes = {left, right}
    canvas.selected_elements = set()

    created = canvas.transform_selected_nodes("copy", 0.0, 3.0)

    assert created == 2
    assert len(canvas.elements) == 1, "no member was selected, so none should be invented"


def test_selecting_a_member_and_moving_drags_both_its_endpoints() -> None:
    canvas = _canvas()
    left = canvas.place_point(0.0, 0.0)
    right = canvas.place_point(4.0, 0.0)
    canvas.end_chain()
    member = next(iter(canvas.elements))
    canvas.selected_nodes = set()
    canvas.selected_elements = {member}

    moved = canvas.transform_selected_nodes("move", 0.0, 2.0)

    assert moved == 2
    assert canvas.nodes[left].y == pytest.approx(2.0)
    assert canvas.nodes[right].y == pytest.approx(2.0)


def test_mirroring_without_a_selection_does_nothing() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)

    assert canvas.mirror_selection("x", 5.0) == 0
    assert len(canvas.nodes) == 1


def test_array_copy_reproduces_a_truss_panel_across_several_bays() -> None:
    canvas = _canvas()
    bottom = canvas.place_point(0.0, 0.0)
    top = canvas.place_point(0.0, 2.0)
    canvas.end_chain()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(2.0, 0.0)
    canvas.end_chain()
    canvas.selected_nodes = {bottom, top}

    created = canvas.array_copy_selection(2.0, 0.0, count=3)

    assert created == 3
    assert len(canvas.nodes) == 8
    xs = sorted({round(node.x, 6) for node in canvas.nodes.values()})
    assert xs == [0.0, 2.0, 4.0, 6.0]


def test_array_copy_with_no_selection_does_nothing() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)

    assert canvas.array_copy_selection(1.0, 0.0, count=3) == 0
    assert len(canvas.nodes) == 1


def test_subdividing_a_member_inserts_evenly_spaced_stations() -> None:
    canvas = _canvas()
    left = canvas.place_point(0.0, 0.0)
    right = canvas.place_point(6.0, 0.0)
    canvas.end_chain()
    member = canvas.elements[1]
    assert (member.node_i, member.node_j) == (left, right)

    created = canvas.subdivide_member(1, segments=3)

    assert len(created) == 2
    positions = sorted(canvas.nodes[tag].x for tag in created)
    assert positions == pytest.approx([2.0, 4.0])
    assert len(canvas.build_model().elements) == 3


def test_subdividing_with_fewer_than_two_segments_is_a_no_op() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 0.0)
    canvas.end_chain()

    assert canvas.subdivide_member(1, segments=1) == []
    assert canvas.embedded_nodes == {}


def test_a_free_form_gable_frame_reaches_the_determinacy_check() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.commit_entry("0,4")
    canvas.commit_entry("5.385<21.8")
    canvas.commit_entry("5.385<-21.8")
    canvas.commit_entry("@0,-4")
    canvas.end_chain()
    base_left = canvas.elements[1].node_i
    base_right = canvas.elements[4].node_j
    canvas.set_support(base_left, (True, True, False))
    canvas.set_support(base_right, (True, True, False))
    canvas.selected_nodes = {canvas.elements[2].node_j}
    canvas.set_selected_node_kind(True)

    assert check_determinacy(canvas.build_model()).degree == 0


def test_grid_snap_pulls_a_click_onto_the_nearest_grid_intersection() -> None:
    canvas = _canvas()
    canvas.grid = 1.0

    result = canvas.snap_at(1.03, -0.02)

    assert result.kind == "grid"
    assert (result.x, result.y) == pytest.approx((1.0, 0.0))


def test_grid_snap_toggle_off_leaves_the_raw_cursor_point_untouched() -> None:
    """The 격자 스냅 checkbox in the bottom bar has to be able to turn this off
    entirely - otherwise there is no way to place a point at an exact
    off-grid coordinate by clicking."""
    canvas = _canvas()
    canvas.grid = 1.0
    canvas.grid_snap_enabled = False

    result = canvas.snap_at(1.03, -0.02)

    assert result.kind == "free"
    assert (result.x, result.y) == pytest.approx((1.03, -0.02))


def test_space_bar_activates_the_draw_tool() -> None:
    """QShortcut activation depends on real window focus, which a headless
    test window does not reliably get - the same reason the existing
    fit_shortcut test (test_modeling_layout.py) emits .activated directly
    instead of simulating a real key press."""
    page = _page()
    page._activate_select_tool()
    assert page.canvas.mode == "select"

    page.draw_space_shortcut.activated.emit()

    assert page.canvas.mode == "draw"
    assert page.draw_tool.isChecked() is True


def test_an_indeterminate_structure_without_material_fails_quietly_not_as_a_popup() -> None:
    """solve() must always call the solver rather than pre-emptively refusing
    on the determinacy check alone - the check is status-bar information, not
    a separate gate. The solver's own refusal (no way to give a meaningful
    stiffness-dependent answer without material) still has to surface
    somewhere, but only in the status bar, never a blocking dialog, since an
    indeterminate structure with nothing set yet is an everyday state while
    still authoring a model."""
    page = _page()
    canvas = page.canvas
    left = canvas.add_node(0.0, 0.0)
    mid = canvas.add_node(4.0, 0.0)
    right = canvas.add_node(8.0, 0.0)
    canvas.add_member(left, mid)
    canvas.add_member(mid, right)
    canvas.set_support(left, (True, True, True))
    canvas.set_support(mid, (False, True, False))
    canvas.set_support(right, (False, True, False))

    solve_and_wait(page)

    assert page.workspace_stack.currentIndex() == 0
    assert "부정정" in page.determinacy_status.text()
    assert page.analysis_progress.isVisible() is False
