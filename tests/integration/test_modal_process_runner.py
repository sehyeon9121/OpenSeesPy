import math
from pathlib import Path

import pytest

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisStatus
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

#: Same single-DOF spring-mass as test_modal_solver.py, but run through the real
#: worker subprocess end-to-end (spawn -> JSON payload -> domain ModeShape), to
#: catch anything the in-process solver test can't (JSON round-trip, CLI --kind
#: dispatch, runner._to_domain_result parsing).
_SPRING_MASS_MODEL = """
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


def test_runs_modal_analysis_in_subprocess_and_matches_hand_calculation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "spring_mass.py"
    source.write_text(_SPRING_MASS_MODEL, encoding="utf-8")
    runner = OpenSeesProcessRunner(timeout_seconds=15.0)
    request = AnalysisRequest(
        source_path=source, kind=AnalysisKind.MODAL, options={"num_modes": 1}
    )

    result = runner.run(request)

    assert result.status == AnalysisStatus.COMPLETED
    assert len(result.mode_shapes) == 1
    mode = result.mode_shapes[0]
    assert mode.mode_number == 1
    assert mode.angular_frequency == pytest.approx(10.0, rel=1e-6)
    assert mode.period == pytest.approx(2 * math.pi / 10.0, rel=1e-6)
    assert mode.node_results[2].displacement[0] == pytest.approx(
        1.0 / math.sqrt(10.0), rel=1e-6
    )
    assert mode.node_results[1].displacement[0] == pytest.approx(0.0, abs=1e-9)
    # Round-tripped through JSON by _to_domain_result - the field is easy to miss
    # when adding a new payload key there (it silently defaults to empty).
    assert mode.mass_participation_ratio == pytest.approx((1.0,), rel=1e-6)


def test_modal_analysis_reports_missing_mass_as_a_failure(tmp_path: Path) -> None:
    source = tmp_path / "no_mass.py"
    source.write_text(
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
    runner = OpenSeesProcessRunner(timeout_seconds=15.0)
    request = AnalysisRequest(
        source_path=source, kind=AnalysisKind.MODAL, options={"num_modes": 1}
    )

    result = runner.run(request)

    assert result.status == AnalysisStatus.FAILED
    assert any("절점 질량" in message for message in result.messages)
