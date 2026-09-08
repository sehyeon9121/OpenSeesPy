"""``MainWindow._analysis_completed`` must not block a diagnosed mechanism
behind a critical error dialog - it already pushes the result (mechanism
modes included) into ``results_workspace`` unconditionally, so a genuinely
diagnosed instability should read as "go look at RESULTS", not "analysis
failed". See ``tests/unit/test_solve_completed_instability_gate.py`` for the
same philosophy on the 3D canvas's simple solve path.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.core.domain import (
    AnalysisKind,
    AnalysisResult,
    AnalysisStatus,
    InstabilityDiagnosticResult,
    MechanismMode,
    UnitSystem,
)
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.linear_static.module import LinearStaticAnalysis
from openframe.features.model.application.open_model import OpenModelService
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

EXAMPLES = Path(__file__).parents[2] / "examples"
EXAMPLE_MODEL = EXAMPLES / "portal_frame_2d.py"


def _run_thread_to_completion(thread) -> None:
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(15_000, loop.quit)
    loop.exec()


def _mechanism_result() -> AnalysisResult:
    diagnostic = InstabilityDiagnosticResult(
        mechanism_count=1,
        modes=(
            MechanismMode(
                mode_number=1,
                eigenvalue=1e-15,
                mode_shape={1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)},
                dominant_dofs=("n2:Ux=+1.00",),
                residual=1e-14,
            ),
        ),
        message="구조가 불안정합니다 - 강성행렬에서 메커니즘 1개가 감지되었습니다.",
        matrix_size=6,
        diagnostic_success=True,
    )
    return AnalysisResult(
        status=AnalysisStatus.FAILED,
        messages=["정역학 계산에 실패했습니다: 선형정적해석이 수렴하지 않았습니다.", diagnostic.message],
        instability_diagnostic=diagnostic,
    )


def _window() -> MainWindow:
    model_service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    runner = OpenSeesProcessRunner(timeout_seconds=15)
    analysis_service = RunAnalysisService(
        {AnalysisKind.LINEAR_STATIC: LinearStaticAnalysis(runner)}
    )
    return MainWindow(
        open_model_service=model_service,
        run_analysis_service=analysis_service,
        imported_unit_resolver=lambda _source: UnitSystem("kN", "m"),
    )


def test_mechanism_failure_populates_results_without_critical_dialog() -> None:
    application = QApplication.instance() or QApplication([])
    window = _window()

    window._start_model_load(EXAMPLE_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()
    assert window._current_model_source == EXAMPLE_MODEL

    with (
        patch("openframe.app.shell.main_window.QMessageBox.critical") as critical,
        patch("openframe.app.shell.main_window.QMessageBox.warning") as warning,
    ):
        window._analysis_completed(
            _mechanism_result(),
            run_generation=window._model_generation,
            run_session_key=window._current_session_key,
        )

    critical.assert_not_called()
    warning.assert_called_once()
    assert warning.call_args.args[1] == "구조 불안정 감지"
    assert window.results_workspace.result_types._instability_available
    window.close()


def test_non_mechanism_failure_still_shows_critical_dialog() -> None:
    application = QApplication.instance() or QApplication([])
    window = _window()

    window._start_model_load(EXAMPLE_MODEL)
    _run_thread_to_completion(window._model_load_thread)
    application.processEvents()

    result = AnalysisResult(status=AnalysisStatus.FAILED, messages=["재료가 없습니다."])

    with (
        patch("openframe.app.shell.main_window.QMessageBox.critical") as critical,
        patch("openframe.app.shell.main_window.QMessageBox.warning") as warning,
    ):
        window._analysis_completed(
            result,
            run_generation=window._model_generation,
            run_session_key=window._current_session_key,
        )

    warning.assert_not_called()
    critical.assert_called_once()
    assert critical.call_args.args[1] == "해석 실행 실패"
    window.close()
