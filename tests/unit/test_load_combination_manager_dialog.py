import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import LoadCaseKind
from openframe.features.model.presentation.load_combination_manager_dialog import (
    LoadCombinationManagerDialog,
)
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def test_dialog_preloads_the_panel_from_existing_canvas_combinations() -> None:
    canvas = _canvas()
    canvas.add_load_combination("ULS-01")
    canvas.update_load_combination("ULS-01", {LoadCaseKind.DEAD: 1.2, LoadCaseKind.LIVE: 1.6})

    dialog = LoadCombinationManagerDialog(canvas)

    assert len(dialog.panel.combinations()) == 1
    assert dialog.panel.combinations()[0].name == "ULS-01"


def test_save_writes_the_panels_rows_back_to_the_canvas() -> None:
    canvas = _canvas()
    dialog = LoadCombinationManagerDialog(canvas)
    row = dialog.panel.add_row("ULS-01", {LoadCaseKind.DEAD: 1.2, LoadCaseKind.LIVE: 1.6})

    dialog._save()

    assert "ULS-01" in canvas.load_combinations
    assert canvas.load_combinations["ULS-01"].factor_for(LoadCaseKind.DEAD) == 1.2
    assert canvas.load_combinations["ULS-01"].factor_for(LoadCaseKind.LIVE) == 1.6
    assert row is dialog.panel._rows[0]


def test_cancel_never_touches_the_canvas() -> None:
    canvas = _canvas()
    canvas.add_load_combination("ULS-01")
    dialog = LoadCombinationManagerDialog(canvas)
    dialog.panel.add_row("ULS-99")

    dialog.reject()

    assert list(canvas.load_combinations.keys()) == ["ULS-01"]
