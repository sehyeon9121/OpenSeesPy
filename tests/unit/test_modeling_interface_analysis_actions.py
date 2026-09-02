"""Unit tests for 3D canvas full-analysis wiring (Phase 2-B).

Exporter and OpenSees worker are monkeypatched so these pass before the
parallel 3D ``export_opensees_script`` branch lands.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _page(*, with_service: bool = True) -> ModelingInterfacePage:
    service = MagicMock(spec=RunAnalysisService)
    service.validate.return_value = []
    return ModelingInterfacePage(
        start_in_3d=True,
        run_analysis_service=service if with_service else None,
    )


def _select_kind(page: ModelingInterfacePage, kind: AnalysisKind) -> None:
    page._show_category("analysis")
    index = page.analysis_method_selector.findData(kind.value)
    page.analysis_method_selector.setCurrentIndex(index)


@pytest.mark.parametrize(
    "kind",
    [
        AnalysisKind.MODAL,
        AnalysisKind.BUCKLING,
        AnalysisKind.TIME_HISTORY,
        AnalysisKind.RESPONSE_SPECTRUM,
    ],
)
def test_full_analysis_kinds_enable_run_when_service_is_wired(app, kind: AnalysisKind) -> None:
    page = _page(with_service=True)
    _select_kind(page, kind)
    assert page.analysis_run_button.isEnabled() is True


def test_full_analysis_kind_disabled_without_service(app) -> None:
    page = _page(with_service=False)
    _select_kind(page, AnalysisKind.MODAL)
    assert page.analysis_run_button.isEnabled() is False


@pytest.mark.parametrize(
    "kind",
    [
        AnalysisKind.LINEAR_STATIC,
        AnalysisKind.MODAL,
        AnalysisKind.BUCKLING,
        AnalysisKind.TIME_HISTORY,
        AnalysisKind.RESPONSE_SPECTRUM,
    ],
)
def test_selecting_analysis_method_previews_the_results_sidebar(
    app, kind: AnalysisKind
) -> None:
    """Picking a method must already update the Results sidebar's context
    label/sections (ResultTypeSidebar.set_analysis_kind) - not leave the
    last-*run* kind's stale label up until 해석하기 actually starts."""
    page = _page(with_service=True)
    _select_kind(page, kind)
    assert page.results.result_types.context_label.text() == kind.value.replace("_", " ").upper()


@patch("openframe.features.model.presentation.modeling_interface_page.AnalysisRunThread")
@patch("openframe.features.model.presentation.modeling_interface_page.export_opensees_script")
def test_run_full_analysis_builds_request_and_starts_thread(
    export_mock: MagicMock,
    thread_cls: MagicMock,
    app,
) -> None:
    page = _page(with_service=True)
    _select_kind(page, AnalysisKind.MODAL)
    page._analysis_settings[AnalysisKind.MODAL.value] = {
        "extraction_method": "fixed",
        "num_modes": 3,
    }
    export_mock.return_value = "# exported script"
    thread_instance = MagicMock()
    thread_cls.return_value = thread_instance

    page._run_full_analysis(AnalysisKind.MODAL)

    export_mock.assert_called_once()
    _, kwargs = export_mock.call_args
    assert kwargs["include_mass"] is True
    assert kwargs["length_unit"] == page._unit_system.length
    thread_cls.assert_called_once()
    request = thread_cls.call_args.args[1]
    assert isinstance(request, AnalysisRequest)
    assert request.kind == AnalysisKind.MODAL
    assert request.options["num_modes"] == 3
    assert request.source_path.suffix == ".py"
    assert request.source_path.exists()
    thread_instance.start.assert_called_once()
    page._analysis_run_thread = thread_instance


@patch("openframe.features.model.presentation.modeling_interface_page.AnalysisRunThread")
@patch("openframe.features.model.presentation.modeling_interface_page.export_opensees_script")
def test_missing_options_reports_in_status_bar(
    export_mock: MagicMock,
    thread_cls: MagicMock,
    app,
) -> None:
    page = _page(with_service=True)
    _select_kind(page, AnalysisKind.BUCKLING)

    page._run_full_analysis(AnalysisKind.BUCKLING)

    export_mock.assert_not_called()
    thread_cls.assert_not_called()
    assert "설정" in page.determinacy_status.text()


def test_missing_service_reports_in_status_bar(app) -> None:
    page = _page(with_service=False)
    _select_kind(page, AnalysisKind.TIME_HISTORY)
    page._analysis_settings[AnalysisKind.TIME_HISTORY.value] = {"directions": []}

    page._run_full_analysis(AnalysisKind.TIME_HISTORY)

    assert "서비스" in page.determinacy_status.text()


