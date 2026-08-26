import math
from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees.response_spectrum_solver import (
    run_response_spectrum_analysis,
)

#: Same golden-ratio 2-DOF shear building as test_modal_solver.py's own
#: benchmark model (k=1000, m=10 at both floors) - reusing its already-
#: independently-verified closed-form mode shapes/eigenvalues here lets this
#: test check the *new* SRSS/equivalent-static-force machinery in isolation,
#: without re-deriving the eigenproblem from scratch.
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


def test_flat_spectrum_matches_hand_derived_equivalent_static_srss(tmp_path: Path) -> None:
    """Flat spectrum (same Sa at every period) so the expected combined
    displacement/reaction can be hand-derived directly from the shear
    building's own closed-form mode shapes (golden ratio, phi and -1/phi)
    and K^{-1} = [[1/k, 1/k], [1/k, 2/k]] for K = [[2k, -k], [-k, k]] -
    independent of this solver's own code, so this is a real accuracy
    check rather than a self-consistency smoke test."""
    source = _write(tmp_path, "shear_building.py", _SHEAR_BUILDING_2DOF_MODEL)
    k = 1000.0
    m = 10.0
    sa0 = 0.5
    try:
        result = run_response_spectrum_analysis(
            source,
            periods=[0.01, 10.0],
            spectral_accelerations=[sa0, sa0],
            acceleration_unit="model",
            num_modes=2,
        )
    finally:
        ops.wipe()

    assert result["status"] == "completed"
    assert result["response_spectrum_settings"]["num_modes"] == 2
    assert result["response_spectrum_settings"]["directions"] == ["X"]

    golden_ratio = (1 + math.sqrt(5)) / 2
    mode_shapes = (1.0, golden_ratio), (1.0, -1.0 / golden_ratio)

    u2_squares = 0.0
    u3_squares = 0.0
    reaction_squares = 0.0
    for shape2, shape3 in mode_shapes:
        modal_mass = m * shape2 * shape2 + m * shape3 * shape3
        participation = m * shape2 + m * shape3
        gamma = participation / modal_mass
        force2 = gamma * m * shape2 * sa0
        force3 = gamma * m * shape3 * sa0
        u2 = (force2 + force3) / k
        u3 = (force2 + 2.0 * force3) / k
        reaction = -(force2 + force3)
        u2_squares += u2 * u2
        u3_squares += u3 * u3
        reaction_squares += reaction * reaction

    expected_u2 = math.sqrt(u2_squares)
    expected_u3 = math.sqrt(u3_squares)
    expected_reaction = math.sqrt(reaction_squares)

    node_results = {item["node_tag"]: item for item in result["node_results"]}
    assert node_results[2]["displacement"][0] == pytest.approx(expected_u2, rel=1e-6)
    assert node_results[3]["displacement"][0] == pytest.approx(expected_u3, rel=1e-6)
    assert node_results[1]["reaction"][0] == pytest.approx(expected_reaction, rel=1e-6)
    # SRSS destroys sign - every combined value is non-negative.
    assert all(value >= 0.0 for item in result["node_results"] for value in item["displacement"])
    assert all(value >= 0.0 for item in result["node_results"] for value in item["reaction"])


def test_rejects_a_model_with_no_mass(tmp_path: Path) -> None:
    source = _write(tmp_path, "no_mass.py", _NO_MASS_MODEL)
    try:
        with pytest.raises(RuntimeError, match="절점 질량"):
            run_response_spectrum_analysis(
                source, periods=[0.1, 1.0], spectral_accelerations=[0.5, 0.5]
            )
    finally:
        ops.wipe()


def test_rejects_a_spectrum_with_fewer_than_two_points(tmp_path: Path) -> None:
    source = _write(tmp_path, "shear_building.py", _SHEAR_BUILDING_2DOF_MODEL)
    try:
        with pytest.raises(RuntimeError, match="스펙트럼 표"):
            run_response_spectrum_analysis(source, periods=[0.5], spectral_accelerations=[0.5])
    finally:
        ops.wipe()


def test_rejects_duplicate_periods(tmp_path: Path) -> None:
    source = _write(tmp_path, "shear_building.py", _SHEAR_BUILDING_2DOF_MODEL)
    try:
        with pytest.raises(RuntimeError, match="중복"):
            run_response_spectrum_analysis(
                source, periods=[0.5, 0.5], spectral_accelerations=[0.5, 0.6]
            )
    finally:
        ops.wipe()
