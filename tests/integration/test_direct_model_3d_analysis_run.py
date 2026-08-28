"""Integration tests for MainWindow -> DirectModelWorkspace -> 3D canvas
analysis service wiring (Phase 2-B)."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.core.domain import AnalysisKind, AnalysisResult, AnalysisStatus
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.modal.module import ModalAnalysis
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner


@patch("openframe.features.model.presentation.modeling_interface_page.export_opensees_script")
def test_service_passes_through_to_3d_geometry_page(export_mock: MagicMock) -> None:
    QApplication.instance() or QApplication([])
    runner = OpenSeesProcessRunner(timeout_seconds=5)
    service = RunAnalysisService({AnalysisKind.MODAL: ModalAnalysis(runner)})
    window = MainWindow(run_analysis_service=service)

    page_3d = window.direct_model_workspace.geometry_page_3d
    page_2d = window.direct_model_workspace.geometry_page
    assert page_3d._run_analysis_service is service
    assert page_2d._run_analysis_service is None

    window.close()


@patch("openframe.features.model.presentation.modeling_interface_page.AnalysisRunThread")
@patch("openframe.features.model.presentation.modeling_interface_page.export_opensees_script")
def test_3d_modal_solve_creates_request_and_starts_thread(
    export_mock: MagicMock,
    thread_cls: MagicMock,
) -> None:
    QApplication.instance() or QApplication([])
    runner = OpenSeesProcessRunner(timeout_seconds=5)
    service = RunAnalysisService({AnalysisKind.MODAL: ModalAnalysis(runner)})
    window = MainWindow(run_analysis_service=service)
    page = window.direct_model_workspace.geometry_page_3d
    page._show_category("analysis")
    index = page.analysis_method_selector.findData(AnalysisKind.MODAL.value)
    page.analysis_method_selector.setCurrentIndex(index)
    page._analysis_settings[AnalysisKind.MODAL.value] = {
        "extraction_method": "fixed",
        "num_modes": 2,
    }
    export_mock.return_value = "import openseespy.opensees as ops"
    thread_instance = MagicMock()
    thread_cls.return_value = thread_instance

    page.solve()

    export_mock.assert_called_once()
    thread_cls.assert_called_once()
    request = thread_cls.call_args.args[1]
    assert request.kind == AnalysisKind.MODAL
    assert request.options["num_modes"] == 2
    thread_instance.start.assert_called_once()
    assert not page.analysis_progress.isHidden()

    window.close()


def test_validate_failure_without_starting_thread() -> None:
    QApplication.instance() or QApplication([])
    runner = OpenSeesProcessRunner(timeout_seconds=5)
    service = RunAnalysisService({AnalysisKind.MODAL: ModalAnalysis(runner)})
    from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage

    page = ModelingInterfacePage(start_in_3d=True, run_analysis_service=service)
    page._show_category("analysis")
    page._analysis_settings[AnalysisKind.MODAL.value] = {
        "extraction_method": "fixed",
        "num_modes": 0,
    }

    with patch(
        "openframe.features.model.presentation.modeling_interface_page.export_opensees_script",
        return_value="# ok",
    ):
        with patch(
            "openframe.features.model.presentation.modeling_interface_page.AnalysisRunThread"
        ) as thread_cls:
            page._run_full_analysis(AnalysisKind.MODAL)
            thread_cls.assert_not_called()

    assert "모드" in page.determinacy_status.text()


@patch("openframe.features.model.presentation.modeling_interface_page.export_opensees_script")
def test_full_analysis_completion_shows_result(export_mock: MagicMock) -> None:
    QApplication.instance() or QApplication([])
    runner = OpenSeesProcessRunner(timeout_seconds=5)
    service = RunAnalysisService({AnalysisKind.MODAL: ModalAnalysis(runner)})
    from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage

    page = ModelingInterfacePage(start_in_3d=True, run_analysis_service=service)
    page._show_category("analysis")
    export_mock.return_value = "# ok"
    model = page.canvas.build_model()
    completed = AnalysisResult(status=AnalysisStatus.COMPLETED, mode_shapes=())
    page.results.show_result = MagicMock()

    page._full_analysis_completed(completed, model, AnalysisKind.MODAL)

    page.results.show_result.assert_called_once_with(completed)
