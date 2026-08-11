"""Run a transient (time-history) analysis for an OpenSeesPy source.

Ground-motion acceleration is applied via ``UniformExcitation`` and integrated
with the standard average-acceleration Newmark method. Damping is Rayleigh
damping computed automatically from a single target damping ratio and the
model's own first one or two natural frequencies (``ops.eigen``) - a raw
alpha/beta pair is easy to get wrong and hard for a non-specialist to reason
about, so this solver only ever asks for the ratio real earthquake-engineering
references quote (e.g. "5%").
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.ground_motion import parse_ground_motion
from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script


def _report_progress(
    callback: Callable[[int | None, str], None] | None, value: int | None, stage: str
) -> None:
    if callback is not None:
        callback(value, stage)


def _rayleigh_coefficients(damping_ratio: float, angular_frequencies: list[float]) -> tuple[float, float]:
    """(alphaM, betaK) targeting ``damping_ratio`` at the given frequencies.

    Two frequencies (the usual case: first two natural modes) give the
    standard Rayleigh pair a0 = xi*2*w1*w2/(w1+w2), a1 = xi*2/(w1+w2). With
    only one valid frequency (a model too small/simple for a second mode to
    exist), falls back to mass-proportional-only damping (a1=0) targeting that
    one frequency exactly - still a real, exact damping ratio at that mode,
    just not "matched" at a second one that does not exist.
    """
    if not angular_frequencies:
        return 0.0, 0.0
    if len(angular_frequencies) == 1:
        return 2.0 * damping_ratio * angular_frequencies[0], 0.0
    w1, w2 = angular_frequencies[0], angular_frequencies[1]
    alpha_m = damping_ratio * 2.0 * w1 * w2 / (w1 + w2)
    beta_k = damping_ratio * 2.0 / (w1 + w2)
    return alpha_m, beta_k


def _natural_angular_frequencies(num_modes: int) -> list[float]:
    """Best-effort eigenvalues for Rayleigh damping - never raises: a model
    this solver could not find modes for (no mass, too few free dofs) simply
    gets zero damping instead of failing the whole time-history run over it,
    since a bad frequency estimate quietly producing the wrong damping ratio
    would be worse than an honest "no damping applied" fallback."""
    try:
        eigenvalues = ops.eigen(num_modes)
    except Exception:  # noqa: BLE001 - OpenSeesPy's own C++-backed exceptions.
        try:
            eigenvalues = ops.eigen("-fullGenLapack", num_modes)
        except Exception:  # noqa: BLE001
            return []
    return [float(value) ** 0.5 for value in eigenvalues if float(value) > 0.0]


def run_time_history_analysis(
    source: Path,
    *,
    ground_motion_path: Path,
    direction: int = 1,
    damping_ratio: float = 0.05,
    scale_factor: float = 1.0,
    dt_override: float | None = None,
    progress_callback: Callable[[int | None, str], None] | None = None,
) -> dict[str, Any]:
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
    if not 1 <= direction <= ndf:
        raise RuntimeError(f"DIRECTION {direction}이 모델의 자유도 범위(1~{ndf})를 벗어났습니다.")
    if damping_ratio < 0.0:
        raise RuntimeError("감쇠비는 0 이상이어야 합니다.")

    _report_progress(progress_callback, 5, "Reading the ground motion file...")
    try:
        motion_dt, accelerations = parse_ground_motion(ground_motion_path, dt=dt_override)
    except (ValueError, OSError) as error:
        raise RuntimeError(f"지진파 파일을 읽지 못했습니다: {error}") from error
    if not accelerations:
        raise RuntimeError("지진파 파일에 가속도 값이 없습니다.")

    fixed_nodes = [int(tag) for tag in ops.getFixedNodes()]

    ops.wipeAnalysis()
    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("BandGeneral")
    ops.test("NormDispIncr", 1.0e-8, 30)
    ops.algorithm("Newton")
    ops.integrator("Newmark", 0.5, 0.25)
    ops.analysis("Transient")

    if damping_ratio > 0.0:
        _report_progress(progress_callback, 10, "Computing Rayleigh damping from mode shapes...")
        angular_frequencies = _natural_angular_frequencies(2)
        alpha_m, beta_k = _rayleigh_coefficients(damping_ratio, angular_frequencies)
        ops.rayleigh(alpha_m, beta_k, 0.0, 0.0)
        # The eigen solve above changes nothing about the model itself, but
        # OpenSees' analysis objects are picky about being re-created cleanly
        # right before the real transient loop starts.
        ops.wipeAnalysis()
        ops.constraints("Transformation")
        ops.numberer("RCM")
        ops.system("BandGeneral")
        ops.test("NormDispIncr", 1.0e-8, 30)
        ops.algorithm("Newton")
        ops.integrator("Newmark", 0.5, 0.25)
        ops.analysis("Transient")
    else:
        angular_frequencies = []

    ground_motion_tag = 1
    pattern_tag = 1
    ops.timeSeries(
        "Path", ground_motion_tag, "-dt", motion_dt, "-values", *accelerations, "-factor", scale_factor
    )
    ops.pattern("UniformExcitation", pattern_tag, direction, "-accel", ground_motion_tag)

    num_steps = len(accelerations)
    time_history: list[dict[str, Any]] = []
    failed_step: int | None = None
    for step in range(1, num_steps + 1):
        if ops.analyze(1, motion_dt) != 0:
            failed_step = step
            break
        ops.reactions()
        node_results = [
            {
                "node_tag": tag,
                "displacement": [float(value) for value in ops.nodeDisp(tag)],
                "reaction": (
                    [float(value) for value in ops.nodeReaction(tag)] if tag in fixed_nodes else []
                ),
            }
            for tag in node_tags
        ]
        time_history.append({"time": ops.getTime(), "node_results": node_results})
        if step % 50 == 0 or step == num_steps:
            _report_progress(
                progress_callback,
                10 + round(90 * step / num_steps),
                f"Time step {step}/{num_steps}",
            )

    if not time_history:
        raise RuntimeError("첫 시간 스텝부터 수렴하지 않았습니다. 시간 간격을 줄여보세요.")

    messages: list[str] = []
    if failed_step is not None:
        messages.append(
            f"{failed_step}번째 시간 스텝에서 수렴하지 않아 그때까지의 결과만 표시합니다 "
            f"(총 {num_steps} 스텝 중 {len(time_history)} 스텝 완료)."
        )
    if damping_ratio > 0.0 and not angular_frequencies:
        messages.append(
            "고유진동수를 구하지 못해 감쇠 없이(alpha=beta=0) 해석했습니다 - 지점 조건과 "
            "질량을 확인하세요."
        )

    return {
        "status": "completed" if failed_step is None else "partial",
        "time_history": time_history,
        "damping": {
            "requested_ratio": damping_ratio,
            "angular_frequencies": angular_frequencies,
        },
        "messages": messages,
    }
