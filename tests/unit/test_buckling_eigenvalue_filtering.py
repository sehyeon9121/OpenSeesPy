"""Unit coverage for buckling_solver.py's eigenvalue filtering rules.

A real model rarely produces a clean, deliberate mix of complex/negative/
infinite eigenvalues on demand, so scipy.linalg.eig itself is mocked here
(matching test_nonlinear_static_solver_retry.py's own philosophy: script the
part that is hard to construct deterministically, keep the surrounding real
OpenSees model so K_material/K_geometric extraction and the mode-shape
mapping are still exercised for real) - this isolates exactly the filtering
rules from buckling_solver.py's docstring: finite only, effectively-real
within tolerance, strictly positive, ascending sort, truncated to the
requested mode count.
"""

from pathlib import Path
from unittest.mock import patch

import numpy as np
import openseespy.opensees as ops
import pytest
import scipy.linalg

from openframe.infrastructure.opensees import buckling_solver as bs
from openframe.infrastructure.opensees.buckling_solver import run_buckling_analysis

_E = 200_000.0
_I = 8_333.33
_A = 10_000.0
_L = 3_000.0


def _write_euler_column(tmp_path: Path, n_elements: int) -> Path:
    lines = [
        "import openseespy.opensees as ops",
        "ops.wipe()",
        "ops.model('basic', '-ndm', 2, '-ndf', 3)",
    ]
    for i in range(n_elements + 1):
        y = _L * i / n_elements
        lines.append(f"ops.node({i + 1}, 0.0, {y})")
    lines.append("ops.fix(1, 1, 1, 0)")
    lines.append(f"ops.fix({n_elements + 1}, 1, 0, 0)")
    lines.append("ops.geomTransf('PDelta', 1)")
    for i in range(n_elements):
        lines.append(
            f"ops.element('elasticBeamColumn', {i + 1}, {i + 1}, {i + 2}, {_A}, {_E}, {_I}, 1)"
        )
    lines.append("ops.timeSeries('Linear', 1)")
    lines.append("ops.pattern('Plain', 1, 1)")
    lines.append(f"ops.load({n_elements + 1}, 0.0, -1.0, 0.0)")
    source = tmp_path / "euler_column.py"
    source.write_text("\n".join(lines), encoding="utf-8")
    return source


def test_eigenvalue_filtering_rules_and_partial_status(tmp_path: Path) -> None:
    # 3 elements -> 4 nodes -> 12 total DOFs, minus 3 restrained (node 1:
    # Ux,Uy; node 4: Ux) = 9 free DOFs, so K_material/K_geometric are 9x9 and
    # scipy.linalg.eig must be handed back exactly 9 eigenvalues/eigenvectors.
    source = _write_euler_column(tmp_path, 3)

    # Deliberately covers every filtering category the docstring promises:
    # negative, complex (beyond and within tolerance), infinite, and valid
    # positive-real values in non-sorted order.
    fake_eigenvalues = np.array(
        [
            -5.0 + 0.0j,  # filtered: non-positive
            3.0 + 3.0j,  # filtered: complex (well beyond tolerance)
            np.inf + 0.0j,  # filtered: infinite
            2.0 + 1.0e-10j,  # accepted as real 2.0 (imag within AUTO tolerance)
            20.0 + 0.0j,  # accepted
            -1.0 + 0.0j,  # filtered: non-positive
            1.0 + 0.5j,  # filtered: complex
            np.inf + 0.0j,  # filtered: infinite
            8.0 + 0.0j,  # accepted
        ]
    )
    fake_eigenvectors = np.eye(9, dtype=complex)

    def fake_eig(k_material: np.ndarray, k_geometric: np.ndarray):
        assert k_material.shape == (9, 9)
        assert k_geometric.shape == (9, 9)
        return fake_eigenvalues, fake_eigenvectors

    try:
        with patch.object(scipy.linalg, "eig", side_effect=fake_eig):
            result = run_buckling_analysis(source, num_modes=5)
    finally:
        ops.wipe()

    factors = [mode["buckling_load_factor"] for mode in result["buckling_modes"]]
    assert factors == [2.0, 8.0, 20.0]  # ascending, only the 3 valid ones

    # Requested 5, only 3 valid -> partial, with the shortfall reported.
    assert result["status"] == "partial"
    assert any("요청한 5개" in message and "3개" in message for message in result["messages"])

    # Filtered counts (2 infinite, 2 complex, 2 non-positive) surfaced as
    # diagnostics, not silently dropped.
    diagnostic_message = next(
        message for message in result["messages"] if "무한" in message
    )
    assert "무한/미해결 2개" in diagnostic_message
    assert "복소 2개" in diagnostic_message
    assert "0 이하 2개" in diagnostic_message


def test_large_system_size_adds_a_dense_matrix_performance_warning(tmp_path: Path) -> None:
    """Closing check: Dense FullGeneral + SciPy's O(n**3) dense generalized
    eigensolve deserve a warning on a large model - the threshold itself is
    patched down to a value this small fixture already exceeds instead of
    building a genuinely large model, since only the threshold-crossing
    behavior is under test here (real-model accuracy is covered elsewhere)."""
    source = _write_euler_column(tmp_path, 3)  # system_size == 9 (see the other test)
    try:
        with patch.object(bs, "_LARGE_SYSTEM_DOF_WARNING_THRESHOLD", 5):
            result = run_buckling_analysis(source, num_modes=1)
    finally:
        ops.wipe()

    assert any(
        "자유도 수가 9개" in message and "5개" in message for message in result["messages"]
    )


def test_small_system_size_does_not_add_the_performance_warning(tmp_path: Path) -> None:
    source = _write_euler_column(tmp_path, 3)
    try:
        result = run_buckling_analysis(source, num_modes=1)
    finally:
        ops.wipe()

    assert not any("Dense" in message or "밀집" in message for message in result["messages"])


def test_no_valid_eigenvalues_raises_a_clear_error(tmp_path: Path) -> None:
    source = _write_euler_column(tmp_path, 3)
    fake_eigenvalues = np.array([-1.0, -2.0, np.inf, 1.0 + 2.0j] + [-3.0] * 5)
    fake_eigenvectors = np.eye(9, dtype=complex)

    def fake_eig(k_material: np.ndarray, k_geometric: np.ndarray):
        return fake_eigenvalues, fake_eigenvectors

    try:
        with (
            patch.object(scipy.linalg, "eig", side_effect=fake_eig),
            pytest.raises(RuntimeError, match="유효한 양의 실수 좌굴하중계수"),
        ):
            run_buckling_analysis(source, num_modes=3)
    finally:
        ops.wipe()
