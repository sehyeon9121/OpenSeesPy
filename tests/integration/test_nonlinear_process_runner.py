from pathlib import Path

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisStatus
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

_PERFECTLY_PLASTIC_SPRING = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 0.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Steel01', 1, 100.0, 1000.0, 0.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 300.0)
"""


def test_process_runner_preserves_partial_convergence_and_diagnostics(tmp_path: Path) -> None:
    source = tmp_path / "perfectly_plastic_spring.py"
    source.write_text(_PERFECTLY_PLASTIC_SPRING, encoding="utf-8")
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.NONLINEAR_STATIC,
        options={
            "control_node": 2,
            "num_steps": 10,
            "max_iterations": 10,
            # This is a runner setting and must not leak into the solver kwargs.
            "execution_timeout_seconds": 20,
        },
    )

    progress: list[tuple[int | None, str]] = []
    result = OpenSeesProcessRunner(nonlinear_timeout_seconds=30).run(
        request,
        progress_callback=lambda value, stage: progress.append((value, stage)),
    )

    assert result.status == AnalysisStatus.PARTIAL
    assert result.convergence is not None
    assert result.convergence.requested_steps == 10
    assert result.convergence.completed_steps == 3
    assert result.convergence.failed_step == 4
    assert result.convergence.total_attempts > 3
    assert len(result.load_displacement_curve) == 3
    assert all(point.attempts >= 1 for point in result.load_displacement_curve)
    assert progress
    assert any("Pushover" in stage for _value, stage in progress)


def test_process_runner_can_cancel_the_worker(tmp_path: Path) -> None:
    source = tmp_path / "cancelled_spring.py"
    source.write_text(_PERFECTLY_PLASTIC_SPRING, encoding="utf-8")
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.NONLINEAR_STATIC,
        options={"control_node": 2, "num_steps": 1000},
    )

    result = OpenSeesProcessRunner(nonlinear_timeout_seconds=30).run(
        request,
        cancellation_requested=lambda: True,
    )

    assert result.status == AnalysisStatus.CANCELLED
    assert result.messages