@patch("openframe.features.model.presentation.modeling_interface_page.QMessageBox.information")
@patch("openframe.features.model.presentation.modeling_interface_page.AnalysisRunThread")
@patch("openframe.features.model.presentation.modeling_interface_page.export_opensees_script")
def test_completion_routes_to_results_workspace(
    export_mock: MagicMock,
    thread_cls: MagicMock,
    information: MagicMock,
    app,
) -> None:
    page = _page(with_service=True)
    _select_kind(page, AnalysisKind.MODAL)
    page._analysis_settings[AnalysisKind.MODAL.value] = {
        "extraction_method": "fixed",
        "num_modes": 2,
    }
    export_mock.return_value = "# script"
    page.results.show_result = MagicMock()
    model = page.canvas.build_model()

    completed = AnalysisResult(status=AnalysisStatus.COMPLETED, mode_shapes=())
    page._full_analysis_completed(completed, model, AnalysisKind.MODAL)

    page.results.show_result.assert_called_once_with(completed)
    information.assert_called_once()
    assert information.call_args.args[1] == "해석 완료"
    assert "모드/고유치" in information.call_args.args[2]


@patch("openframe.features.model.presentation.modeling_interface_page.AnalysisRunThread")
@patch("openframe.features.model.presentation.modeling_interface_page.export_opensees_script")
def test_cancel_requests_thread_stop(
    export_mock: MagicMock,
    thread_cls: MagicMock,
    app,
) -> None:
    page = _page(with_service=True)
    _select_kind(page, AnalysisKind.RESPONSE_SPECTRUM)
    page._analysis_settings[AnalysisKind.RESPONSE_SPECTRUM.value] = {
        "periods": [0.1, 0.2],
        "spectral_accelerations": [1.0, 0.8],
        "acceleration_unit": "g",
        "num_modes": 3,
        "directions": ["X"],
        "model_length_unit": "m",
    }
    export_mock.return_value = "# script"
    thread_instance = MagicMock()
    thread_instance.isRunning.return_value = True
    thread_cls.return_value = thread_instance
    page._run_full_analysis(AnalysisKind.RESPONSE_SPECTRUM)
    page._analysis_run_thread = thread_instance

    page._cancel_full_analysis()

    thread_instance.request_cancel.assert_called_once()


def test_normalize_time_history_paths_resolves_relative_paths(tmp_path: Path) -> None:
    motion = tmp_path / "motions" / "gm.txt"
    motion.parent.mkdir()
    motion.write_text("NPTS= 2, DT= 0.01 SEC\n0.0\n0.0\n", encoding="utf-8")
    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        options = ModelingInterfacePage._normalize_full_analysis_options(
            AnalysisKind.TIME_HISTORY,
            {
                "directions": [
                    {
                        "dof": 1,
                        "path": "motions/gm.txt",
                        "unit": "model",
                        "scaling_method": "factor",
                        "scale_factor": 1.0,
                        "target_pga": 0.0,
                    }
                ],
            },
        )
    finally:
        os.chdir(original_cwd)

    assert Path(options["directions"][0]["path"]).resolve() == motion.resolve()


@pytest.mark.parametrize(
    ("kind", "label_fragment"),
    [
        (AnalysisKind.MODAL, "모드/고유치"),
        (AnalysisKind.BUCKLING, "좌굴"),
        (AnalysisKind.TIME_HISTORY, "시간이력"),
        (AnalysisKind.RESPONSE_SPECTRUM, "응답스펙트럼"),
    ],
)
@patch("openframe.features.model.presentation.modeling_interface_page.QMessageBox.information")
def test_full_analysis_completion_dialog_covers_every_kind(
    information: MagicMock,
    kind: AnalysisKind,
    label_fragment: str,
    app,
) -> None:
    page = _page(with_service=True)
    page.results.show_result = MagicMock()
    model = page.canvas.build_model()
    extra: dict[str, object] = {}
    if kind == AnalysisKind.MODAL:
        extra["mode_shapes"] = ()
    elif kind == AnalysisKind.BUCKLING:
        extra["buckling_modes"] = ()
    elif kind == AnalysisKind.TIME_HISTORY:
        extra["time_history"] = ()
    completed = AnalysisResult(status=AnalysisStatus.COMPLETED, **extra)

    page._full_analysis_completed(completed, model, kind)

    information.assert_called_once()
    assert information.call_args.args[1] == "해석 완료"
    assert label_fragment in information.call_args.args[2]


@patch("openframe.features.model.presentation.modeling_interface_page.QMessageBox.information")
def test_in_canvas_solve_completion_shows_dialog(information: MagicMock, app) -> None:
    from openframe.features.analysis.statics.solver import check_determinacy

    page = _page()
    page.results.show_result = MagicMock()
    model = page.canvas.build_model()
    result = AnalysisResult(status=AnalysisStatus.COMPLETED)

    page._solve_completed(model, check_determinacy(model), result)

    information.assert_called_once()
    assert information.call_args.args[1] == "해석 완료"
    assert "선형탄성" in information.call_args.args[2]


@patch("openframe.features.model.presentation.modeling_interface_page.QMessageBox.information")
def test_in_canvas_solve_failure_does_not_show_completion_dialog(
    information: MagicMock, app
) -> None:
    from openframe.features.analysis.statics.solver import check_determinacy

    page = _page()
    model = page.canvas.build_model()
    result = AnalysisResult(status=AnalysisStatus.FAILED, messages=["재료가 없습니다."])

    page._solve_completed(model, check_determinacy(model), result)

    information.assert_not_called()
    assert "재료가 없습니다" in page.determinacy_status.text()
