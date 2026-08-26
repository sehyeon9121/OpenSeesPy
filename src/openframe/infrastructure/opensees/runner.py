"""GUI-side controller for the isolated OpenSees worker process."""

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openframe.core.domain import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisStatus,
    BucklingMode,
    ElementResult,
    LoadDisplacementPoint,
    ModeShape,
    NodeResult,
    NonlinearConvergence,
    ResponseSpectrumSettings,
    TimeHistoryDirectionSummary,
    TimeHistorySettings,
    TimeHistoryStep,
)


def _uniform_load(values: Any) -> tuple[float, float, float, float]:
    """Real OpenSeesPy analyses only ever carry a plain constant (wx, wy) -
    OpenSees itself has no linearly-varying eleLoad type - so the pair is
    duplicated into the (wx_i, wy_i, wx_j, wy_j) shape ``ElementResult``
    expects, with i == j."""
    padded = (*values, 0.0, 0.0)
    wx, wy = float(padded[0]), float(padded[1])
    return wx, wy, wx, wy


class OpenSeesProcessRunner:
    def __init__(
        self,
        timeout_seconds: float = 30.0,
        nonlinear_timeout_seconds: float = 600.0,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._nonlinear_timeout_seconds = nonlinear_timeout_seconds

    def run(
        self,
        request: AnalysisRequest,
        *,
        progress_callback: Callable[[int | None, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> AnalysisResult:
        source = request.source_path.resolve()
        solver_options = dict(request.options)
        requested_timeout = solver_options.pop("execution_timeout_seconds", None)
        if requested_timeout is not None:
            timeout_seconds = max(1.0, min(float(requested_timeout), 86_400.0))
        elif str(request.kind) in (
            "nonlinear_static",
            "time_history",
            "buckling",
            "response_spectrum",
        ):
            # A time-history run repeats the same per-step solve as many times
            # as the ground motion has points (often thousands) - the same
            # "this can genuinely take a while" reasoning as the nonlinear
            # pushover's own extended timeout, not the plain 30s default.
            # Buckling's own two solves are cheap, but extracting/reshaping a
            # dense N-by-N FullGeneral matrix and running scipy.linalg.eig on it
            # is O(n^3) - slow enough on a large model to need the same room.
            # Response spectrum re-solves the model once per (mode, direction)
            # pair on top of its own eigen solve - the same "many repeated
            # solves" shape as time history's, just bounded by mode count
            # instead of record length.
            timeout_seconds = self._nonlinear_timeout_seconds
        else:
            timeout_seconds = self._timeout_seconds

        with tempfile.TemporaryDirectory(prefix="openframe-analysis-") as temporary_directory:
            output = Path(temporary_directory) / "results.json"
            progress_output = Path(temporary_directory) / "progress.json"
            stdout_path = Path(temporary_directory) / "worker.stdout.log"
            stderr_path = Path(temporary_directory) / "worker.stderr.log"
            command = [
                sys.executable,
                "-m",
                "openframe.infrastructure.opensees.worker",
                "--source",
                str(source),
                "--output",
                str(output),
                "--mode",
                "analysis",
                "--kind",
                str(request.kind),
                "--options",
                json.dumps(solver_options),
                "--progress",
                str(progress_output),
            ]
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            cancelled = False
            timed_out = False
            last_progress: tuple[int | None, str] | None = None
            with (
                stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_stream,
                stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_stream,
            ):
                process = subprocess.Popen(
                    command,
                    cwd=source.parent,
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    creationflags=creation_flags,
                )
                started = time.monotonic()
                while process.poll() is None:
                    if cancellation_requested is not None and cancellation_requested():
                        cancelled = True
                        self._stop_process(process)
                        break
                    if time.monotonic() - started > timeout_seconds:
                        timed_out = True
                        self._stop_process(process)
                        break
                    last_progress = self._forward_progress(
                        progress_output,
                        progress_callback,
                        last_progress,
                    )
                    time.sleep(0.05)
                if not cancelled and not timed_out:
                    process.wait()
                    self._forward_progress(
                        progress_output,
                        progress_callback,
                        last_progress,
                    )

            if cancelled:
                return AnalysisResult(
                    status=AnalysisStatus.CANCELLED,
                    messages=["해석이 사용자에 의해 취소되었습니다."],
                )
            if timed_out:
                return AnalysisResult(
                    status=AnalysisStatus.FAILED,
                    messages=[f"해석이 {timeout_seconds:g}초 제한을 초과했습니다."],
                )

            if not output.exists():
                detail = (
                    stderr_path.read_text(encoding="utf-8", errors="replace").strip()
                    or stdout_path.read_text(encoding="utf-8", errors="replace").strip()
                )
                return AnalysisResult(
                    status=AnalysisStatus.FAILED,
                    messages=[f"해석 worker가 결과를 만들지 못했습니다. {detail}"],
                )

            payload = json.loads(output.read_text(encoding="utf-8"))

        if not payload.get("ok"):
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[str(payload.get("error", "알 수 없는 해석 오류"))],
            )

        return self._to_domain_result(payload["results"])

    @staticmethod
    def _stop_process(process: subprocess.Popen[object]) -> None:
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)

    @staticmethod
    def _forward_progress(
        path: Path,
        callback: Callable[[int | None, str], None] | None,
        previous: tuple[int | None, str] | None,
    ) -> tuple[int | None, str] | None:
        if callback is None or not path.exists():
            return previous
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            update = (
                None if payload.get("value") is None else int(payload["value"]),
                str(payload.get("stage", "Analysis in progress...")),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return previous
        if update != previous:
            callback(*update)
        return update

    def _to_domain_result(self, payload: dict[str, Any]) -> AnalysisResult:
        node_results = {
            int(item["node_tag"]): NodeResult(
                node_tag=int(item["node_tag"]),
                displacement=tuple(float(value) for value in item.get("displacement", [])),
                reaction=tuple(float(value) for value in item.get("reaction", [])),
            )
            for item in payload.get("node_results", [])
        }
        element_results = {
            int(item["element_tag"]): ElementResult(
                element_tag=int(item["element_tag"]),
                local_forces=tuple(float(value) for value in item.get("local_forces", [])),
                length=float(item.get("length", 0.0)),
                uniform_load=_uniform_load(item.get("uniform_load", ())),
                flexural_rigidity=float(item.get("flexural_rigidity", 0.0)),
            )
            for item in payload.get("element_results", [])
        }
        curve = tuple(
            LoadDisplacementPoint(
                step=int(item["step"]),
                control_displacement=float(item["control_displacement"]),
                base_shear=float(item["base_shear"]),
                attempts=int(item.get("attempts", 1)),
                substeps=int(item.get("substeps", 1)),
                iterations=int(item.get("iterations", 0)),
                recovered_with=tuple(str(value) for value in item.get("recovered_with", [])),
                load_factor=float(item.get("load_factor", 0.0)),
                arc_length_radius=(
                    None
                    if item.get("arc_length_radius") is None
                    else float(item["arc_length_radius"])
                ),
                algorithm_used=str(item.get("algorithm_used", "")),
                recovered=bool(item.get("recovered", False)),
                retry_count=int(item.get("retry_count", 0)),
            )
            for item in payload.get("load_displacement_curve", [])
        )
        convergence_payload = payload.get("convergence")
        convergence = (
            NonlinearConvergence(
                requested_steps=int(convergence_payload.get("requested_steps", len(curve))),
                completed_steps=int(convergence_payload.get("completed_steps", len(curve))),
                failed_step=(
                    None
                    if convergence_payload.get("failed_step") is None
                    else int(convergence_payload["failed_step"])
                ),
                total_attempts=int(convergence_payload.get("total_attempts", 0)),
                total_substeps=int(convergence_payload.get("total_substeps", 0)),
                recovered_steps=tuple(
                    int(value) for value in convergence_payload.get("recovered_steps", [])
                ),
            )
            if isinstance(convergence_payload, dict)
            else None
        )
        mode_shapes = tuple(
            ModeShape(
                mode_number=int(item["mode_number"]),
                eigenvalue=float(item["eigenvalue"]),
                angular_frequency=float(item["angular_frequency"]),
                frequency_hz=float(item["frequency_hz"]),
                period=float(item["period"]),
                node_results={
                    int(node["node_tag"]): NodeResult(
                        node_tag=int(node["node_tag"]),
                        displacement=tuple(float(value) for value in node.get("displacement", [])),
                    )
                    for node in item.get("node_results", [])
                },
                mass_participation_ratio=tuple(
                    float(value) for value in item.get("mass_participation_ratio", [])
                ),
            )
            for item in payload.get("mode_shapes", [])
        )
        buckling_modes = tuple(
            BucklingMode(
                mode_number=int(item["mode_number"]),
                buckling_load_factor=float(item["buckling_load_factor"]),
                raw_eigenvalue=float(item["raw_eigenvalue"]),
                node_results={
                    int(node["node_tag"]): NodeResult(
                        node_tag=int(node["node_tag"]),
                        displacement=tuple(float(value) for value in node.get("displacement", [])),
                    )
                    for node in item.get("node_results", [])
                },
                normalized_node_results={
                    int(node["node_tag"]): NodeResult(
                        node_tag=int(node["node_tag"]),
                        displacement=tuple(float(value) for value in node.get("displacement", [])),
                    )
                    for node in item.get("normalized_node_results", [])
                },
                reference_load_case=str(item.get("reference_load_case", "")),
                reference_load_scale=float(item.get("reference_load_scale", 1.0)),
            )
            for item in payload.get("buckling_modes", [])
        )
        time_history = tuple(
            TimeHistoryStep(
                time=float(item["time"]),
                node_results={
                    int(node["node_tag"]): NodeResult(
                        node_tag=int(node["node_tag"]),
                        displacement=tuple(float(value) for value in node.get("displacement", [])),
                        reaction=tuple(float(value) for value in node.get("reaction", [])),
                        velocity=tuple(float(value) for value in node.get("velocity", [])),
                        acceleration=tuple(float(value) for value in node.get("acceleration", [])),
                    )
                    for node in item.get("node_results", [])
                },
                actual_dt=float(item.get("actual_dt", 0.0)),
                algorithm_used=str(item.get("algorithm_used", "")),
                recovered=bool(item.get("recovered", False)),
                retry_count=int(item.get("retry_count", 0)),
                dt_reduction_count=int(item.get("dt_reduction_count", 0)),
            )
            for item in payload.get("time_history", [])
        )
        settings_payload = payload.get("settings")
        time_history_settings = (
            TimeHistorySettings(
                directions=tuple(
                    TimeHistoryDirectionSummary(
                        dof=int(item["dof"]),
                        record_name=str(item.get("record_name", "")),
                        effective_scale=float(item.get("effective_scale", 1.0)),
                    )
                    for item in settings_payload.get("directions", [])
                ),
                integrator_type=str(settings_payload.get("integrator_type", "")),
                integrator_params=tuple(
                    (str(name), float(value)) for name, value in settings_payload.get("integrator_params", [])
                ),
                damping_mode=str(settings_payload.get("damping_mode", "")),
                rayleigh_alpha_m=float(settings_payload.get("rayleigh_alpha_m", 0.0)),
                rayleigh_beta_k=float(settings_payload.get("rayleigh_beta_k", 0.0)),
                rayleigh_beta_k_init=float(settings_payload.get("rayleigh_beta_k_init", 0.0)),
                rayleigh_beta_k_comm=float(settings_payload.get("rayleigh_beta_k_comm", 0.0)),
                initial_dt=float(settings_payload.get("initial_dt", 0.0)),
                minimum_dt=float(settings_payload.get("minimum_dt", 0.0)),
                maximum_dt=float(settings_payload.get("maximum_dt", 0.0)),
                end_time=float(settings_payload.get("end_time", 0.0)),
                status=str(settings_payload.get("status", "completed")),
            )
            if isinstance(settings_payload, dict)
            else None
        )
        response_spectrum_payload = payload.get("response_spectrum_settings")
        response_spectrum_settings = (
            ResponseSpectrumSettings(
                num_modes=int(response_spectrum_payload.get("num_modes", 0)),
                directions=tuple(str(value) for value in response_spectrum_payload.get("directions", [])),
                combination_method=str(response_spectrum_payload.get("combination_method", "SRSS")),
                periods=tuple(float(value) for value in response_spectrum_payload.get("periods", [])),
                spectral_accelerations=tuple(
                    float(value)
                    for value in response_spectrum_payload.get("spectral_accelerations", [])
                ),
                acceleration_unit=str(response_spectrum_payload.get("acceleration_unit", "g")),
            )
            if isinstance(response_spectrum_payload, dict)
            else None
        )
        try:
            status = AnalysisStatus(str(payload.get("status", "completed")))
        except ValueError:
            status = AnalysisStatus.FAILED
        return AnalysisResult(
            status=status,
            node_results=node_results,
            element_results=element_results,
            messages=[str(message) for message in payload.get("messages", [])],
            load_displacement_curve=curve,
            convergence=convergence,
            mode_shapes=mode_shapes,
            time_history=time_history,
            buckling_modes=buckling_modes,
            time_history_settings=time_history_settings,
            response_spectrum_settings=response_spectrum_settings,
        )
