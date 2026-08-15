"""Transient solver, verified against an SDOF/2DOF closed-form (Duhamel
integral) response and, for Adaptive Recovery, against the real transient
loop with a single surgically-injected ops.analyze() failure per scenario -
not a fully mocked OpenSeesPy, so the "recovered" step is still a genuine
solve, just one this test told to report failure on its first attempt.

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

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees import time_history_solver as ths_module
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

#: Two uncoupled SDOFs (independent X/Y materials on the same zeroLength) -
#: for multi-direction UniformExcitation tests, each direction's response can
#: still be checked against its own single-DOF Duhamel solution.
_MASS_X, _STIFFNESS_X = 10.0, 1000.0
_MASS_Y, _STIFFNESS_Y = 10.0, 2500.0
_OMEGA_X = math.sqrt(_STIFFNESS_X / _MASS_X)
_OMEGA_Y = math.sqrt(_STIFFNESS_Y / _MASS_Y)
_2DOF_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 2)
ops.node(1, 0.0, 0.0)
ops.node(2, 0.0, 0.0)
ops.fix(1, 1, 1)
ops.mass(2, {mass_x}, {mass_y})
ops.uniaxialMaterial('Elastic', 1, {stiffness_x})
ops.uniaxialMaterial('Elastic', 2, {stiffness_y})
ops.element('zeroLength', 1, 1, 2, '-mat', 1, 2, '-dir', 1, 2)
"""

_DT = 0.01
_NUM_POINTS = 500
_PULSE_AMPLITUDE = 1.0
_PULSE_DURATION = 1.0


def _half_sine_acceleration(time: float) -> float:
    if 0.0 <= time <= _PULSE_DURATION:
        return _PULSE_AMPLITUDE * math.sin(math.pi * time / _PULSE_DURATION)
    return 0.0


def _duhamel_exact_displacement(
    time: float, *, omega: float, damping_ratio: float = 0.0, n_sub: int = 4000
) -> float:
    """Independent numerical Duhamel integral (Simpson's rule), undamped or
    lightly damped, for cross-checking - shares no code with the solver."""
    if time <= 0.0:
        return 0.0
    omega_d = omega * math.sqrt(1.0 - damping_ratio**2) if damping_ratio < 1.0 else omega
    step = time / n_sub
    total = 0.0
    for index in range(n_sub + 1):
        tau = index * step
        decay = math.exp(-damping_ratio * omega * (time - tau)) if damping_ratio > 0.0 else 1.0
        value = _half_sine_acceleration(tau) * decay * math.sin(omega_d * (time - tau))
        weight = 1 if index in (0, n_sub) else (4 if index % 2 == 1 else 2)
        total += weight * value
    integral = total * step / 3.0
    return -(1.0 / omega_d) * integral


def _write_sdof_model(tmp_path: Path, name: str = "sdof.py") -> Path:
    path = tmp_path / name
    path.write_text(_SDOF_MODEL.format(mass=_MASS, stiffness=_STIFFNESS), encoding="utf-8")
    return path


def _write_2dof_model(tmp_path: Path) -> Path:
    path = tmp_path / "twodof.py"
    path.write_text(
        _2DOF_MODEL.format(
            mass_x=_MASS_X, mass_y=_MASS_Y, stiffness_x=_STIFFNESS_X, stiffness_y=_STIFFNESS_Y
        ),
        encoding="utf-8",
    )
    return path


def _write_ground_motion(
    tmp_path: Path, name: str = "half_sine.txt", *, dt: float = _DT, num_points: int = _NUM_POINTS
) -> Path:
    values = [_half_sine_acceleration(index * dt) for index in range(num_points)]
    lines = [f"NPTS= {num_points}, DT= {dt:.4f} SEC"]
    for start in range(0, num_points, 5):
        lines.append(" ".join(f"{value:.8f}" for value in values[start : start + 5]))
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_half_sine_ground_motion(tmp_path: Path) -> Path:
    return _write_ground_motion(tmp_path)


