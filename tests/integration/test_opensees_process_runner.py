from pathlib import Path

import pytest

from openframe.core.domain import AnalysisRequest, AnalysisStatus
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "portal_frame_2d.py"


def test_runs_portal_frame_in_subprocess() -> None:
    runner = OpenSeesProcessRunner(timeout_seconds=15.0)
    request = AnalysisRequest(source_path=EXAMPLE_MODEL)

    result = runner.run(request)

    assert result.status == AnalysisStatus.COMPLETED
    assert len(result.node_results) == 4
    assert len(result.element_results) == 3

    total_rx = sum(node.reaction[0] for node in result.node_results.values())
    total_ry = sum(node.reaction[1] for node in result.node_results.values())
    assert total_rx == pytest.approx(-20.0, abs=1e-6)
    assert total_ry == pytest.approx(30.0, abs=1e-6)


def test_reports_failure_for_missing_source() -> None:
    runner = OpenSeesProcessRunner(timeout_seconds=15.0)
    request = AnalysisRequest(source_path=Path("does_not_exist.py"))

    result = runner.run(request)

    assert result.status == AnalysisStatus.FAILED
    assert result.messages
