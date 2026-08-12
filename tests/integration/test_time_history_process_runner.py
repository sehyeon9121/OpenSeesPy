"""End-to-end through the real worker subprocess: spawn -> JSON round-trip ->
domain TimeHistoryStep parsing - catches anything the in-process solver test
(test_time_history_solver.py) can't, like a CLI --kind dispatch mistake or a
JSON serialization bug in runner.py's TimeHistoryStep parsing."""

import math
from pathlib import Path

import pytest

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisStatus
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

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
ops.mass(2, 10.0)
ops.uniaxialMaterial('Elastic', 1, 1000.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
"""

_DT = 0.01
_NUM_POINTS = 200
_PULSE_AMPLITUDE = 1.0
_PULSE_DURATION = 1.0


def _half_sine_acceleration(time: float) -> float:
    if 0.0 <= time <= _PULSE_DURATION:
        return _PULSE_AMPLITUDE * math.sin(math.pi * time / _PULSE_DURATION)
    return 0.0


def _write_ground_motion(tmp_path: Path) -> Path:
    values = [_half_sine_acceleration(index * _DT) for index in range(_NUM_POINTS)]
    lines = [f"NPTS= {_NUM_POINTS}, DT= {_DT:.4f} SEC"]
    for start in range(0, _NUM_POINTS, 5):
        lines.append(" ".join(f"{value:.8f}" for value in values[start : start + 5]))
    path = tmp_path / "half_sine.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_runs_time_history_in_subprocess_and_populates_domain_time_history(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sdof.py"
    source.write_text(_SDOF_MODEL, encoding="utf-8")
    motion = _write_ground_motion(tmp_path)

    runner = OpenSeesProcessRunner(timeout_seconds=60.0)
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.TIME_HISTORY,
        options={
            "ground_motion_path": str(motion),
            "direction": 1,
            "damping_ratio": 0.0,
        },
    )

    result = runner.run(request)

    assert result.status == AnalysisStatus.COMPLETED
    assert len(result.time_history) == _NUM_POINTS
    first_step = result.time_history[0]
    assert first_step.time == pytest.approx(_DT, rel=1e-6)
    assert 2 in first_step.node_results
    assert 1 in first_step.node_results
    # Node 1 is fixed - it carries a reaction; node 2 is free - it doesn't.
    assert first_step.node_results[1].reaction != ()
    assert first_step.node_results[2].reaction == ()
    # Displacement grows in magnitude from a standing start.
    late_step = result.time_history[99]
    assert abs(late_step.node_results[2].displacement[0]) > 0.0
    # Phase 3-H: velocity/acceleration survive the worker subprocess's JSON
    # round-trip too, not just the in-process solver call.
    assert len(late_step.node_results[2].velocity) == 1
    assert len(late_step.node_results[2].acceleration) == 1


def test_reports_a_missing_ground_motion_file_as_a_failure(tmp_path: Path) -> None:
    source = tmp_path / "sdof.py"
    source.write_text(_SDOF_MODEL, encoding="utf-8")

    runner = OpenSeesProcessRunner(timeout_seconds=60.0)
    request = AnalysisRequest(
        source_path=source,
        kind=AnalysisKind.TIME_HISTORY,
        options={"ground_motion_path": str(tmp_path / "does_not_exist.txt"), "direction": 1},
    )

    result = runner.run(request)

    assert result.status == AnalysisStatus.FAILED
    assert any("지진파" in message for message in result.messages)
