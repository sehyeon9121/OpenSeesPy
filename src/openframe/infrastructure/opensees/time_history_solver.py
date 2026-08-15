"""Run a transient (time-history) analysis for an OpenSeesPy source.

Supports one or more independently-configured ground-motion directions
(``UniformExcitation`` per active DOF), a real-time-based step loop (not a
fixed ``num_steps`` multiplication - a step's own dt can shrink under
Adaptive Recovery without desynchronizing the run from ``end_time``),
Rayleigh damping (None / Modal Targets / Direct Coefficients), Newmark or
HHT time integration, a fully user-configurable Solution Strategy, and an
Adaptive Recovery ladder (algorithm fallback, then dt reduction, then dt
restoration after a run of clean steps) mirroring
``nonlinear_static_solver.py``'s own recovery ladder.

Multi-Support Excitation (per-support ground motion) is out of scope - every
active direction excites the whole model uniformly, exactly as OpenSees'
``UniformExcitation`` pattern implies.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.ground_motion import load_ground_motion
from openframe.infrastructure.opensees.ground_motion_scaling import compute_ground_motion_scaling
from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script

#: Algorithms tried, in order, when the configured one fails to converge on a
#: step - mirrors nonlinear_static_solver.py's own ``_FALLBACK_ALGORITHMS``.
_FALLBACK_ALGORITHMS = ("Newton", "ModifiedNewton", "KrylovNewton", "NewtonLineSearch")
_SUPPORTED_ALGORITHMS = set(_FALLBACK_ALGORITHMS)
_SUPPORTED_CONVERGENCE_TESTS = {"NormDispIncr", "NormUnbalance", "EnergyIncr"}
_SUPPORTED_CONSTRAINT_HANDLERS = {"Plain", "Transformation"}
_SUPPORTED_NUMBERERS = {"RCM", "Plain", "AMD"}
_SUPPORTED_SYSTEMS = {"BandGeneral", "UmfPack", "ProfileSPD"}
_SUPPORTED_DAMPING_MODES = {"none", "modal", "direct"}
_SUPPORTED_STIFFNESS_TERMS = {"initial", "current", "last_committed"}
_SUPPORTED_INTEGRATOR_TYPES = {"Newmark", "HHT"}
_HHT_ALPHA_MIN, _HHT_ALPHA_MAX = 0.67, 1.0

#: Reserved tag ranges for the per-direction TimeSeries/Pattern this solver
#: creates itself - offset far above any tag a real model script would
#: plausibly define, so "다방향 TimeSeries tag와 Pattern tag 충돌 여부" can
#: never actually collide (see PRE-CHECK item in the SETUP UI, which reports
#: this check as always-passing for exactly this reason).
_TIME_SERIES_TAG_OFFSET = 800_000_000
_PATTERN_TAG_OFFSET = 850_000_000


def _report_progress(
    callback: Callable[[int | None, str], None] | None, value: int | None, stage: str
) -> None:
    if callback is not None:
        callback(value, stage)


@dataclass(slots=True)
class _StepOutcome:
    actual_dt: float
    algorithm_used: str
    recovered: bool
    retry_count: int
    dt_reduction_count: int


def _analyze_transient_with_fallback(
    step_dt: float, algorithm: str, *, algorithm_fallback: bool
) -> tuple[bool, int, set[str]]:
    """One dt level's worth of attempts: the configured algorithm, then (if
    ``algorithm_fallback``) every other standard algorithm at the same dt.
    Returns (converged, attempts_made, algorithms_that_recovered_it)."""
    recovered_with: set[str] = set()
    attempts = 1
    if ops.analyze(1, step_dt) == 0:
        return True, attempts, recovered_with
    if not algorithm_fallback:
        return False, attempts, recovered_with
    for candidate in _FALLBACK_ALGORITHMS:
        if candidate == algorithm:
            continue
        ops.algorithm(candidate)
        attempts += 1
        converged = ops.analyze(1, step_dt) == 0
        ops.algorithm(algorithm)
        if converged:
            recovered_with.add(candidate)
            return True, attempts, recovered_with
    return False, attempts, recovered_with


def _advance_one_transient_step(
    nominal_dt: float,
    *,
    algorithm: str,
    algorithm_fallback: bool,
    automatic_recovery: bool,
    min_dt: float,
    reduction_factor: float,
    max_reductions: int,
) -> _StepOutcome | None:
    """Cover one reporting step's worth of pseudo-time, retrying with
    algorithm fallback and (if that alone is not enough) a shrunk dt - the
    Adaptive Recovery ladder: try the primary algorithm, then the other
    standard algorithms at the same dt, then halve dt (down to ``min_dt``,
    up to ``max_reductions`` times) and restart the ladder from the primary
    algorithm at the smaller dt.

    ``automatic_recovery=False`` is "Use Settings Only": the configured
    algorithm gets exactly one attempt at ``nominal_dt`` - no fallback, no
    dt reduction - matching nonlinear_static_solver.py's own convention.
    """
    effective_fallback = algorithm_fallback and automatic_recovery
    step_dt = nominal_dt
    total_attempts = 0
    reductions = 0
    while True:
        converged, attempts, recovered_with = _analyze_transient_with_fallback(
            step_dt, algorithm, algorithm_fallback=effective_fallback
        )
        total_attempts += attempts
        if converged:
            algorithm_used = algorithm if not recovered_with else ", ".join(sorted(recovered_with))
            return _StepOutcome(
                actual_dt=step_dt,
                algorithm_used=algorithm_used,
                recovered=bool(recovered_with) or reductions > 0,
                retry_count=total_attempts - 1,
                dt_reduction_count=reductions,
            )
        if not automatic_recovery:
            return None
        reductions += 1
        if reductions > max_reductions:
            return None
        next_dt = step_dt * reduction_factor
        if next_dt < min_dt - 1.0e-12:
            return None
        step_dt = next_dt


def _natural_angular_frequencies(num_modes: int) -> list[float]:
    """``ops.eigen`` frequencies for the requested mode count, ARPACK first
    then FullGenLapack - mirrors the previous single-target-ratio solver's
    own fallback. Never raises: a genuine failure is reported by the caller
    as "could not compute frequencies", not a bare OpenSeesPy exception."""
    try:
        eigenvalues = ops.eigen(num_modes)
    except Exception:  # noqa: BLE001 - OpenSeesPy's own C++-backed exceptions.
        try:
            eigenvalues = ops.eigen("-fullGenLapack", num_modes)
        except Exception:  # noqa: BLE001
            return []
    return [float(value) ** 0.5 for value in eigenvalues]


def _modal_rayleigh_coefficients(
    mode_i: int,
    mode_j: int,
    ratio_i: float,
    ratio_j: float,
) -> tuple[float, float]:
    """(alphaM, beta) solving the two-mode Rayleigh system
    ``alphaM + beta*wi^2 = 2*ratio_i*wi`` / ``alphaM + beta*wj^2 = 2*ratio_j*wj``
    for the requested mode numbers' own angular frequencies. Raises
    RuntimeError (not a silent fallback) on anything that would make the
    result meaningless - callers own the ``ops.eigen`` call and mode-index
    bookkeeping, not this pure arithmetic function."""
    if mode_i == mode_j:
        raise RuntimeError("Mode i와 Mode j는 서로 달라야 합니다.")
    frequencies = _natural_angular_frequencies(max(mode_i, mode_j))
    if len(frequencies) < max(mode_i, mode_j):
        raise RuntimeError(
            "고유진동수를 구하지 못했습니다 - 지점 조건과 질량을 확인하세요."
        )
    w_i, w_j = frequencies[mode_i - 1], frequencies[mode_j - 1]
    if w_i <= 0.0 or w_j <= 0.0:
        raise RuntimeError("계산된 고유진동수가 0 이하입니다.")
    if math.isclose(w_i, w_j, rel_tol=1.0e-12):
        raise RuntimeError("Mode i와 Mode j의 고유진동수가 동일해 Rayleigh 계수를 구할 수 없습니다.")
    beta = 2.0 * (ratio_i * w_i - ratio_j * w_j) / (w_i**2 - w_j**2)
    alpha = 2.0 * ratio_i * w_i - beta * w_i**2
    return alpha, beta


def _resolve_damping(damping: dict[str, Any] | None) -> tuple[str, float, float, float, float]:
    """Return (mode, alphaM, betaK, betaKInit, betaKComm) - the four Rayleigh
    coefficients actually passed to ``ops.rayleigh(...)``. "none" always
    resolves to all-zero, so no previous run's damping state can leak into
    this one (see ``ops.rayleigh`` call site)."""
    damping = damping or {}
    mode = str(damping.get("mode", "none"))
    if mode not in _SUPPORTED_DAMPING_MODES:
        raise RuntimeError(f"지원하지 않는 DAMPING MODE입니다: {mode}")
    if mode == "none":
        return mode, 0.0, 0.0, 0.0, 0.0
    if mode == "direct":
        alpha_m = float(damping.get("alpha_m", 0.0))
        beta_k = float(damping.get("beta_k", 0.0))
        beta_k_init = float(damping.get("beta_k_init", 0.0))
        beta_k_comm = float(damping.get("beta_k_comm", 0.0))
    else:  # "modal"
        mode_i = int(damping.get("mode_i", 1))
        mode_j = int(damping.get("mode_j", 2))
        if mode_i < 1 or mode_j < 1:
            raise RuntimeError("Mode 번호는 1 이상이어야 합니다.")
        ratio_i = float(damping.get("ratio_i", 0.05))
        ratio_j = float(damping.get("ratio_j", 0.05))
        stiffness_term = str(damping.get("stiffness_term", "initial"))
        if stiffness_term not in _SUPPORTED_STIFFNESS_TERMS:
            raise RuntimeError(f"지원하지 않는 STIFFNESS TERM입니다: {stiffness_term}")
        alpha_m, beta = _modal_rayleigh_coefficients(mode_i, mode_j, ratio_i, ratio_j)
        beta_k = beta if stiffness_term == "current" else 0.0
        beta_k_init = beta if stiffness_term == "initial" else 0.0
        beta_k_comm = beta if stiffness_term == "last_committed" else 0.0
    for name, value in (
        ("alphaM", alpha_m),
        ("betaK", beta_k),
        ("betaKInit", beta_k_init),
        ("betaKComm", beta_k_comm),
    ):
        if math.isnan(value) or math.isinf(value):
            raise RuntimeError(f"Rayleigh 계수 {name}가 NaN/Inf로 계산되었습니다.")
    return mode, alpha_m, beta_k, beta_k_init, beta_k_comm


def _resolve_integrator(integrator: dict[str, Any] | None) -> tuple[str, tuple[tuple[str, float], ...]]:
    """Issue ``ops.integrator(...)`` and return (type, params_for_display).
    ``params_for_display`` always carries the effective gamma/beta even for
    HHT AUTO mode (computed here for reporting), even though the 2-argument
    ``ops.integrator("HHT", alpha)`` call lets OpenSees derive them
    internally rather than this function passing them explicitly."""
    integrator = integrator or {}
    integrator_type = str(integrator.get("type", "Newmark"))
    if integrator_type not in _SUPPORTED_INTEGRATOR_TYPES:
        raise RuntimeError(f"지원하지 않는 TIME INTEGRATION 방식입니다: {integrator_type}")
    if integrator_type == "Newmark":
        gamma = float(integrator.get("gamma", 0.5))
        beta = float(integrator.get("beta", 0.25))
        if gamma <= 0.0 or beta <= 0.0:
            raise RuntimeError("GAMMA와 BETA는 0보다 커야 합니다.")
        ops.integrator("Newmark", gamma, beta)
        return integrator_type, (("gamma", gamma), ("beta", beta))
    alpha = float(integrator.get("alpha", 0.9))
    if not _HHT_ALPHA_MIN <= alpha <= _HHT_ALPHA_MAX:
        raise RuntimeError(f"ALPHA는 {_HHT_ALPHA_MIN} 이상 {_HHT_ALPHA_MAX} 이하이어야 합니다.")
    parameter_mode = str(integrator.get("parameter_mode", "auto"))
    if parameter_mode == "custom":
        gamma = float(integrator.get("gamma", 1.5 - alpha))
        beta = float(integrator.get("beta", (2.0 - alpha) ** 2 / 4.0))
        if gamma <= 0.0 or beta <= 0.0:
            raise RuntimeError("GAMMA와 BETA는 0보다 커야 합니다.")
        ops.integrator("HHT", alpha, gamma, beta)
    else:
        gamma = 1.5 - alpha
        beta = (2.0 - alpha) ** 2 / 4.0
        ops.integrator("HHT", alpha)
    return integrator_type, (("alpha", alpha), ("gamma", gamma), ("beta", beta))


def _resolve_solution(solution: dict[str, Any] | None) -> dict[str, Any]:
    solution = solution or {}
    resolved = {
        "algorithm": str(solution.get("algorithm", "Newton")),
        "test_type": str(solution.get("test_type", "NormDispIncr")),
        "tolerance": float(solution.get("tolerance", 1.0e-8)),
        "max_iterations": int(solution.get("max_iterations", 30)),
        "constraints_type": str(solution.get("constraints_type", "Transformation")),
        "numberer": str(solution.get("numberer", "RCM")),
        "system": str(solution.get("system", "BandGeneral")),
    }
    supported_settings = {
        "ALGORITHM": (resolved["algorithm"], _SUPPORTED_ALGORITHMS),
        "CONVERGENCE TEST": (resolved["test_type"], _SUPPORTED_CONVERGENCE_TESTS),
        "CONSTRAINT HANDLER": (resolved["constraints_type"], _SUPPORTED_CONSTRAINT_HANDLERS),
        "NUMBERER": (resolved["numberer"], _SUPPORTED_NUMBERERS),
        "EQUATION SOLVER": (resolved["system"], _SUPPORTED_SYSTEMS),
    }
    for label, (value, supported) in supported_settings.items():
        if value not in supported:
            raise RuntimeError(f"지원하지 않는 {label} 설정입니다: {value}")
    if resolved["tolerance"] <= 0.0:
        raise RuntimeError("TOLERANCE는 0보다 커야 합니다.")
    if resolved["max_iterations"] <= 0:
        raise RuntimeError("MAXIMUM ITERATIONS는 0보다 커야 합니다.")
    return resolved


def _apply_analysis_objects(solution: dict[str, Any], integrator: dict[str, Any] | None) -> tuple[str, tuple[tuple[str, float], ...]]:
    ops.wipeAnalysis()
    ops.constraints(solution["constraints_type"])
    ops.numberer(solution["numberer"])
    ops.system(solution["system"])
    ops.test(solution["test_type"], solution["tolerance"], solution["max_iterations"])
    ops.algorithm(solution["algorithm"])
    integrator_type, integrator_params = _resolve_integrator(integrator)
    ops.analysis("Transient")
    return integrator_type, integrator_params


@dataclass(slots=True)
class _ResolvedDirection:
    dof: int
    ts_tag: int
    pattern_tag: int
    dt: float
    duration: float
    record_name: str
    total_factor: float
    effective_scale: float
    accelerations: tuple[float, ...]


def _resolve_directions(
    directions: list[dict[str, Any]], *, ndf: int, model_length_unit: str
) -> list[_ResolvedDirection]:
    if not directions:
        raise RuntimeError("활성화된 지진파 방향이 없습니다.")
    seen_dofs: set[int] = set()
    resolved: list[_ResolvedDirection] = []
    for index, direction in enumerate(directions):
        dof = int(direction["dof"])
        if not 1 <= dof <= ndf:
            raise RuntimeError(f"DIRECTION {dof}이 모델의 자유도 범위(1~{ndf})를 벗어났습니다.")
        if dof in seen_dofs:
            raise RuntimeError(f"동일한 방향(DOF {dof})이 두 번 이상 활성화되어 있습니다.")
        seen_dofs.add(dof)
        path = Path(direction["path"])
        try:
            motion = load_ground_motion(path)
        except (ValueError, OSError) as error:
            raise RuntimeError(f"DOF {dof}의 지진파 파일을 읽지 못했습니다: {error}") from error
        unit = str(direction.get("unit", "model"))
        scaling_method = str(direction.get("scaling_method", "factor"))
        if scaling_method == "target_pga" and motion.pga <= 0.0:
            raise RuntimeError(
                f"DOF {dof}: TARGET PGA 스케일링을 사용하려면 원본 PGA가 0보다 커야 합니다."
            )
        scaling = compute_ground_motion_scaling(
            original_pga_raw=motion.pga,
            unit=unit,
            length_unit=model_length_unit,
            scaling_method=scaling_method,
            scale_factor=float(direction.get("scale_factor", 1.0)),
            target_pga=float(direction.get("target_pga", 0.0)),
        )
        resolved.append(
            _ResolvedDirection(
                dof=dof,
                ts_tag=_TIME_SERIES_TAG_OFFSET + index,
                pattern_tag=_PATTERN_TAG_OFFSET + index,
                dt=motion.dt,
                duration=motion.duration,
                record_name=motion.name,
                total_factor=scaling.total_factor,
                effective_scale=scaling.effective_scale,
                accelerations=motion.accelerations,
            )
        )
    return resolved


def _resolve_analysis_time(
    analysis_time: dict[str, Any] | None, resolved_directions: list[_ResolvedDirection]
) -> tuple[float, float, float]:
    analysis_time = analysis_time or {}
    duration_mode = str(analysis_time.get("duration_mode", "full"))
    end_time = float(analysis_time.get("end_time", 0.0))
    if duration_mode != "custom" or end_time <= 0.0:
        end_time = max(direction.duration for direction in resolved_directions)
    initial_dt = float(analysis_time.get("dt", 0.0))
    if initial_dt <= 0.0:
        initial_dt = min(direction.dt for direction in resolved_directions)
    max_dt = float(analysis_time.get("max_dt", 0.0))
    if max_dt <= 0.0:
        max_dt = initial_dt
    if end_time <= 0.0:
        raise RuntimeError("END TIME은 0보다 커야 합니다.")
    if initial_dt <= 0.0:
        raise RuntimeError("ANALYSIS TIME STEP은 0보다 커야 합니다.")
    return end_time, initial_dt, max_dt


def _resolve_recovery(
    recovery: dict[str, Any] | None, *, initial_dt: float, max_dt: float
) -> dict[str, Any]:
    recovery = recovery or {}
    automatic = bool(recovery.get("automatic", True))
    # 0 (or absent) is the "Auto" sentinel - same convention as
    # _resolve_analysis_time's own dt/max_dt (extract-then-check, not
    # dict.get's default parameter, since 0.0 is a legitimate present value
    # coming straight from a UI spinbox, not merely "the key was omitted").
    min_dt = float(recovery.get("min_dt", 0.0))
    if min_dt <= 0.0:
        min_dt = initial_dt * 0.0625
    reduction_factor = float(recovery.get("reduction_factor", 0.5))
    restoration_factor = float(recovery.get("restoration_factor", 1.5))
    max_reductions = int(recovery.get("max_reductions", 4))
    clean_steps_to_restore = int(recovery.get("clean_steps_to_restore", 5))
    algorithm_fallback = bool(recovery.get("algorithm_fallback", True))
    if min_dt <= 0.0 or not (min_dt <= initial_dt <= max_dt):
        raise RuntimeError(
            "MINIMUM TIME STEP ≤ ANALYSIS TIME STEP ≤ MAXIMUM TIME STEP 순서여야 합니다."
        )
    if not 0.0 < reduction_factor < 1.0:
        raise RuntimeError("TIME STEP REDUCTION은 0과 1 사이여야 합니다.")
    if restoration_factor <= 1.0:
        raise RuntimeError("TIME STEP RESTORATION은 1보다 커야 합니다.")
    if max_reductions < 0:
        raise RuntimeError("MAXIMUM STEP REDUCTIONS는 0 이상이어야 합니다.")
    if clean_steps_to_restore <= 0:
        raise RuntimeError("CLEAN STEPS TO RESTORE는 1 이상이어야 합니다.")
    return {
        "automatic": automatic,
        "min_dt": min_dt,
        "reduction_factor": reduction_factor,
        "restoration_factor": restoration_factor,
        "max_reductions": max_reductions,
        "clean_steps_to_restore": clean_steps_to_restore,
        "algorithm_fallback": algorithm_fallback,
    }


def run_time_history_analysis(
    source: Path,
    *,
    directions: list[dict[str, Any]],
    model_length_unit: str = "m",
    analysis_time: dict[str, Any] | None = None,
    damping: dict[str, Any] | None = None,
    integrator: dict[str, Any] | None = None,
    solution: dict[str, Any] | None = None,
    recovery: dict[str, Any] | None = None,
    progress_callback: Callable[[int | None, str], None] | None = None,
) -> dict[str, Any]:
    """Build the model by executing ``source``, then run a transient analysis
    driven by one or more ``UniformExcitation`` ground-motion directions.

    ``directions`` is a list of ``{"dof", "path", "unit", "scaling_method",
    "scale_factor", "target_pga"}`` dicts - already-active rows from SETUP's
    Ground Motion table only (a disabled row is simply not included). Each
    direction gets its own ``ops.timeSeries("Path", ...)``/
    ``ops.pattern("UniformExcitation", ...)`` pair at a reserved, collision-
    free tag (see ``_TIME_SERIES_TAG_OFFSET``/``_PATTERN_TAG_OFFSET``), and
    keeps its own record dt - dt values are never resampled to match each
    other. A direction whose record ends before ``end_time`` reads 0 for the
    remainder (OpenSeesPy's own default Path TimeSeries behavior outside its
    defined domain - no ``-useLast``/``-prependZero`` flag is set).

    The main loop advances by real (pseudo-)time, not a fixed step count -
    ``ops.getTime()`` is the loop's own progress signal, so a step whose dt
    was shrunk by Adaptive Recovery cannot desynchronize the run from
    ``end_time``; the final step is clipped to land exactly on it.
    """
    _report_progress(progress_callback, 0, "Building the OpenSees model...")
    property_collector = ModelCommandCollector()
    property_collector.install()
    try:
        run_model_script(source)
    finally:
        property_collector.restore()

    node_tags = [int(tag) for tag in ops.getNodeTags()]
    if not node_tags:
        raise RuntimeError(
            "해석할 모델이 비어 있습니다. 스크립트 끝에서 ops.wipe()로 모델을 지우고 "
            "있지 않은지 확인하세요."
        )
    total_mass = sum(sum(abs(value) for value in ops.nodeMass(tag)) for tag in node_tags)
    if total_mass <= 0.0:
        raise RuntimeError(
            "절점 질량이 정의되어 있지 않습니다. 시간이력해석에는 ops.mass(...)로 "
            "정의된 질량이 필요합니다."
        )
    ndf = property_collector.ndf
    fixed_nodes = [int(tag) for tag in ops.getFixedNodes()]

    resolved_directions = _resolve_directions(
        directions, ndf=ndf, model_length_unit=model_length_unit
    )
    end_time, initial_dt, max_dt = _resolve_analysis_time(analysis_time, resolved_directions)
    resolved_recovery = _resolve_recovery(recovery, initial_dt=initial_dt, max_dt=max_dt)
    resolved_solution = _resolve_solution(solution)

    _report_progress(progress_callback, 3, "Setting up ground-motion patterns...")
    for direction in resolved_directions:
        ops.timeSeries(
            "Path",
            direction.ts_tag,
            "-dt",
            direction.dt,
            "-values",
            *direction.accelerations,
            "-factor",
            direction.total_factor,
        )
        ops.pattern("UniformExcitation", direction.pattern_tag, direction.dof, "-accel", direction.ts_tag)

    # First analysis-object build, needed only so ops.eigen() (for Modal
    # Targets damping) runs in a valid analysis context - mirrors the
    # previous single-ratio solver's own two-phase approach. Rebuilt cleanly
    # below once damping is known, before the real transient loop starts.
    _apply_analysis_objects(resolved_solution, integrator)
    damping_mode, alpha_m, beta_k, beta_k_init, beta_k_comm = _resolve_damping(damping)
    ops.rayleigh(alpha_m, beta_k, beta_k_init, beta_k_comm)
    integrator_type, integrator_params = _apply_analysis_objects(resolved_solution, integrator)

    _report_progress(progress_callback, 10, "Running the transient analysis...")
    current_time = 0.0
    current_dt = initial_dt
    clean_streak = 0
    time_history: list[dict[str, Any]] = []
    partial = False
    step_counter = 0
    while current_time < end_time - 1.0e-9:
        step_dt = min(current_dt, end_time - current_time)
        outcome = _advance_one_transient_step(
            step_dt,
            algorithm=resolved_solution["algorithm"],
            algorithm_fallback=resolved_recovery["algorithm_fallback"],
            automatic_recovery=resolved_recovery["automatic"],
            min_dt=resolved_recovery["min_dt"],
            reduction_factor=resolved_recovery["reduction_factor"],
            max_reductions=resolved_recovery["max_reductions"],
        )
        if outcome is None:
            partial = True
            break
        current_time = ops.getTime()
        ops.reactions()
        node_results = [
            {
                "node_tag": tag,
                "displacement": [float(value) for value in ops.nodeDisp(tag)],
                # Relative to the ground, not absolute/total - see
                # test_time_history_solver.py's own Duhamel-integral check.
                "velocity": [float(value) for value in ops.nodeVel(tag)],
                "acceleration": [float(value) for value in ops.nodeAccel(tag)],
                "reaction": (
                    [float(value) for value in ops.nodeReaction(tag)] if tag in fixed_nodes else []
                ),
            }
            for tag in node_tags
        ]
        time_history.append(
            {
                "time": current_time,
                "node_results": node_results,
                "actual_dt": outcome.actual_dt,
                "algorithm_used": outcome.algorithm_used,
                "recovered": outcome.recovered,
                "retry_count": outcome.retry_count,
                "dt_reduction_count": outcome.dt_reduction_count,
            }
        )
        if outcome.dt_reduction_count > 0:
            current_dt = outcome.actual_dt
            clean_streak = 0
        elif outcome.recovered:
            clean_streak = 0
        else:
            clean_streak += 1
            if resolved_recovery["automatic"] and clean_streak >= resolved_recovery["clean_steps_to_restore"]:
                current_dt = min(current_dt * resolved_recovery["restoration_factor"], max_dt)
                clean_streak = 0
        step_counter += 1
        if step_counter % 20 == 0 or current_time >= end_time - 1.0e-9:
            _report_progress(
                progress_callback,
                10 + round(90 * min(1.0, current_time / end_time)),
                f"t = {current_time:.4g}s / {end_time:.4g}s",
            )

    if not time_history:
        raise RuntimeError("첫 시간 스텝부터 수렴하지 않았습니다. ANALYSIS TIME STEP을 줄여보세요.")

    messages: list[str] = []
    if partial:
        messages.append(
            f"t = {current_time:.4g}s에서 더 이상 수렴하지 않아 그때까지의 결과만 표시합니다 "
            f"(목표 종료 시각 {end_time:.4g}s 중)."
        )

    settings = {
        "directions": [
            {
                "dof": direction.dof,
                "record_name": direction.record_name,
                "effective_scale": direction.effective_scale,
            }
            for direction in resolved_directions
        ],
        "integrator_type": integrator_type,
        "integrator_params": list(integrator_params),
        "damping_mode": damping_mode,
        "rayleigh_alpha_m": alpha_m,
        "rayleigh_beta_k": beta_k,
        "rayleigh_beta_k_init": beta_k_init,
        "rayleigh_beta_k_comm": beta_k_comm,
        "initial_dt": initial_dt,
        "minimum_dt": resolved_recovery["min_dt"],
        "maximum_dt": max_dt,
        "end_time": end_time,
        "status": "completed" if not partial else "partial",
    }

    return {
        "status": "completed" if not partial else "partial",
        "time_history": time_history,
        "settings": settings,
        "messages": messages,
    }