def _direction(dof: int, path: Path, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "dof": dof,
        "path": str(path),
        "unit": "model",
        "scaling_method": "factor",
        "scale_factor": 1.0,
        "target_pga": 0.0,
    }
    base.update(overrides)
    return base


def _displacement_at(steps: list[dict], target_time: float, node_tag: int = 2, component: int = 0) -> float:
    closest = min(steps, key=lambda step: abs(step["time"] - target_time))
    node = next(item for item in closest["node_results"] if item["node_tag"] == node_tag)
    return node["displacement"][component]


def _node_result_at(steps: list[dict], target_time: float, node_tag: int) -> dict:
    closest = min(steps, key=lambda step: abs(step["time"] - target_time))
    return next(item for item in closest["node_results"] if item["node_tag"] == node_tag)


# -- 1/2. Single-direction Built-in-shaped file / plain-file record --------


def test_undamped_sdof_matches_the_duhamel_integral_for_a_smooth_pulse(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
    )

    assert result["status"] == "completed"
    assert result["messages"] == []
    steps = result["time_history"]
    assert len(steps) == _NUM_POINTS - 1  # End Time = record Duration = dt*(NPTS-1)

    for target_time in (0.1, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 4.9):
        actual = _displacement_at(steps, target_time)
        expected = _duhamel_exact_displacement(target_time, omega=_OMEGA)
        assert actual == pytest.approx(expected, abs=1.0e-4)


def test_velocity_and_acceleration_are_recorded_for_every_node(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model, directions=[_direction(1, motion)], damping={"mode": "none"}
    )

    late_step = result["time_history"][300]
    for node_tag in (1, 2):
        node = next(item for item in late_step["node_results"] if item["node_tag"] == node_tag)
        assert len(node["velocity"]) == 1
        assert len(node["acceleration"]) == 1


def test_relative_response_matches_the_governing_ode(tmp_path: Path) -> None:
    """UniformExcitation results are RELATIVE (see time_history_solver.py's
    module docstring and SETUP's own Ground Motion card note) - checked
    against the governing ODE's exact relative acceleration, and explicitly
    checked to NOT match the absolute/total acceleration."""
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model, directions=[_direction(1, motion)], damping={"mode": "none"}
    )
    steps = result["time_history"]

    def exact_relative_acceleration(time: float) -> float:
        u_rel = _duhamel_exact_displacement(time, omega=_OMEGA)
        return -_half_sine_acceleration(time) - _OMEGA**2 * u_rel

    for target_time in (0.3, 0.5, 0.7, 1.0, 1.5, 2.0):
        node = _node_result_at(steps, target_time, node_tag=2)
        recorded_accel = node["acceleration"][0]
        exact_relative = exact_relative_acceleration(target_time)
        exact_absolute = exact_relative + _half_sine_acceleration(target_time)
        assert recorded_accel == pytest.approx(exact_relative, abs=5.0e-3)
        if abs(_half_sine_acceleration(target_time)) > 0.05:
            assert recorded_accel != pytest.approx(exact_absolute, abs=5.0e-3)


def test_a_real_bundled_kobe_at2_file_still_runs_end_to_end(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    kobe_at2 = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "openframe"
        / "infrastructure"
        / "ground_motions"
        / "data"
        / "RSN1116_KOBE_SHI-UP.AT2"
    )

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, kobe_at2, unit="g")],
        damping={"mode": "direct", "alpha_m": 0.1},
    )

    assert result["status"] == "completed"
    assert len(result["time_history"]) == 4095


# -- 3. Multi-direction (X/Y) UniformExcitation -----------------------------


def test_x_and_y_directions_each_respond_independently_to_their_own_record(
    tmp_path: Path,
) -> None:
    model = _write_2dof_model(tmp_path)
    motion_x = _write_ground_motion(tmp_path, "gm_x.txt")
    motion_y = _write_ground_motion(tmp_path, "gm_y.txt")

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion_x), _direction(2, motion_y)],
        damping={"mode": "none"},
    )

    assert result["status"] == "completed"
    steps = result["time_history"]
    settings = result["settings"]
    assert {entry["dof"] for entry in settings["directions"]} == {1, 2}

    for target_time in (0.3, 0.7, 1.5, 3.0):
        actual_x = _displacement_at(steps, target_time, node_tag=2, component=0)
        actual_y = _displacement_at(steps, target_time, node_tag=2, component=1)
        expected_x = _duhamel_exact_displacement(target_time, omega=_OMEGA_X)
        expected_y = _duhamel_exact_displacement(target_time, omega=_OMEGA_Y)
        assert actual_x == pytest.approx(expected_x, abs=1.0e-4)
        assert actual_y == pytest.approx(expected_y, abs=1.0e-4)


