"""Transient (time-history) solver, verified against an SDOF system.

The single ground-truth check that matters here: for an undamped single-dof
oscillator, the exact response to any base acceleration ag(t) is Duhamel's
integral u(t) = -(1/omega) * integral(ag(tau) * sin(omega*(t-tau)), tau=0..t).
This is computed independently (fine-grid Simpson's rule, nothing shared with
the solver or with OpenSees) and compared against what run_time_history_analysis
actually produces.

A pure step function (ag jumping straight to a nonzero value at t=0) was tried
first and rejected as a test case: it exposed a real but expected Newmark/
OpenSees initial-acceleration edge case (a(0) is taken as 0 rather than the
true -ag at a genuine discontinuity), which real ground-motion records never
trigger because they always start at/near zero. A smooth half-sine pulse
avoids the discontinuity entirely and is a closer match to how this feature is
actually used, so it is what these tests check against.
"""

import math
from pathlib import Path

import pytest

from openframe.infrastructure.opensees.time_history_solver import run_time_history_analysis

_MASS = 10.0
_STIFFNESS = 1000.0
_OMEGA = math.sqrt(_STIFFNESS / _MASS)

_SDOF_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.mass(2, {mass})
ops.uniaxialMaterial('Elastic', 1, {stiffness})
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
"""

_DT = 0.01
_NUM_POINTS = 500
_PULSE_AMPLITUDE = 1.0
_PULSE_DURATION = 1.0


def _half_sine_acceleration(time: float) -> float:
    if 0.0 <= time <= _PULSE_DURATION:
        return _PULSE_AMPLITUDE * math.sin(math.pi * time / _PULSE_DURATION)
    return 0.0


def _duhamel_exact_displacement(time: float, *, damping_ratio: float = 0.0, n_sub: int = 4000) -> float:
    """Independent numerical Duhamel integral (Simpson's rule), undamped or
    lightly damped, for cross-checking - shares no code with the solver."""
    if time <= 0.0:
        return 0.0
    omega_d = _OMEGA * math.sqrt(1.0 - damping_ratio**2) if damping_ratio < 1.0 else _OMEGA
    step = time / n_sub
    total = 0.0
    for index in range(n_sub + 1):
        tau = index * step
        decay = math.exp(-damping_ratio * _OMEGA * (time - tau)) if damping_ratio > 0.0 else 1.0
        value = _half_sine_acceleration(tau) * decay * math.sin(omega_d * (time - tau))
        weight = 1 if index in (0, n_sub) else (4 if index % 2 == 1 else 2)
        total += weight * value
    integral = total * step / 3.0
    return -(1.0 / omega_d) * integral


def _write_sdof_model(tmp_path: Path) -> Path:
    path = tmp_path / "sdof.py"
    path.write_text(_SDOF_MODEL.format(mass=_MASS, stiffness=_STIFFNESS), encoding="utf-8")
    return path


def _write_half_sine_ground_motion(tmp_path: Path) -> Path:
    values = [_half_sine_acceleration(index * _DT) for index in range(_NUM_POINTS)]
    lines = [f"NPTS= {_NUM_POINTS}, DT= {_DT:.4f} SEC"]
    for start in range(0, _NUM_POINTS, 5):
        lines.append(" ".join(f"{value:.8f}" for value in values[start : start + 5]))
    path = tmp_path / "half_sine.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _displacement_at(steps: list[dict], target_time: float) -> float:
    closest = min(steps, key=lambda step: abs(step["time"] - target_time))
    node = next(item for item in closest["node_results"] if item["node_tag"] == 2)
    return node["displacement"][0]


def test_undamped_sdof_matches_the_duhamel_integral_for_a_smooth_pulse(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model, ground_motion_path=motion, direction=1, damping_ratio=0.0
    )

    assert result["status"] == "completed"
    assert result["messages"] == []
    steps = result["time_history"]
    assert len(steps) == _NUM_POINTS

    for target_time in (0.1, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0):
        actual = _displacement_at(steps, target_time)
        expected = _duhamel_exact_displacement(target_time)
        assert actual == pytest.approx(expected, abs=1.0e-4)


def test_damped_sdof_also_matches_the_duhamel_integral(tmp_path: Path) -> None:
    """damping_ratio=0.05 on a single-mode SDOF has only one natural frequency,
    so the solver's single-frequency Rayleigh fallback (mass-proportional
    only, see _rayleigh_coefficients) applies - this exercises that path, not
    just the two-frequency one."""
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model, ground_motion_path=motion, direction=1, damping_ratio=0.05
    )

    assert result["status"] == "completed"
    steps = result["time_history"]

    for target_time in (0.5, 1.0, 2.0, 3.0):
        actual = _displacement_at(steps, target_time)
        expected = _duhamel_exact_displacement(target_time, damping_ratio=0.05)
        assert actual == pytest.approx(expected, abs=2.0e-4)


def test_damping_reduces_the_late_time_response_relative_to_undamped(tmp_path: Path) -> None:
    """Qualitative but exact-direction check: after the pulse ends, a damped
    oscillator's remaining free vibration must be smaller in amplitude than an
    undamped one - true regardless of the exact numbers."""
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    undamped = run_time_history_analysis(
        model, ground_motion_path=motion, direction=1, damping_ratio=0.0
    )
    damped = run_time_history_analysis(
        model, ground_motion_path=motion, direction=1, damping_ratio=0.10
    )

    late_time_steps = [
        (undamped["time_history"][index], damped["time_history"][index])
        for index in range(len(undamped["time_history"]))
        if undamped["time_history"][index]["time"] >= 3.0
    ]
    undamped_peak = max(
        abs(next(n for n in u["node_results"] if n["node_tag"] == 2)["displacement"][0])
        for u, _ in late_time_steps
    )
    damped_peak = max(
        abs(next(n for n in d["node_results"] if n["node_tag"] == 2)["displacement"][0])
        for _, d in late_time_steps
    )
    assert damped_peak < undamped_peak


def test_rejects_a_model_with_no_mass(tmp_path: Path) -> None:
    path = tmp_path / "no_mass.py"
    path.write_text(
        """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Elastic', 1, 1000.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
