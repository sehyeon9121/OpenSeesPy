import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import LoadCaseKind
from openframe.features.model.presentation.load_case_manager_dialog import LoadCaseManagerDialog
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def test_dialog_lists_every_existing_load_case_on_open() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL_SELF", kind=LoadCaseKind.DEAD)
    canvas.add_load_case("LL_OFFICE", kind=LoadCaseKind.LIVE)

    dialog = LoadCaseManagerDialog(canvas)

    assert dialog.table.rowCount() == 2
    names = {dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())}
    assert names == {"DL_SELF", "LL_OFFICE"}


def test_add_button_creates_a_case_on_the_canvas_immediately() -> None:
    canvas = _canvas()
    dialog = LoadCaseManagerDialog(canvas)
    dialog.name_input.setText("WX_POS")
    index = dialog.type_input.findData(LoadCaseKind.WIND.value)
    dialog.type_input.setCurrentIndex(index)
    dialog.description_input.setText("Wind +X")

    dialog._add_case()

    assert "WX_POS" in canvas.load_cases
    assert canvas.load_cases["WX_POS"].kind is LoadCaseKind.WIND
    assert dialog.table.rowCount() == 1


def test_add_button_rejects_a_duplicate_name_without_touching_the_canvas() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL_SELF")
    dialog = LoadCaseManagerDialog(canvas)
    dialog.name_input.setText("DL_SELF")

    dialog._add_case()

    assert len(canvas.load_cases) == 1
    assert "이미 사용 중" in dialog.status_label.text()


def test_delete_button_removes_the_selected_case() -> None:
    canvas = _canvas()
    canvas.add_load_case("DL_SELF")
    dialog = LoadCaseManagerDialog(canvas)
    dialog.table.selectRow(0)

    dialog._delete_case()

    assert canvas.load_cases == {}
    assert dialog.table.rowCount() == 0
