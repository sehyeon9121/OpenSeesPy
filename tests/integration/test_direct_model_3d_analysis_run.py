"""Integration tests for 3D canvas -> RunAnalysisService wiring (Phase 2-B/2-C).

Phase 2-C adds real OpenSees end-to-end runs through exported 3D scripts and
verifies the canvas execution boundary (request creation, path normalization,
temp-file lifetime) without modifying the exporter itself.
"""

import math
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.buckling.module import BucklingAnalysis
from openframe.features.analysis.modal.module import ModalAnalysis
from openframe.features.analysis.response_spectrum.module import ResponseSpectrumAnalysis
from openframe.features.analysis.statics.opensees_script_export import export_opensees_script
from openframe.features.analysis.time_history.module import TimeHistoryAnalysis
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

_DT = 0.01
_NUM_POINTS = 200
_PULSE_DURATION = 1.0


def _analysis_service(timeout_seconds: float = 30.0) -> RunAnalysisService:
    runner = OpenSeesProcessRunner(timeout_seconds=timeout_seconds)
    return RunAnalysisService(
        {
            AnalysisKind.MODAL: ModalAnalysis(runner),
            AnalysisKind.BUCKLING: BucklingAnalysis(runner),
            AnalysisKind.TIME_HISTORY: TimeHistoryAnalysis(runner),
            AnalysisKind.RESPONSE_SPECTRUM: ResponseSpectrumAnalysis(runner),
        }
    )


def _page(*, with_service: bool = True) -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    service = _analysis_service() if with_service else None
    page = ModelingInterfacePage(start_in_3d=True, run_analysis_service=service)
    page.resize(1280, 800)
    page.show()
    return page


def _build_mass_cantilever(page: ModelingInterfacePage) -> tuple[int, int, int]:
    """3D cantilever with density so ``include_mass=True`` export assigns nodal mass."""
    base = page.canvas._add_node_at((0.0, 0.0, 0.0))
    tip = page.canvas._add_node_at((6.0, 0.0, 0.0))
    member = page.canvas.add_member(base, tip)
    page.canvas.selected_elements = {member}
    page.canvas.apply_full_section_to_selection(
        shape="Rectangle",
        source="custom",
        dimensions={"b": 0.2, "h": 0.2},
        area=0.04,
        iy=2.67e-4,
        iz=2.67e-4,
        j=4.0e-4,
        elastic=200000.0,
        density=5.0,
    )
    page.canvas.selected_nodes = {base}
    page.canvas.apply_support_to_selection((True,) * 6)
    return base, tip, member


