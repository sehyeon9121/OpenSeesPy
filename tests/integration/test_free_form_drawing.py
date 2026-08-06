import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.features.analysis.statics import check_determinacy
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.set_mode("draw")
    return canvas


def test_one_chain_of_clicks_creates_both_nodes_and_members() -> None:
    canvas = _canvas()

    canvas.place_point(0.0, 0.0)
    canvas.place_point(0.0, 4.0)
    canvas.place_point(5.0, 4.0)

    assert len(canvas.nodes) == 3
    assert len(canvas.elements) == 2
    assert canvas.is_drawing is True
    assert canvas.chain_anchor == pytest.approx((5.0, 4.0))


def test_escape_ends_the_chain_so_the_next_click_starts_a_new_run() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(2.0, 0.0)

    canvas.end_chain()
    canvas.place_point(6.0, 0.0)

    assert canvas.is_drawing is True
    assert len(canvas.nodes) == 3
    assert len(canvas.elements) == 1


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


def test_drawing_across_a_member_lands_on_it_and_splits_it_for_the_analysis() -> None:
    canvas = _canvas()
    canvas.place_point(0.0, 0.0)
    canvas.place_point(4.0, 0.0)
    canvas.end_chain()

    snap = canvas.snap_at(1.4, 0.03)
    tag = canvas.place_point(snap.x, snap.y, snap=snap)

    assert canvas.embedded_nodes[tag] == (1, pytest.approx(0.35))
    assert canvas.nodes[tag].x == pytest.approx(1.4)
    assert len(canvas.elements) == 1
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
