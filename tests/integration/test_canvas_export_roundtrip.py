"""End-to-end coverage for the only place the canvas (free-form 2D authoring)
and "OpenSeesPy 파일 불러오기" (nonlinear static/time history/modal, subprocess-
executed) paths actually meet: exporting a hand-drawn model as a script and
opening it through the real file-import pipeline, not just the canvas's own
in-process solvers."""

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.core.domain import UnitSystem
from openframe.features.model.application.open_model import OpenModelService
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter


def _run_thread_to_completion(thread) -> None:
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(15_000, loop.quit)
    loop.exec()


def test_exporting_a_canvas_model_opens_it_through_the_file_import_pipeline(
    tmp_path: Path,
) -> None:
    application = QApplication.instance() or QApplication([])
    model_service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    window = MainWindow(
        open_model_service=model_service,
        imported_unit_resolver=lambda _source: UnitSystem("kN", "m"),
    )

    window.start_workspace.new_model_button.click()
    direct = window.direct_model_workspace
    assert window.workspace_stack.currentWidget() is direct

    canvas = direct.geometry_page.canvas
    base = canvas.add_node(0.0, 0.0)
    tip = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(base, tip)
    canvas.set_support(base, (True, True, True))
    canvas.selected_elements = {member}
    canvas.apply_section_to_selection(width=0.3, height=0.5, elastic=200_000.0)

    destination = tmp_path / "exported.py"
    with patch(
        "openframe.features.model.presentation.modeling_interface_page.QFileDialog.getSaveFileName",
        return_value=(str(destination), "Python 파일 (*.py)"),
    ):
        direct.geometry_page.export_analysis_button.click()

    thread = window._model_load_thread
    assert thread is not None, "exporting must trigger the real model-load pipeline"
    _run_thread_to_completion(thread)
    application.processEvents()

    # The app has left the canvas workspace for the ordinary file-import one -
    # the same place a manually-picked .py file would land.
    assert window.workspace_stack.currentWidget() is window.model_workspace_page
    assert window._current_model_source == destination
    assert window.model_sidebar.summary_values["nodes"].text() == "2"
    assert window.model_sidebar.summary_values["elements"].text() == "1"

    window.close()