def _build_axially_loaded_cantilever(page: ModelingInterfacePage) -> tuple[int, int, int]:
    """Same cantilever as ``_build_mass_cantilever``, plus a compressive
    nodal load along the member's own axis (global X here) at the tip - the
    "하단 고정, 상단 압축축력" scenario Buckling needs a real reference load
    for (see buckling_solver.py's own module docstring: unlike Modal/Time
    History/Response Spectrum, which only need mass, Buckling's geometric
    stiffness comes from a genuine static reference load pattern applied to
    the model - Modal/Time History/Response Spectrum's own tests reuse
    ``_build_mass_cantilever`` unchanged precisely because they never needed
    one)."""
    base, tip, member = _build_mass_cantilever(page)
    page.canvas.selected_nodes = {tip}
    page.canvas.apply_nodal_load_to_selection((-1000.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    return base, tip, member


def _write_half_sine_motion(path: Path) -> Path:
    lines = [f"NPTS= {_NUM_POINTS}, DT= {_DT} SEC"]
    for index in range(_NUM_POINTS):
        time = index * _DT
        value = (
            math.sin(math.pi * time / _PULSE_DURATION)
            if 0.0 <= time <= _PULSE_DURATION
            else 0.0
        )
        lines.append(f"{value:+.6E}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.resolve()


def _minimal_time_history_options(motion_path: Path) -> dict[str, object]:
    return {
        "directions": [
            {
                "dof": 1,
                "path": str(motion_path),
                "unit": "model",
                "scaling_method": "factor",
                "scale_factor": 1.0,
                "target_pga": 0.0,
            }
        ],
        "model_length_unit": "m",
        "analysis_time": {
            "duration_mode": "custom",
            "end_time": 0.5,
            "dt": _DT,
            "max_dt": 0.0,
        },
        "damping": {"mode": "none"},
        "integrator": {"type": "Newmark", "gamma": 0.5, "beta": 0.25},
        "solution": {
            "algorithm": "ModifiedNewton",
            "test_type": "EnergyIncr",
            "tolerance": 1.0e-8,
            "max_iterations": 50,
            "constraints_type": "Plain",
            "numberer": "Plain",
            "system": "BandGeneral",
        },
        "recovery": {
            "automatic": False,
            "algorithm_fallback": False,
            "min_dt": 0.0,
            "reduction_factor": 0.5,
            "restoration_factor": 1.5,
            "max_reductions": 4,
            "clean_steps_to_restore": 5,
        },
    }


def _wait_for_analysis_thread(page: ModelingInterfacePage) -> None:
    thread = page._analysis_run_thread
    if thread is None:
        return
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(60_000, loop.quit)
    loop.exec()
    QApplication.instance().processEvents()


def _page_with_service(service: RunAnalysisService | MagicMock) -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True, run_analysis_service=service)
    page.resize(1280, 800)
    page.show()
    return page



@patch("openframe.features.model.presentation.modeling_interface_page.AnalysisRunThread")
@patch("openframe.features.model.presentation.modeling_interface_page.export_opensees_script")
def test_3d_modal_solve_creates_request_and_starts_thread(
    export_mock: MagicMock,
    thread_cls: MagicMock,
) -> None:
    service = MagicMock(spec=RunAnalysisService)
    service.validate.return_value = []
    page = _page_with_service(service)
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


def test_validate_failure_without_starting_thread() -> None:
    page = _page()
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
    page = _page()
    page._show_category("analysis")
    export_mock.return_value = "# ok"
    model = page.canvas.build_model()
    completed = AnalysisResult(status=AnalysisStatus.COMPLETED, mode_shapes=())
    page.results.show_result = MagicMock()

    page._full_analysis_completed(completed, model, AnalysisKind.MODAL)

    page.results.show_result.assert_called_once_with(completed)


def test_exported_3d_modal_e2e_via_run_analysis_service(tmp_path: Path) -> None:
    """Verification 1: export + synchronous ``RunAnalysisService.execute()``."""
    page = _page()
    _build_mass_cantilever(page)
    model = page.canvas.build_model()
    script = export_opensees_script(
        model, include_mass=True, length_unit=page._unit_system.length
    )
    source = tmp_path / "modal_model.py"
    source.write_text(script, encoding="utf-8")

    service = _analysis_service()
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.MODAL,
        options={"extraction_method": "fixed", "num_modes": 2},
    )
    result = service.execute(request)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.mode_shapes
    fundamental = result.mode_shapes[0]
    assert fundamental.period > 0.0
    assert fundamental.frequency_hz > 0.0
    assert fundamental.angular_frequency > 0.0
    assert len(fundamental.node_results) >= 2


def test_3d_canvas_modal_full_pipeline_runs_and_shows_results() -> None:
    """Verification 2: real exporter + real worker thread from the canvas."""
    page = _page()
    _build_mass_cantilever(page)
    page._show_category("analysis")
    page._analysis_settings[AnalysisKind.MODAL.value] = {
        "extraction_method": "fixed",
        "num_modes": 2,
    }

    page._run_full_analysis(AnalysisKind.MODAL)
    temp_path = page._analysis_temp_script
    assert temp_path is not None
    assert temp_path.exists()
    assert temp_path.suffix == ".py"

    _wait_for_analysis_thread(page)

    assert not temp_path.exists()
    assert page._analysis_temp_script is None
    assert page.results.summary.status_badge.text() == "COMPLETED"
    assert page.workspace_stack.currentIndex() == 1


def test_validate_failure_deletes_temp_script_before_thread_starts() -> None:
    page = _page()
    _build_mass_cantilever(page)
    page._analysis_settings[AnalysisKind.MODAL.value] = {
        "extraction_method": "fixed",
        "num_modes": 0,
    }

    created_paths: list[Path] = []
    original_named = tempfile.NamedTemporaryFile

    def capture_temp(*args, **kwargs):
        handle = original_named(*args, **kwargs)
        created_paths.append(Path(handle.name))
        return handle

    with patch(
        "openframe.features.model.presentation.modeling_interface_page.tempfile.NamedTemporaryFile",
        side_effect=capture_temp,
    ):
        page._run_full_analysis(AnalysisKind.MODAL)

    assert created_paths
    assert not created_paths[0].exists()
    assert page._analysis_temp_script is None


def test_failed_analysis_run_deletes_temp_script_after_thread_finishes() -> None:
    service = MagicMock(spec=RunAnalysisService)
    service.validate.return_value = []
    service.execute.return_value = AnalysisResult(
        status=AnalysisStatus.FAILED,
        messages=["의도적 실패"],
    )
    page = _page_with_service(service)
    _build_mass_cantilever(page)
    page._analysis_settings[AnalysisKind.MODAL.value] = {
        "extraction_method": "fixed",
        "num_modes": 2,
    }

    page._run_full_analysis(AnalysisKind.MODAL)
    temp_path = page._analysis_temp_script
    assert temp_path is not None

    _wait_for_analysis_thread(page)

    assert not temp_path.exists()
    assert page._analysis_temp_script is None
    assert "의도적 실패" in page.determinacy_status.text()


def test_time_history_absolute_path_survives_subprocess_cwd(tmp_path: Path) -> None:
    """Verification 3: motion file outside the script directory still loads."""
    page = _page()
    _build_mass_cantilever(page)
    model = page.canvas.build_model()
    script = export_opensees_script(
        model, include_mass=True, length_unit=page._unit_system.length
    )
    script_dir = tmp_path / "analysis_scripts"
    script_dir.mkdir()
    source = script_dir / "model.py"
    source.write_text(script, encoding="utf-8")

    motion = _write_half_sine_motion(tmp_path / "motions" / "half_sine.txt")
    options = _minimal_time_history_options(motion)
    assert Path(options["directions"][0]["path"]).is_absolute()

    service = _analysis_service()
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.TIME_HISTORY,
        options=options,
    )
    result = service.execute(request)

    assert result.status == AnalysisStatus.COMPLETED, result.messages
    assert result.time_history
    assert len(result.time_history) > 1


