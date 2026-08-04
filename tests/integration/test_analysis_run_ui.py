import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.core.domain import AnalysisKind
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.linear_static.module import LinearStaticAnalysis
from openframe.features.model.application.open_model import OpenModelService
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "portal_frame_2d.py"


def _run_thread_to_completion(thread) -> None:
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(15_000, loop.quit)
    loop.exec()


def test_run_button_flow_populates_results_panel() -> None:
    application = QApplication.instance() or QApplication([])

    model_service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    runner = OpenSeesProcessRunner(timeout_seconds=15)
    analysis_service = RunAnalysisService(
        {AnalysisKind.LINEAR_STATIC: LinearStaticAnalysis(runner)}
    )
    window = MainWindow(open_model_service=model_service, run_analysis_service=analysis_service)

    window._start_model_load(EXAMPLE_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()
    assert window._current_model_source == EXAMPLE_MODEL

    window._run_analysis()
    thread = window._analysis_run_thread
    assert thread is not None
    _run_thread_to_completion(thread)
    application.processEvents()

    assert window._analysis_run_thread is None
    assert window.results_panel.status_badge.text() == "COMPLETED"
    assert window.results_panel.displacement_table.rowCount() == 4

    node_column_values = {
        window.results_panel.displacement_table.item(row, 0).text()
        for row in range(window.results_panel.displacement_table.rowCount())
    }
    assert node_column_values == {"1", "2", "3", "4"}

    for key in ("axial", "shear", "moment"):
        text = window.results_panel.result_values[key].text()
        assert not text.startswith("—"), f"{key} value was left as the placeholder: {text}"

    assert window.results_panel.member_selector.count() == 3
    selected_tag = window.results_panel.member_selector.currentData()
    assert selected_tag in {1, 2, 3}
    for key in ("axial", "shear", "moment"):
        plot = window.results_panel.diagram_plots[key]
        assert plot._diagram is not None
        assert plot._diagram.element_tag == selected_tag

    window.close()


def test_run_without_loaded_model_shows_warning_and_does_not_crash() -> None:
    application = QApplication.instance() or QApplication([])
    runner = OpenSeesProcessRunner(timeout_seconds=15)
    analysis_service = RunAnalysisService(
        {AnalysisKind.LINEAR_STATIC: LinearStaticAnalysis(runner)}
    )
    window = MainWindow(run_analysis_service=analysis_service)

    with patch("openframe.app.shell.main_window.QMessageBox.warning") as warning:
        window._run_analysis()
        application.processEvents()

    warning.assert_called_once()
    assert window._analysis_run_thread is None
    window.close()