# -- 4. Invalid / duplicate directions are blocked ---------------------------


def test_rejects_a_direction_outside_the_model_ndf(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    with pytest.raises(RuntimeError, match="DIRECTION"):
        run_time_history_analysis(model, directions=[_direction(2, motion)])


def test_rejects_the_same_direction_activated_twice(tmp_path: Path) -> None:
    model = _write_2dof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    with pytest.raises(RuntimeError, match="동일한 방향"):
        run_time_history_analysis(
            model, directions=[_direction(1, motion), _direction(1, motion)]
        )


def test_rejects_no_active_directions(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)

    with pytest.raises(RuntimeError, match="활성화된 지진파 방향"):
        run_time_history_analysis(model, directions=[])


# -- 5/6/7. Unit conversion, Direct Scale Factor, Target PGA -----------------


def test_g_unit_conversion_matches_a_manually_pre_scaled_model_unit_record(
    tmp_path: Path,
) -> None:
    """A record whose raw values ARE g's, run with unit="g", must match a
    record whose raw values were pre-multiplied by standard gravity and run
    with unit="model" - the two are physically the same excitation."""
    from openframe.core.domain.units import STANDARD_GRAVITY_M_S2

    model = _write_sdof_model(tmp_path)
    raw_g_motion = _write_half_sine_ground_motion(tmp_path)

    result_g = run_time_history_analysis(
        model, directions=[_direction(1, raw_g_motion, unit="g")], damping={"mode": "none"}
    )
    result_model = run_time_history_analysis(
        model,
        directions=[_direction(1, raw_g_motion, unit="model", scale_factor=STANDARD_GRAVITY_M_S2)],
        damping={"mode": "none"},
    )

    for target_time in (0.3, 0.7, 1.5, 3.0):
        assert _displacement_at(result_g["time_history"], target_time) == pytest.approx(
            _displacement_at(result_model["time_history"], target_time), rel=1.0e-9
        )


def test_scale_factor_linearly_scales_the_response(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    baseline = run_time_history_analysis(
        model, directions=[_direction(1, motion, scale_factor=1.0)], damping={"mode": "none"}
    )
    scaled = run_time_history_analysis(
        model, directions=[_direction(1, motion, scale_factor=2.0)], damping={"mode": "none"}
    )

    for target_time in (0.3, 0.7, 1.5, 3.0):
        base_disp = _displacement_at(baseline["time_history"], target_time)
        scaled_disp = _displacement_at(scaled["time_history"], target_time)
        assert scaled_disp == pytest.approx(2.0 * base_disp, abs=1.0e-6)


def test_target_pga_scaling_reaches_the_requested_effective_scale(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    baseline = run_time_history_analysis(
        model, directions=[_direction(1, motion, scale_factor=1.0)], damping={"mode": "none"}
    )
    target_pga = 2.5 * _PULSE_AMPLITUDE
    scaled = run_time_history_analysis(
        model,
        directions=[
            _direction(1, motion, scaling_method="target_pga", target_pga=target_pga)
        ],
        damping={"mode": "none"},
    )

    assert scaled["settings"]["directions"][0]["effective_scale"] == pytest.approx(2.5)
    for target_time in (0.3, 0.7, 1.5):
        base_disp = _displacement_at(baseline["time_history"], target_time)
        scaled_disp = _displacement_at(scaled["time_history"], target_time)
        assert scaled_disp == pytest.approx(2.5 * base_disp, abs=1.0e-6)


def test_target_pga_rejects_a_zero_pga_record(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    silent_motion_path = tmp_path / "silent.txt"
    silent_motion_path.write_text("NPTS= 10, DT= 0.01 SEC\n" + "0.0 " * 10 + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="TARGET PGA"):
        run_time_history_analysis(
            model,
            directions=[
                _direction(1, silent_motion_path, scaling_method="target_pga", target_pga=1.0)
            ],
        )


# -- 8. Different Record dt per direction ------------------------------------


def test_directions_keep_their_own_record_dt_when_they_differ(tmp_path: Path) -> None:
    model = _write_2dof_model(tmp_path)
    motion_x = _write_ground_motion(tmp_path, "gm_x_fine.txt", dt=0.005, num_points=1000)
    motion_y = _write_ground_motion(tmp_path, "gm_y_coarse.txt", dt=0.02, num_points=250)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion_x), _direction(2, motion_y)],
        damping={"mode": "none"},
        analysis_time={"duration_mode": "custom", "end_time": 2.0, "dt": 0.005},
    )

    assert result["status"] == "completed"
    for target_time in (0.5, 1.0, 1.5):
        actual_x = _displacement_at(result["time_history"], target_time, node_tag=2, component=0)
        actual_y = _displacement_at(result["time_history"], target_time, node_tag=2, component=1)
        expected_x = _duhamel_exact_displacement(target_time, omega=_OMEGA_X)
        expected_y = _duhamel_exact_displacement(target_time, omega=_OMEGA_Y)
        assert actual_x == pytest.approx(expected_x, abs=2.0e-4)
        assert actual_y == pytest.approx(expected_y, abs=2.0e-4)


# -- 9. Final step lands exactly on End Time ---------------------------------


def test_final_step_lands_exactly_on_a_non_multiple_end_time(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        analysis_time={"duration_mode": "custom", "end_time": 1.0, "dt": 0.03},
    )

    assert result["status"] == "completed"
    last_step = result["time_history"][-1]
    assert last_step["time"] == pytest.approx(1.0, abs=1.0e-9)
    # 33 full 0.03 steps land at 0.99; the 34th is clipped to the remaining 0.01.
    assert len(result["time_history"]) == 34


# -- 10/11. Newmark and HHT command mapping ----------------------------------


def test_newmark_command_receives_the_configured_gamma_and_beta(tmp_path, monkeypatch) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)
    calls: list[tuple] = []
    real_integrator = ops.integrator

    def recording_integrator(*args, **kwargs):
        calls.append(args)
        return real_integrator(*args, **kwargs)

    monkeypatch.setattr(ops, "integrator", recording_integrator)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        integrator={"type": "Newmark", "gamma": 0.6, "beta": 0.3025},
    )

    assert result["status"] == "completed"
    assert ("Newmark", 0.6, 0.3025) in calls
    assert result["settings"]["integrator_type"] == "Newmark"
    assert dict(result["settings"]["integrator_params"]) == {"gamma": 0.6, "beta": 0.3025}


