import math
from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees.modal_solver import run_modal_analysis

#: Single-DOF spring-mass: node 1 fixed, node 2 free with mass m=10, spring k=1000.
#: Closed-form: omega = sqrt(k/m) = 10 rad/s, f = omega/2pi, T = 1/f.
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

#: Classic 2-DOF shear building, equal k and m at both floors: the two eigenvalues
#: have the closed-form golden-ratio solution (k/m)*(3 -+ sqrt(5))/2.
_SHEAR_BUILDING_2DOF_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.node(3, 2.0)
ops.fix(1, 1)
ops.mass(2, 10.0)
ops.mass(3, 10.0)
ops.uniaxialMaterial('Elastic', 1, 1000.0)
ops.uniaxialMaterial('Elastic', 2, 1000.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
ops.element('zeroLength', 2, 2, 3, '-mat', 2, '-dir', 1)
"""

_NO_MASS_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Elastic', 1, 1000.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
"""


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_single_dof_mode_matches_the_spring_mass_hand_calculation(tmp_path: Path) -> None:
    source = _write(tmp_path, "spring_mass.py", _SPRING_MASS_MODEL)
    try:
        result = run_modal_analysis(source, num_modes=1)
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    assert result["messages"] == []
    modes = result["mode_shapes"]
    assert len(modes) == 1
    mode = modes[0]
    assert mode["mode_number"] == 1
    assert mode["angular_frequency"] == pytest.approx(10.0, rel=1e-9)
    assert mode["frequency_hz"] == pytest.approx(10.0 / (2 * math.pi), rel=1e-9)
    assert mode["period"] == pytest.approx(2 * math.pi / 10.0, rel=1e-9)


def test_two_dof_shear_building_matches_the_golden_ratio_closed_form(tmp_path: Path) -> None:
    """A textbook result: for equal k and m at both floors, the two eigenvalues of
    K/m are (3 -+ sqrt(5))/2 times k/m - this is independent of this codebase and
    checkable by hand, so it is a real accuracy check, not just a smoke test."""
    source = _write(tmp_path, "shear_building.py", _SHEAR_BUILDING_2DOF_MODEL)
    try:
        result = run_modal_analysis(source, num_modes=2)
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    modes = result["mode_shapes"]
    assert len(modes) == 2
    k_over_m = 1000.0 / 10.0
    expected_low = k_over_m * (3 - math.sqrt(5)) / 2
    expected_high = k_over_m * (3 + math.sqrt(5)) / 2
    assert modes[0]["eigenvalue"] == pytest.approx(expected_low, rel=1e-6)
    assert modes[1]["eigenvalue"] == pytest.approx(expected_high, rel=1e-6)
    # Ascending order, and the fundamental mode is the softer/slower one.
    assert modes[0]["period"] > modes[1]["period"]

    # Mode 1 (in-phase, both floors move the same way) vs mode 2 (out-of-phase).
    mode1_by_node = {item["node_tag"]: item["displacement"][0] for item in modes[0]["node_results"]}
    mode2_by_node = {item["node_tag"]: item["displacement"][0] for item in modes[1]["node_results"]}
    assert mode1_by_node[2] * mode1_by_node[3] > 0
    assert mode2_by_node[2] * mode2_by_node[3] < 0
    # Node 1 is fixed - its eigenvector entry is always zero, in every mode.
    assert mode1_by_node[1] == pytest.approx(0.0, abs=1e-12)
    assert mode2_by_node[1] == pytest.approx(0.0, abs=1e-12)


def test_rejects_a_model_with_no_mass(tmp_path: Path) -> None:
    source = _write(tmp_path, "no_mass.py", _NO_MASS_MODEL)
    try:
        with pytest.raises(RuntimeError, match="절점 질량"):
            run_modal_analysis(source, num_modes=1)
    finally:
        ops.wipe()


def test_rejects_zero_or_negative_mode_count(tmp_path: Path) -> None:
    source = _write(tmp_path, "spring_mass.py", _SPRING_MASS_MODEL)
    try:
        with pytest.raises(RuntimeError, match="모드 수"):
            run_modal_analysis(source, num_modes=0)
    finally:
        ops.wipe()


def test_rejects_an_empty_model(tmp_path: Path) -> None:
    source = _write(tmp_path, "empty.py", "import openseespy.opensees as ops\nops.wipe()\n")
    try:
        with pytest.raises(RuntimeError, match="비어 있습니다"):
            run_modal_analysis(source, num_modes=1)
    finally:
        ops.wipe()
