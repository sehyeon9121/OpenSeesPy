"""Verify that the main Qt window can be constructed without showing it."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow


def test_main_window_can_be_constructed() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert application is QApplication.instance()
    assert window.windowTitle() == "OpenFrame Studio"
    assert window.view is window.viewport.view
    assert window.navigation.current_section() == "model"

    window.navigation._buttons["results"].click()
    assert window.navigation.current_section() == "results"
    assert window.workspace_stack.currentWidget() is window.results_workspace
    assert set(window.results_workspace.result_types.buttons) == {
        "overview",
        "deformation",
        "displacement",
        "reaction",
        "axial",
        "shear",
        "moment",
        "tables",
    }
    assert window.analysis_settings.analysis_type.currentText() == "Linear Static"
    assert window.header.run_button.text() == "▶  RUN ANALYSIS"

    window.close()