def test_hht_auto_mode_issues_the_two_argument_command(tmp_path, monkeypatch) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)
    calls: list[tuple] = []
    real_integrator = ops.integrator

    def recording_integrator(*args, **kwargs):
        calls.append(args)
        return real_integrator(*args, **kwargs)

    monkeypatch.setattr(ops, "integrator", recording_integrator)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        integrator={"type": "HHT", "alpha": 0.8, "parameter_mode": "auto"},
    )

    assert result["status"] == "completed"
    assert ("HHT", 0.8) in calls
    assert not any(call[0] == "HHT" and len(call) > 2 for call in calls)
    params = dict(result["settings"]["integrator_params"])
    assert params["gamma"] == pytest.approx(1.5 - 0.8)
    assert params["beta"] == pytest.approx((2.0 - 0.8) ** 2 / 4.0)


def test_hht_custom_mode_issues_the_four_argument_command(tmp_path, monkeypatch) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)
    calls: list[tuple] = []
    real_integrator = ops.integrator

    def recording_integrator(*args, **kwargs):
        calls.append(args)
        return real_integrator(*args, **kwargs)

    monkeypatch.setattr(ops, "integrator", recording_integrator)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        integrator={
            "type": "HHT",
            "alpha": 0.75,
            "parameter_mode": "custom",
            "gamma": 0.65,
            "beta": 0.32,
        },
    )

    assert result["status"] == "completed"
    assert ("HHT", 0.75, 0.65, 0.32) in calls


