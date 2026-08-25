"""Floor Load Type CRUD + apply (canvas_load_entries.py) - MIDAS' "Floor
Load Type": a named bundle of (Load Case, magnitude) rows applied to a
floor boundary in one step, one FloorLoadEntry minted per non-empty row.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import FloorLoadTypeRow, LoadCaseKind
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def test_add_floor_load_type_refuses_a_duplicate_name() -> None:
    canvas = _canvas()
    canvas.add_floor_load_type("사무실 바닥")
    assert canvas.add_floor_load_type("사무실 바닥") is None
    assert len(canvas.floor_load_types) == 1


def test_update_floor_load_type_can_rename_and_replace_rows() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL_CONCRETE", kind=LoadCaseKind.DEAD)
    canvas.add_floor_load_type("바닥1", rows=(FloorLoadTypeRow("DL_CONCRETE", 2.0),))

    assert canvas.update_floor_load_type(
        "바닥1", name="바닥2", rows=(FloorLoadTypeRow("DL_CONCRETE", 3.5),)
    )

    assert "바닥1" not in canvas.floor_load_types
    assert canvas.floor_load_types["바닥2"].rows[0].magnitude == 3.5


def test_duplicate_floor_load_type_copies_rows_under_a_new_name() -> None:
    canvas = _canvas()
    canvas.add_load_case("LL", kind=LoadCaseKind.LIVE)
    canvas.add_floor_load_type("바닥1", rows=(FloorLoadTypeRow("LL", 2.5),))

    result = canvas.duplicate_floor_load_type("바닥1", "바닥1_COPY")

    assert result == "바닥1_COPY"
    assert canvas.floor_load_types["바닥1_COPY"].rows[0].magnitude == 2.5


def test_delete_floor_load_type_removes_it() -> None:
    canvas = _canvas()
    canvas.add_floor_load_type("바닥1")
    canvas.delete_floor_load_type("바닥1")
    assert canvas.floor_load_types == {}


def test_apply_floor_load_type_creates_one_entry_per_nonempty_row() -> None:
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    n3 = canvas.add_node(4.0, 4.0)
    canvas.add_load_case("DL_CONCRETE", kind=LoadCaseKind.DEAD)
    canvas.add_load_case("DL_FINISH", kind=LoadCaseKind.DEAD)
    canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)
    canvas.add_floor_load_type(
        "사무실 바닥",
        rows=(
            FloorLoadTypeRow("DL_CONCRETE", 2.0),
            FloorLoadTypeRow("DL_FINISH", 1.0),
            FloorLoadTypeRow(None, 0.0),  # NONE row - always skipped
            FloorLoadTypeRow("LL_OFFICE", 0.0),  # zero magnitude - skipped too
        ),
    )

    count = canvas.apply_floor_load_type("사무실 바닥", (n1, n2, n3), direction="-z")

    assert count == 2
    entries = list(canvas.load_entries.values())
    assert {entry.case_id for entry in entries} == {"DL_CONCRETE", "DL_FINISH"}
    assert all(entry.kind == "floor" for entry in entries)
    assert all(entry.target == (n1, n2, n3) for entry in entries)
    magnitudes = sorted(entry.payload.magnitude for entry in entries)
    assert magnitudes == [1.0, 2.0]


def test_apply_floor_load_type_returns_none_for_an_unknown_type() -> None:
    canvas = _canvas()
    assert canvas.apply_floor_load_type("no-such-type", (1, 2, 3)) is None


def test_apply_floor_load_type_is_a_single_undo_step() -> None:
    canvas = _canvas()
    n1, n2, n3 = canvas.add_node(0.0, 0.0), canvas.add_node(4.0, 0.0), canvas.add_node(4.0, 4.0)
    canvas.add_load_case("DL_CONCRETE", kind=LoadCaseKind.DEAD)
    canvas.add_load_case("LL", kind=LoadCaseKind.LIVE)
    canvas.add_floor_load_type(
        "바닥1",
        rows=(FloorLoadTypeRow("DL_CONCRETE", 2.0), FloorLoadTypeRow("LL", 2.5)),
    )

    canvas.apply_floor_load_type("바닥1", (n1, n2, n3))
    assert len(canvas.load_entries) == 2

    canvas.undo()

    assert canvas.load_entries == {}
