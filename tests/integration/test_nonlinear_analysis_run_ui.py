import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.core.domain import AnalysisKind, UnitSystem
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.linear_static.module import LinearStaticAnalysis
from openframe.features.analysis.nonlinear_static.module import NonlinearStaticAnalysis
from openframe.features.model.application.open_model import OpenModelService
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "nonlinear_spring_pushover_1d.py"


def _run_thread_to_completion(thread) -> None:
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(15_000, loop.quit)
    loop.exec()


def _build_window() -> MainWindow:
    model_service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    runner = OpenSeesProcessRunner(timeout_seconds=15)
    analysis_service = RunAnalysisService(
        {
            AnalysisKind.LINEAR_STATIC: LinearStaticAnalysis(runner),
            AnalysisKind.NONLINEAR_STATIC: NonlinearStaticAnalysis(runner),
        }
    )
    return MainWindow(
        open_model_service=model_service,
        run_analysis_service=analysis_service,
        imported_unit_resolver=lambda _source: UnitSystem("kN", "m"),
    )


@patch("openframe.app.shell.main_window.QMessageBox.information")
def test_nonlinear_run_populates_pushover_curve(information: MagicMock) -> None:
    application = QApplication.instance() or QApplication([])
    window = _build_window()

    window._start_model_load(EXAMPLE_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()
    assert window._current_model_source == EXAMPLE_MODEL

    settings = window.analysis_settings
    settings.analysis_type.setCurrentIndex(
        settings.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    assert settings.control_node.count() == 2
    settings.control_node.setCurrentIndex(settings.control_node.findData(2))
    settings.num_steps.setValue(15)

    window._run_analysis()
    thread = window._analysis_run_thread
    assert thread is not None
    _run_thread_to_completion(thread)
    application.processEvents()

    assert window._analysis_run_thread is None
    information.assert_called_once()

    workspace = window.results_workspace
    workspace.result_types.select_result_type("pushover")
    application.processEvents()

    viewport = workspace.viewport
    assert viewport.canvas_stack.currentWidget() is viewport.curve_view
    assert len(viewport.curve_view._points) == 15
    assert viewport.mode_badge.text() == "PUSHOVER CURVE"

    window.close()


@patch("openframe.app.shell.main_window.QMessageBox.information")
def test_nonlinear_run_with_pdelta_and_new_options_survives_the_real_worker_subprocess(
    information: MagicMock,
) -> None:
    """build_options() must produce exactly the keyword names
    run_nonlinear_static_analysis accepts - a mismatch would only surface as a
    worker-subprocess TypeError, which only a real end-to-end run (not a mocked
    runner) actually exercises. Covers geometric_transform_type, target_load_factor,
    automatic_recovery and adaptive_step together."""
    application = QApplication.instance() or QApplication([])
    window = _build_window()

    window._start_model_load(EXAMPLE_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()

    settings = window.analysis_settings
    settings.analysis_type.setCurrentIndex(
        settings.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    settings.control_node.setCurrentIndex(settings.control_node.findData(2))
    settings.num_steps.setValue(10)
    settings.geometric_transformation.setCurrentIndex(
        settings.geometric_transformation.findData("PDelta")
    )
    settings.target_load_factor.setValue(1.0)
    settings.adaptive_step.setChecked(True)
    settings.min_increment.setValue(0.0001)

    window._run_analysis()
    thread = window._analysis_run_thread
    assert thread is not None
    _run_thread_to_completion(thread)
    application.processEvents()

    assert window._analysis_run_thread is None
    information.assert_called_once()
    window.close()


@patch("openframe.app.shell.main_window.QMessageBox.critical")
def test_nonlinear_validation_blocks_run_without_control_node(critical: MagicMock) -> None:
    """The control node combo starts empty until a model loads; running before that
    (or before picking a node) must surface the module's own validation message
    instead of crashing on a missing option."""
    application = QApplication.instance() or QApplication([])
    window = _build_window()

    window._start_model_load(EXAMPLE_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()

    settings = window.analysis_settings
    settings.analysis_type.setCurrentIndex(
        settings.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    settings.control_node.setCurrentIndex(-1)

    window._run_analysis()
    thread = window._analysis_run_thread
    assert thread is not None
    _run_thread_to_completion(thread)
    application.processEvents()

    # ResultSummaryPanel only distinguishes "COMPLETED" from everything else - a
    # failed run reads the same as "no result yet" there (pre-existing behaviour,
    # unrelated to this feature). The dialog is what actually surfaces the failure.
    critical.assert_called_once()
    assert "CONTROL NODE" in critical.call_args.args[2]
    window.close()