def test_hht_alpha_outside_the_supported_range_is_rejected(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    with pytest.raises(RuntimeError, match="ALPHA"):
        run_time_history_analysis(
            model,
            directions=[_direction(1, motion)],
            integrator={"type": "HHT", "alpha": 0.5},
        )


# -- 12/13/14. Rayleigh damping: Modal Targets, Direct Coefficients, None ----


def test_modal_targets_rayleigh_coefficients_reproduce_the_requested_ratios(
    tmp_path: Path,
) -> None:
    """Verifies alphaM/beta actually satisfy the two-mode Rayleigh system
    (alphaM + beta*wi^2 = 2*ratio_i*wi) at BOTH requested modes' own
    (independently, ops.eigen-computed) angular frequencies - not merely that
    some numbers came back."""
    model = _write_2dof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={
            "mode": "modal",
            "mode_i": 1,
            "mode_j": 2,
            "ratio_i": 0.05,
            "ratio_j": 0.08,
            "stiffness_term": "initial",
        },
    )

    assert result["status"] == "completed"
    settings = result["settings"]
    assert settings["damping_mode"] == "modal"
    alpha_m = settings["rayleigh_alpha_m"]
    beta_k_init = settings["rayleigh_beta_k_init"]
    assert settings["rayleigh_beta_k"] == 0.0
    assert settings["rayleigh_beta_k_comm"] == 0.0

    # The two uncoupled SDOFs' own natural frequencies are the model's modes.
    for omega, ratio in ((_OMEGA_X, 0.05), (_OMEGA_Y, 0.08)):
        implied_ratio = (alpha_m + beta_k_init * omega**2) / (2.0 * omega)
        assert implied_ratio == pytest.approx(ratio, rel=1.0e-6)


def test_modal_targets_assigns_beta_to_the_selected_stiffness_term_only(
    tmp_path: Path,
) -> None:
    model = _write_2dof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={
            "mode": "modal",
            "mode_i": 1,
            "mode_j": 2,
            "ratio_i": 0.05,
            "ratio_j": 0.05,
            "stiffness_term": "last_committed",
        },
    )

    settings = result["settings"]
    assert settings["rayleigh_beta_k"] == 0.0
    assert settings["rayleigh_beta_k_init"] == 0.0
    assert settings["rayleigh_beta_k_comm"] != 0.0


def test_modal_targets_rejects_duplicate_modes(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    with pytest.raises(RuntimeError, match="Mode i와 Mode j"):
        run_time_history_analysis(
            model,
            directions=[_direction(1, motion)],
            damping={"mode": "modal", "mode_i": 1, "mode_j": 1},
        )


def test_direct_coefficients_are_passed_through_exactly(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={
            "mode": "direct",
            "alpha_m": 0.12,
            "beta_k": 0.001,
            "beta_k_init": 0.002,
            "beta_k_comm": 0.003,
        },
    )

    settings = result["settings"]
    assert settings["damping_mode"] == "direct"
    assert settings["rayleigh_alpha_m"] == pytest.approx(0.12)
    assert settings["rayleigh_beta_k"] == pytest.approx(0.001)
    assert settings["rayleigh_beta_k_init"] == pytest.approx(0.002)
    assert settings["rayleigh_beta_k_comm"] == pytest.approx(0.003)


def test_damping_none_clears_all_four_rayleigh_coefficients_from_a_prior_run(
    tmp_path: Path,
) -> None:
    """A second, independent run using damping "none" on a freshly-built
    model must show zero damping - proving ops.rayleigh(0,0,0,0) is issued
    unconditionally rather than merely skipped for this mode."""
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "direct", "alpha_m": 5.0, "beta_k": 5.0},
    )
    second_model = _write_sdof_model(tmp_path, name="sdof2.py")
    result = run_time_history_analysis(
        second_model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
    )

    assert result["settings"]["rayleigh_alpha_m"] == 0.0
    assert result["settings"]["rayleigh_beta_k"] == 0.0
    for target_time in (0.5, 1.0, 2.0, 3.0):
        actual = _displacement_at(result["time_history"], target_time)
        expected = _duhamel_exact_displacement(target_time, omega=_OMEGA)
        assert actual == pytest.approx(expected, abs=1.0e-4)