def test_canvas_normalizes_relative_time_history_paths(tmp_path: Path) -> None:
    motion = _write_half_sine_motion(tmp_path / "motions" / "gm.txt")
    relative = Path("motions") / "gm.txt"
    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        options = ModelingInterfacePage._normalize_full_analysis_options(
            AnalysisKind.TIME_HISTORY,
            {
                "directions": [
                    {
                        "dof": 1,
                        "path": str(relative),
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

    normalized_path = Path(options["directions"][0]["path"])
    assert normalized_path.is_absolute()
    assert normalized_path == motion


def test_response_spectrum_smoke_on_exported_3d_model(tmp_path: Path) -> None:
    """Verification 4: response spectrum executes on a mass-bearing 3D export."""
    page = _page()
    _build_mass_cantilever(page)
    model = page.canvas.build_model()
    script = export_opensees_script(
        model, include_mass=True, length_unit=page._unit_system.length
    )
    source = tmp_path / "rs_model.py"
    source.write_text(script, encoding="utf-8")

    service = _analysis_service()
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.RESPONSE_SPECTRUM,
        options={
            "periods": [0.1, 1.0, 5.0],
            "spectral_accelerations": [1.0, 0.8, 0.3],
            "acceleration_unit": "g",
            "num_modes": 2,
            "directions": ["X"],
            "model_length_unit": "m",
        },
    )
    result = service.execute(request)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results
    assert result.response_spectrum_settings is not None
    assert result.response_spectrum_settings.num_modes == 2


def test_buckling_on_exported_3d_script_fails_without_a_reference_load(
    tmp_path: Path,
) -> None:
    """``_build_mass_cantilever`` never applies a load (only Modal/Time
    History/Response Spectrum need mass, so its other callers never needed
    one either) - Buckling specifically needs a genuine static reference load
    pattern to build its geometric stiffness from (see buckling_solver.py's
    own module docstring), so a model built with only that helper correctly
    fails here.

    This is NOT about ``geomTransf('Linear', ...)`` - the exporter always
    emits ``Linear`` for every analysis kind, and ``run_buckling_analysis``
    already transparently overrides every geomTransf call to 'PDelta' at
    execution time (``ModelCommandCollector.install(geom_transf_override=
    ...)``, confirmed independently while investigating this - see the
    Phase 2-D session report) - so no exporter change was needed for
    Buckling to run. The only missing piece was ever the reference load, as
    ``test_3d_canvas_buckling_full_pipeline_succeeds_with_a_reference_load``
    right below (same canvas, plus one nodal load) proves by actually
    succeeding."""
    page = _page()
    _build_mass_cantilever(page)

    model = page.canvas.build_model()
    script = export_opensees_script(
        model, include_mass=True, length_unit=page._unit_system.length
    )
    source = tmp_path / "buckling_model.py"
    source.write_text(script, encoding="utf-8")

    service = _analysis_service()
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.BUCKLING,
        options={
            "reference_load_scale": 1.0,
            "num_modes": 1,
            "geometric_transform_type": "PDelta",
        },
    )
    result = service.execute(request)

    assert result.status == AnalysisStatus.FAILED
    assert result.messages


def test_3d_canvas_buckling_full_pipeline_succeeds_with_a_reference_load(
    tmp_path: Path,
) -> None:
    """Verification 5 (Phase 2-D): the real gap was only ever the missing
    reference load - the exact same cantilever as the FAILED test above,
    plus one compressive nodal load at the tip, exported and run through
    ``RunAnalysisService.execute()`` exactly as the canvas's own
    ``_run_full_analysis(AnalysisKind.BUCKLING)`` does, now COMPLETES with a
    real positive buckling load factor and a non-empty mode."""
    page = _page()
    _build_axially_loaded_cantilever(page)

    model = page.canvas.build_model()
    script = export_opensees_script(
        model, include_mass=True, length_unit=page._unit_system.length
    )
    source = tmp_path / "buckling_model_loaded.py"
    source.write_text(script, encoding="utf-8")

    service = _analysis_service()
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.BUCKLING,
        options={
            "reference_load_scale": 1.0,
            "num_modes": 1,
            "geometric_transform_type": "PDelta",
        },
    )
    result = service.execute(request)

    assert result.status == AnalysisStatus.COMPLETED, result.messages
    assert result.buckling_modes
    assert result.buckling_modes[0].buckling_load_factor > 0.0
