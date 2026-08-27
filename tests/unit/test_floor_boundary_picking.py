"""Floor-boundary click-picking (canvas_load_entries.py's begin/add/finish/
cancel_floor_picking) - the ordered-chain accumulator behind the MIDAS-style
"click the boundary nodes in order" alternative to the ordinary rubber-band/
ctrl-click node selection a Floor Load currently requires.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.enter_3d_mode()
    return canvas


def test_begin_floor_picking_enters_floor_pick_mode_with_an_empty_chain() -> None:
    canvas = _canvas()
    canvas.set_mode("select")

    canvas.begin_floor_picking()

    assert canvas.mode == "floor_pick"
    assert canvas._floor_chain == []


def test_add_floor_boundary_node_preserves_click_order() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    c = canvas._add_node_at((4.0, 4.0, 0.0))
    canvas.begin_floor_picking()

    canvas.add_floor_boundary_node(c)
    canvas.add_floor_boundary_node(a)
    canvas.add_floor_boundary_node(b)

    assert canvas._floor_chain == [c, a, b]


def test_add_floor_boundary_node_ignores_a_repeated_node() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    canvas.begin_floor_picking()

    canvas.add_floor_boundary_node(a)
    canvas.add_floor_boundary_node(b)
    canvas.add_floor_boundary_node(a)  # repeat click - must not duplicate/reorder

    assert canvas._floor_chain == [a, b]


def test_add_floor_boundary_node_ignores_an_unknown_tag() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    canvas.begin_floor_picking()

    canvas.add_floor_boundary_node(a)
    canvas.add_floor_boundary_node(99999)  # not a real node tag

    assert canvas._floor_chain == [a]


def test_add_floor_boundary_node_does_nothing_outside_floor_pick_mode() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    canvas.set_mode("select")  # never entered floor_pick

    canvas.add_floor_boundary_node(a)

    assert canvas._floor_chain == []


def test_finish_floor_picking_is_blocked_below_three_distinct_nodes() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    canvas.begin_floor_picking()
    canvas.add_floor_boundary_node(a)
    canvas.add_floor_boundary_node(b)

    result = canvas.finish_floor_picking()

    assert result is None
    # Left untouched, not cleared - the user should be able to keep clicking.
    assert canvas.mode == "floor_pick"
    assert canvas._floor_chain == [a, b]


def test_finish_floor_picking_succeeds_with_three_or_more_nodes_and_resets_state() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    c = canvas._add_node_at((4.0, 4.0, 0.0))
    canvas.begin_floor_picking()
    canvas.add_floor_boundary_node(b)
    canvas.add_floor_boundary_node(c)
    canvas.add_floor_boundary_node(a)

    result = canvas.finish_floor_picking()

    assert result == (b, c, a)  # click order preserved, never sorted
    assert isinstance(result, tuple)
    assert canvas._floor_chain == []  # chain reset after completion
    assert canvas.mode == "select"  # back to the normal selection mode
    assert canvas.selected_nodes == set()


def test_cancel_floor_picking_clears_chain_selection_and_mode() -> None:
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 0.0))
    c = canvas._add_node_at((4.0, 4.0, 0.0))
    canvas.begin_floor_picking()
    canvas.add_floor_boundary_node(a)
    canvas.add_floor_boundary_node(b)
    canvas.add_floor_boundary_node(c)

    canvas.cancel_floor_picking()

    assert canvas._floor_chain == []
    assert canvas.mode == "select"
    assert canvas.selected_nodes == set()


def test_switching_to_another_mode_mid_pick_also_clears_the_floor_chain() -> None:
    """set_mode is the single mode-transition point every mode switch goes
    through (see canvas_drawing_mode.py) - floor_chain must be reset there
    too, not only via finish/cancel, so an unrelated mode switch mid-pick
    never leaves a stale partial boundary behind."""
    canvas = _canvas()
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    canvas.begin_floor_picking()
    canvas.add_floor_boundary_node(a)

    canvas.set_mode("draw")

    assert canvas._floor_chain == []