def test_damping_reduces_the_late_time_response_relative_to_undamped(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    undamped = run_time_history_analysis(
        model, directions=[_direction(1, motion)], damping={"mode": "none"}
    )
    damped = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "direct", "alpha_m": 2.0 * 0.10 * _OMEGA},
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


# -- 15-20. Adaptive Recovery: fallback, dt reduction, restoration, partial -

def _recovery_options(**overrides: object) -> dict[str, object]:
    options = {
        "automatic": True,
        "algorithm_fallback": True,
        "min_dt": 0.0,
        "reduction_factor": 0.5,
        "restoration_factor": 1.5,
        "max_reductions": 4,
        "clean_steps_to_restore": 3,
    }
    options.update(overrides)
    return options


def test_algorithm_fallback_recovers_a_step_and_the_next_step_returns_to_primary(
    tmp_path: Path, monkeypatch
) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)
    real_analyze = ops.analyze
    call_count = {"n": 0}

    def fake_analyze(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return -1  # force the very first attempt (primary algorithm) to fail
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(ths_module.ops, "analyze", fake_analyze)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        solution={"algorithm": "Newton"},
        recovery=_recovery_options(),
    )

    assert result["status"] == "completed"
    first_step = result["time_history"][0]
    assert first_step["recovered"] is True
    assert first_step["dt_reduction_count"] == 0
    assert first_step["retry_count"] >= 1
    assert first_step["algorithm_used"] != "Newton"
    # The step that needed a fallback still returns to the PRIMARY algorithm
    # on the very next step - Adaptive Recovery does not "stick" with what
    # last worked.
    second_step = result["time_history"][1]
    assert second_step["algorithm_used"] == "Newton"
    assert second_step["recovered"] is False


def test_dt_is_reduced_when_every_algorithm_fails_at_the_nominal_step(
    tmp_path: Path, monkeypatch
) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)
    real_analyze = ops.analyze
    call_count = {"n": 0}

    def fake_analyze(*args, **kwargs):
        call_count["n"] += 1
        # 4 standard algorithms all "fail" once each at the nominal dt, so
        # the ladder must fall through to a halved dt before succeeding.
        if call_count["n"] <= 4:
            return -1
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(ths_module.ops, "analyze", fake_analyze)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        solution={"algorithm": "Newton"},
        recovery=_recovery_options(),
        analysis_time={"duration_mode": "full", "dt": 0.02},
    )

    assert result["status"] == "completed"
    first_step = result["time_history"][0]
    assert first_step["dt_reduction_count"] == 1
    assert first_step["actual_dt"] == pytest.approx(0.01)


def test_a_permanently_failing_step_ends_the_run_as_partial_without_duplicate_steps(
    tmp_path: Path, monkeypatch
) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)
    real_analyze = ops.analyze
    call_count = {"n": 0}
    #: The first ops.analyze() call is step 1's own first (real) attempt -
    #: let it succeed so there is a genuine preceding step, then fail every
    #: call after that forever, forcing step 2 to exhaust its whole ladder.
    def fake_analyze(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return real_analyze(*args, **kwargs)
        return -1

    monkeypatch.setattr(ths_module.ops, "analyze", fake_analyze)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        recovery=_recovery_options(max_reductions=2, min_dt=0.001),
        analysis_time={"duration_mode": "full", "dt": 0.01},
    )

    assert result["status"] == "partial"
    # Only the one genuinely-successful step is present - none of step 2's
    # many failed attempts left a duplicate or partial entry behind.
    assert len(result["time_history"]) == 1
    assert any("수렴하지 않아" in message for message in result["messages"])


