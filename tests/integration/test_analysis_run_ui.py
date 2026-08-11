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
from openframe.features.model.application.open_model import OpenModelService
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

EXAMPLES = Path(__file__).parents[2] / "examples"
EXAMPLE_MODEL = EXAMPLES / "portal_frame_2d.py"
SECOND_MODEL = EXAMPLES / "simply_supported_beam_2d.py"


def _run_thread_to_completion(thread) -> None:
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(15_000, loop.quit)
    loop.exec()


@patch("openframe.app.shell.main_window.QMessageBox.information")
def test_run_button_flow_populates_results_workspace(information: MagicMock) -> None:
    application = QApplication.instance() or QApplication([])

    model_service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    runner = OpenSeesProcessRunner(timeout_seconds=15)
    analysis_service = RunAnalysisService(
        {AnalysisKind.LINEAR_STATIC: LinearStaticAnalysis(runner)}
    )
    window = MainWindow(
        open_model_service=model_service,
        run_analysis_service=analysis_service,
        imported_unit_resolver=lambda _source: UnitSystem("kN", "m"),
    )

    window._start_model_load(EXAMPLE_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()
    assert window._current_model_source == EXAMPLE_MODEL

    window._run_analysis()
    thread = window._analysis_run_thread
    assert thread is not None
    assert not window.analysis_progress.isHidden()
    assert window.analysis_progress.isModal()
    assert window.analysis_progress.title.text() == "Calculating results"
    assert window.analysis_progress.progress.maximum() == 0
    assert window.header.status_label.text() == "●  READY"
    _run_thread_to_completion(thread)
    application.processEvents()

    assert window._analysis_run_thread is None
    assert window.results_workspace.summary.status_badge.text() == "COMPLETED"
    assert window.results_workspace.tables_panel.displacement_table.rowCount() == 4
    assert window.results_workspace.summary.member_selector.count() == 3
    assert window.analysis_progress.isHidden()
    information.assert_called_once()
    assert information.call_args.args[1] == "해석 완료"

    window.navigation.set_current_section("results", emit=True)
    assert window.workspace_stack.currentWidget() is window.results_workspace
    assert window.navigation.current_section() == "results"

    node_column_values = {
        window.results_workspace.tables_panel.displacement_table.item(row, 0).text()
        for row in range(window.results_workspace.tables_panel.displacement_table.rowCount())
    }
    assert node_column_values == {"1", "2", "3", "4"}

    for key in ("axial", "shear", "moment"):
        text = window.results_workspace.summary.metric_values[key].text()
        assert not text.startswith("—"), f"{key} value was left as the placeholder: {text}"

    selected_tag = window.results_workspace.data_panel.member_selector.currentData()
    assert selected_tag in {1, 2, 3}
    plot = window.results_workspace.data_panel.diagram_plot
    assert plot._diagram is not None
    assert plot._diagram.element_tag == selected_tag

    window.results_workspace.result_types.select_result_type("moment")
    diagram_items = [
        item
        for item in window.results_workspace.viewport.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "result_diagram"
    ]
    diagram_labels = [
        item
        for item in window.results_workspace.viewport.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "result_diagram_label"
    ]
    assert len(diagram_items) == 3
    assert diagram_labels
    assert window.results_workspace.viewport.mode_badge.text() == "BENDING MOMENT (M)"

    window.close()


@patch("openframe.app.shell.main_window.QMessageBox.information")
def test_loading_a_second_model_clears_results_and_allows_a_new_run(
    information: MagicMock,
) -> None:
    application = QApplication.instance() or QApplication([])

    model_service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    runner = OpenSeesProcessRunner(timeout_seconds=15)
    analysis_service = RunAnalysisService(
        {AnalysisKind.LINEAR_STATIC: LinearStaticAnalysis(runner)}
    )
    original_execute = analysis_service.execute
    analysis_service.execute = MagicMock(wraps=original_execute)
    window = MainWindow(
        open_model_service=model_service,
        run_analysis_service=analysis_service,
        imported_unit_resolver=lambda _source: UnitSystem("kN", "m"),
    )
    workspace = window.results_workspace

    window._start_model_load(EXAMPLE_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()
    window._run_analysis()
    _run_thread_to_completion(window._analysis_run_thread)
    application.processEvents()
    assert workspace.summary.status_badge.text() == "COMPLETED"
    assert analysis_service.execute.call_count == 1

    window._start_model_load(SECOND_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()

    # The previous run's numbers must not survive next to a different model.
    assert workspace.summary.status_badge.text() == "WAITING"
    assert workspace.summary.member_selector.count() == 0
    assert workspace.data_panel.member_selector.count() == 0
    assert workspace.tables_panel.displacement_table.rowCount() == 0
    assert not [
        item
        for item in workspace.viewport.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "result_deformation"
    ]
    # Importing another source only rebuilds the model. It must never invoke the
    # analysis service unless the user presses RUN ANALYSIS again.
    assert analysis_service.execute.call_count == 1

    window._run_analysis()
    thread = window._analysis_run_thread
    assert thread is not None
    _run_thread_to_completion(thread)
    application.processEvents()

    assert workspace.summary.status_badge.text() == "COMPLETED"
    assert workspace.tables_panel.displacement_table.rowCount() == 3
    assert workspace.summary.member_selector.count() == 2
    assert information.call_count == 2
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