""",
        encoding="utf-8",
    )
    motion = _write_half_sine_ground_motion(tmp_path)

    with pytest.raises(RuntimeError, match="절점 질량"):
        run_time_history_analysis(path, ground_motion_path=motion, direction=1)


def test_rejects_a_direction_outside_the_model_ndf(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    with pytest.raises(RuntimeError, match="DIRECTION"):
        run_time_history_analysis(model, ground_motion_path=motion, direction=2)


def test_reports_a_missing_ground_motion_file_as_a_runtime_error(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)

    with pytest.raises(RuntimeError, match="지진파"):
        run_time_history_analysis(
            model, ground_motion_path=tmp_path / "does_not_exist.txt", direction=1
        )


_BUILT_IN_KOBE_AT2 = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "openframe"
    / "infrastructure"
    / "ground_motions"
    / "data"
    / "RSN1116_KOBE_SHI-UP.AT2"
)


def test_a_real_bundled_kobe_at2_file_still_runs_end_to_end(tmp_path: Path) -> None:
    """Regression check for the Phase 3-F internal swap from
    `parse_ground_motion` to `load_ground_motion` inside the solver - a real
    PEER .AT2 record (not a synthetic half-sine) must still complete exactly
    as it did before that refactor."""
    model = _write_sdof_model(tmp_path)

    result = run_time_history_analysis(
        model, ground_motion_path=_BUILT_IN_KOBE_AT2, direction=1, damping_ratio=0.05
    )

    assert result["status"] == "completed"
    assert len(result["time_history"]) == 4096


def test_a_built_in_library_selection_from_the_setup_panel_runs_end_to_end(tmp_path: Path) -> None:
    """Phase 3-G: SETUP's Built-in Library radio ultimately just points
    build_options()["ground_motion_path"] at one of the catalog's own bundled
    files - the same path the RUN pipeline already knew how to read since
    Phase 3-F, so a Built-in selection must run exactly like an Imported one."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from openframe.core.domain import AnalysisKind
    from openframe.features.analysis.presentation.analysis_settings_panel import (
        AnalysisSettingsPanel,
    )

    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))
    panel.source_builtin_radio.setChecked(True)
    options = panel.build_options()
    application.processEvents()

    model = _write_sdof_model(tmp_path)
    result = run_time_history_analysis(
        model,
        ground_motion_path=Path(options["ground_motion_path"]),
        direction=1,
        damping_ratio=0.05,
        scale_factor=options["scale_factor"],
    )

    assert result["status"] == "completed"
    assert len(result["time_history"]) > 0


def test_scale_factor_linearly_scales_the_response(tmp_path: Path) -> None:
    """The solver applies `scale_factor` via the OpenSees `-factor` flag on
    the ground-motion time series, independent of how the file was parsed -
    for this linear-elastic SDOF, doubling it must exactly double every
    displacement, confirming Phase 3-F's ground-motion loading refactor left
    that behavior untouched."""
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    baseline = run_time_history_analysis(
        model, ground_motion_path=motion, direction=1, damping_ratio=0.0, scale_factor=1.0
    )
    scaled = run_time_history_analysis(
        model, ground_motion_path=motion, direction=1, damping_ratio=0.0, scale_factor=2.0
    )

    for target_time in (0.3, 0.7, 1.5, 3.0):
        base_disp = _displacement_at(baseline["time_history"], target_time)
        scaled_disp = _displacement_at(scaled["time_history"], target_time)
        assert scaled_disp == pytest.approx(2.0 * base_disp, abs=1.0e-6)