def test_recovery_disabled_stops_immediately_on_the_first_failure(
    tmp_path: Path, monkeypatch
) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)
    real_analyze = ops.analyze
    call_count = {"n": 0}

    def fake_analyze(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return real_analyze(*args, **kwargs)
        return -1

    monkeypatch.setattr(ths_module.ops, "analyze", fake_analyze)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        recovery=_recovery_options(automatic=False),
        analysis_time={"duration_mode": "full", "dt": 0.01},
    )

    assert result["status"] == "partial"
    assert len(result["time_history"]) == 1
    # Exactly one attempt for the failing step (call #2) - no fallback ladder,
    # no dt reduction ladder, when Automatic Recovery is off.
    assert call_count["n"] == 2


def test_dt_restores_after_enough_consecutive_clean_steps(tmp_path: Path, monkeypatch) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)
    real_analyze = ops.analyze
    call_count = {"n": 0}

    def fake_analyze(*args, **kwargs):
        call_count["n"] += 1
        # Fail every algorithm at the nominal dt exactly once (forcing one dt
        # reduction on step 1), then let every subsequent call succeed for
        # real - a long run of clean steps follows.
        if call_count["n"] <= 4:
            return -1
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(ths_module.ops, "analyze", fake_analyze)

    result = run_time_history_analysis(
        model,
        directions=[_direction(1, motion)],
        damping={"mode": "none"},
        recovery=_recovery_options(clean_steps_to_restore=3, restoration_factor=1.5),
        analysis_time={"duration_mode": "full", "dt": 0.02, "max_dt": 0.02},
    )

    assert result["status"] == "completed"
    steps = result["time_history"]
    assert steps[0]["actual_dt"] == pytest.approx(0.01)  # reduced from 0.02
    # After 3 clean steps (steps 2, 3, 4), step 5 restores toward 0.02.
    later_dts = [step["actual_dt"] for step in steps[4:8]]
    assert max(later_dts) > 0.01
    assert max(later_dts) <= 0.02 + 1.0e-9


# -- 21/22. Real transient benchmark: linear SDOF vs. Duhamel, 2x scale ------


def test_linear_sdof_transient_benchmark_matches_duhamel_within_tight_tolerance(
    tmp_path: Path,
) -> None:
    """The one required real (non-mocked) OpenSees transient benchmark:
    undamped linear SDOF response to a smooth pulse, compared against an
    independently-computed Duhamel integral - already exercised at the top
    of this file (test_undamped_sdof_matches_the_duhamel_integral_for_a_smooth_pulse)
    and reused here under the spec's own item 21/22 naming for traceability."""
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    result = run_time_history_analysis(
        model, directions=[_direction(1, motion)], damping={"mode": "none"}
    )
    for target_time in (0.5, 1.0, 2.0, 4.0):
        actual = _displacement_at(result["time_history"], target_time)
        expected = _duhamel_exact_displacement(target_time, omega=_OMEGA)
        assert actual == pytest.approx(expected, abs=1.0e-4)


def test_doubling_the_input_ground_motion_doubles_the_linear_response(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)
    motion = _write_half_sine_ground_motion(tmp_path)

    baseline = run_time_history_analysis(
        model, directions=[_direction(1, motion, scale_factor=1.0)], damping={"mode": "none"}
    )
    doubled = run_time_history_analysis(
        model, directions=[_direction(1, motion, scale_factor=2.0)], damping={"mode": "none"}
    )

    for target_time in (0.3, 0.7, 1.5, 3.0):
        base_disp = _displacement_at(baseline["time_history"], target_time)
        doubled_disp = _displacement_at(doubled["time_history"], target_time)
        assert doubled_disp == pytest.approx(2.0 * base_disp, abs=1.0e-6)


def test_reports_a_missing_ground_motion_file_as_a_runtime_error(tmp_path: Path) -> None:
    model = _write_sdof_model(tmp_path)

    with pytest.raises(RuntimeError, match="지진파"):
        run_time_history_analysis(
            model, directions=[_direction(1, tmp_path / "does_not_exist.txt")]
        )


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
        run_time_history_analysis(path, directions=[_direction(1, motion)])
