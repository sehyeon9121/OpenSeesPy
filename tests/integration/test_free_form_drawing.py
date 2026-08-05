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
