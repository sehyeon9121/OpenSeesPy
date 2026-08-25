import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import FloorLoadTypeRow, LoadCaseKind
from openframe.features.model.presentation.floor_load_type_manager_dialog import (
    FloorLoadTypeManagerDialog,
)
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def test_dialog_lists_every_existing_type_on_open() -> None:
    canvas = _canvas()
    canvas.add_floor_load_type("바닥1")
    canvas.add_floor_load_type("바닥2")

    dialog = FloorLoadTypeManagerDialog(canvas)

    assert dialog.table.rowCount() == 2
    names = {dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())}
    assert names == {"바닥1", "바닥2"}


def test_row_case_combos_offer_none_plus_every_load_case() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL_CONCRETE", kind=LoadCaseKind.DEAD)

    dialog = FloorLoadTypeManagerDialog(canvas)

    combo = dialog.row_case_combos[0]
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert labels == ["NONE", "DL_CONCRETE"]


def test_add_button_creates_a_type_with_the_form_rows() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL_CONCRETE", kind=LoadCaseKind.DEAD)
    dialog = FloorLoadTypeManagerDialog(canvas)
    dialog.name_input.setText("사무실 바닥")
    dialog.row_case_combos[0].setCurrentIndex(dialog.row_case_combos[0].findData("DL_CONCRETE"))
    dialog.row_magnitude_spins[0].setValue(2.0)

    dialog._add_type()

    assert "사무실 바닥" in canvas.floor_load_types
    assert canvas.floor_load_types["사무실 바닥"].rows[0].case_id == "DL_CONCRETE"
    assert canvas.floor_load_types["사무실 바닥"].rows[0].magnitude == 2.0
    assert dialog.table.rowCount() == 1


def test_add_button_rejects_a_duplicate_name_without_touching_the_canvas() -> None:
    canvas = _canvas()
    canvas.add_floor_load_type("바닥1")
    dialog = FloorLoadTypeManagerDialog(canvas)
    dialog.name_input.setText("바닥1")

    dialog._add_type()

    assert len(canvas.floor_load_types) == 1
    assert "이미 사용 중" in dialog.status_label.text()


def test_selecting_a_row_loads_its_values_back_into_the_form() -> None:
    canvas = _canvas()
    canvas.add_load_case("LL", kind=LoadCaseKind.LIVE)
    canvas.add_floor_load_type(
        "바닥1", description="설명", rows=(FloorLoadTypeRow("LL", 2.5),)
    )
    dialog = FloorLoadTypeManagerDialog(canvas)

    dialog.table.selectRow(0)

    assert dialog.name_input.text() == "바닥1"
    assert dialog.description_input.text() == "설명"
    assert dialog.row_case_combos[0].currentData() == "LL"
    assert dialog.row_magnitude_spins[0].value() == 2.5


def test_delete_button_removes_the_selected_type() -> None:
    canvas = _canvas()
    canvas.add_floor_load_type("바닥1")
    dialog = FloorLoadTypeManagerDialog(canvas)
    dialog.table.selectRow(0)

    dialog._delete_type()

    assert canvas.floor_load_types == {}
    assert dialog.table.rowCount() == 0


def test_define_load_case_button_opening_the_case_manager_refreshes_row_combos(monkeypatch) -> None:
    canvas = _canvas()
    dialog = FloorLoadTypeManagerDialog(canvas)
    assert dialog.row_case_combos[0].count() == 1  # just NONE

    def _fake_exec(self):
        canvas.add_load_case("NEW_CASE", kind=LoadCaseKind.OTHER)
        return 0

    monkeypatch.setattr(
        "openframe.features.model.presentation.load_case_manager_dialog.LoadCaseManagerDialog.exec",
        _fake_exec,
    )

    dialog._open_load_case_manager()

    labels = [dialog.row_case_combos[0].itemText(i) for i in range(dialog.row_case_combos[0].count())]
    assert "NEW_CASE" in labels
