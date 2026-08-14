"""Integration coverage for elastic eigenvalue buckling analysis
(buckling_solver.py), against a real OpenSeesPy process.

The centerpiece is a pinned-pinned Euler column convergence study: the one
closed-form problem this project can check a linearized elastic buckling
solve against (Pcr = pi**2 * E * I / L**2). Convergence is checked across
several element counts - a single-element result is never taken as proof by
itself, since a coarse mesh could accidentally land close to the exact answer.
"""

import math
from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.core.domain import AnalysisKind, AnalysisRequest
from openframe.infrastructure.opensees.buckling_solver import run_buckling_analysis
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

_E = 200_000.0
_I = 8_333.33
_A = 10_000.0
_L = 3_000.0
_EULER_PCR = math.pi**2 * _E * _I / _L**2


def _write_euler_column(tmp_path: Path, n_elements: int, *, name: str = "euler_column.py") -> Path:
    """Pinned-pinned column along Y: bottom node fully pinned (Ux=Uy=0, Rz
    free), top node laterally pinned only (Ux=0, Uy free so the reference
    axial load can be applied and the column can shorten). corotTruss is not
    used here - elasticBeamColumn + PDelta is what develops the geometric
    stiffness a real building-frame model would (bending members), not just
    a two-bar truss case."""
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
    source = tmp_path / name
    source.write_text("\n".join(lines), encoding="utf-8")
    return source


def test_euler_column_buckling_factor_converges_to_the_closed_form(tmp_path: Path) -> None:
    """Relative error must shrink as the mesh refines, and land within 0.5% by
    32 elements - checked across four element counts, not just one, so a
    lucky coarse-mesh coincidence can never be mistaken for real convergence."""
    element_counts = (4, 8, 16, 32)
    relative_errors = []
    for n_elements in element_counts:
        source = _write_euler_column(tmp_path, n_elements, name=f"euler_{n_elements}.py")
        try:
            result = run_buckling_analysis(source, num_modes=1, geometric_transform_type="PDelta")
        finally:
            ops.wipe()
        assert result["status"] == "completed"
        pcr_fe = result["buckling_modes"][0]["buckling_load_factor"]
        relative_errors.append(abs(pcr_fe - _EULER_PCR) / _EULER_PCR)

    # Monotonically improving as the mesh refines (allow equality at the tight
    # end, where floating-point/discretization noise can dominate).
    for coarser, finer in zip(relative_errors, relative_errors[1:]):
        assert finer <= coarser * 1.01
    assert relative_errors[-1] < 0.005  # < 0.5% at 32 elements


def test_reference_load_scale_invariance(tmp_path: Path) -> None:
    """Doubling REFERENCE LOAD SCALE halves the buckling load factor and
    leaves Critical Load (factor * reference load) unchanged - the physical
    quantity, not the arbitrary bookkeeping factor, must be scale-independent."""
    source = _write_euler_column(tmp_path, 20)
    try:
        result_1x = run_buckling_analysis(source, reference_load_scale=1.0, num_modes=1)
    finally:
        ops.wipe()
    try:
        result_2x = run_buckling_analysis(source, reference_load_scale=2.0, num_modes=1)
    finally:
        ops.wipe()

    factor_1x = result_1x["buckling_modes"][0]["buckling_load_factor"]
    factor_2x = result_2x["buckling_modes"][0]["buckling_load_factor"]
    assert factor_2x / factor_1x == pytest.approx(0.5, rel=1.0e-6)
    critical_load_1x = factor_1x * 1.0
    critical_load_2x = factor_2x * 2.0
    assert critical_load_2x == pytest.approx(critical_load_1x, rel=1.0e-6)


def test_first_and_second_mode_shapes_and_eigenvalue_ratio(tmp_path: Path) -> None:
    """The classic pinned-pinned Euler column result: mode 2's buckling factor
    is ~4x mode 1's, and mode 2's shape has a node (zero crossing) exactly at
    mid-height, unlike mode 1's single-lobe shape there."""
    n_elements = 20
    source = _write_euler_column(tmp_path, n_elements)
    try:
        result = run_buckling_analysis(source, num_modes=2)
    finally:
        ops.wipe()

    modes = result["buckling_modes"]
    assert len(modes) == 2
    ratio = modes[1]["buckling_load_factor"] / modes[0]["buckling_load_factor"]
    assert ratio == pytest.approx(4.0, rel=0.01)

    mid_node_tag = n_elements // 2 + 1
    mode1_shape = {item["node_tag"]: item["displacement"] for item in modes[0]["node_results"]}
    mode2_shape = {item["node_tag"]: item["displacement"] for item in modes[1]["node_results"]}
    mode1_mid_ux = mode1_shape[mid_node_tag][0]
    mode2_mid_ux = mode2_shape[mid_node_tag][0]
    assert abs(mode1_mid_ux) > 1.0e-6  # mode 1 has its single lobe's peak here
    assert abs(mode2_mid_ux) < 1.0e-6 * abs(mode1_mid_ux)  # mode 2's node is here


def test_restrained_dof_is_reported_as_zero_in_the_mode_shape(tmp_path: Path) -> None:
    source = _write_euler_column(tmp_path, 8)
    try:
        result = run_buckling_analysis(source, num_modes=1)
    finally:
        ops.wipe()

    mode = result["buckling_modes"][0]
    shapes = {item["node_tag"]: item["displacement"] for item in mode["node_results"]}
    # Node 1 (bottom): Ux, Uy restrained - both DOFs must read exactly 0.0.
    assert shapes[1][0] == 0.0
    assert shapes[1][1] == 0.0
    # Node 9 (top): Ux restrained only.
    assert shapes[9][0] == 0.0


def test_normalized_mode_shape_has_unit_max_translational_component(tmp_path: Path) -> None:
    source = _write_euler_column(tmp_path, 8)
    try:
        result = run_buckling_analysis(source, num_modes=1)
    finally:
        ops.wipe()
    normalized = {
        item["node_tag"]: item["displacement"]
        for item in result["buckling_modes"][0]["normalized_node_results"]
    }
    max_translational = max(abs(components[0]) for components in normalized.values())
    assert max_translational == pytest.approx(1.0)


def test_no_reference_load_pattern_blocks_the_run(tmp_path: Path) -> None:
    source = tmp_path / "no_load.py"
    source.write_text(
        "\n".join(
            [
                "import openseespy.opensees as ops",
                "ops.wipe()",
                "ops.model('basic', '-ndm', 2, '-ndf', 3)",
                "ops.node(1, 0.0, 0.0)",
                "ops.node(2, 0.0, 100.0)",
                "ops.fix(1, 1, 1, 1)",
                "ops.geomTransf('PDelta', 1)",
                f"ops.element('elasticBeamColumn', 1, 1, 2, {_A}, {_E}, {_I}, 1)",
            ]
        ),
        encoding="utf-8",
    )
    try:
        with pytest.raises(RuntimeError, match="REFERENCE LOAD"):
            run_buckling_analysis(source)
    finally:
        ops.wipe()


def test_linear_geometric_transform_is_rejected(tmp_path: Path) -> None:
    source = _write_euler_column(tmp_path, 4)
    try:
        with pytest.raises(RuntimeError, match="Linear"):
            run_buckling_analysis(source, geometric_transform_type="Linear")
    finally:
        ops.wipe()


def test_k_geometric_effectively_zero_fails_cleanly(tmp_path: Path) -> None:
    """A reference load that induces no axial force anywhere develops no
    geometric stiffness at all even with P-Delta active (Kg is a function of
    axial force alone) - a horizontal cantilever loaded transversely at its
    tip is exactly that case (equilibrium gives zero horizontal reaction, so
    zero axial force in the member). The run must fail with a clear reason,
    not silently report a meaningless (or infinite/NaN) factor."""
    source = tmp_path / "zero_axial_force.py"
    source.write_text(
        "\n".join(
            [
                "import openseespy.opensees as ops",
                "ops.wipe()",
                "ops.model('basic', '-ndm', 2, '-ndf', 3)",
                "ops.node(1, 0.0, 0.0)",
                "ops.node(2, 100.0, 0.0)",
                "ops.fix(1, 1, 1, 1)",
                "ops.geomTransf('PDelta', 1)",
                f"ops.element('elasticBeamColumn', 1, 1, 2, {_A}, {_E}, {_I}, 1)",
                "ops.timeSeries('Linear', 1)",
                "ops.pattern('Plain', 1, 1)",
                "ops.load(2, 0.0, -1.0, 0.0)",
            ]
        ),
        encoding="utf-8",
    )
    try:
        with pytest.raises(RuntimeError, match="기하강성"):
            run_buckling_analysis(source, geometric_transform_type="PDelta")
    finally:
        ops.wipe()


def test_corotational_and_from_model_are_not_yet_offered(tmp_path: Path) -> None:
    """Closing check: officially restricted to P-Delta only for now - these
    are real, recognized transform types (unlike a genuinely unknown string),
    so they get their own clear "not yet supported" message rather than a
    generic "unsupported setting" one."""
    source = _write_euler_column(tmp_path, 4)
    for transform in ("Corotational", "UseModelDefinition"):
        try:
            with pytest.raises(RuntimeError, match="P-Delta"):
                run_buckling_analysis(source, geometric_transform_type=transform)
        finally:
            ops.wipe()


def test_fewer_valid_modes_than_requested_reports_partial_status(tmp_path: Path) -> None:
    """K_geometric is generally much lower-rank than K_material, so many
    solved eigenvalues are infinite (filtered) rather than real buckling
    factors - asking for more modes than exist as valid, finite/real/positive
    values must report a partial result with a clear count, not fabricate
    extra ones."""
    source = _write_euler_column(tmp_path, 6)
    try:
        result = run_buckling_analysis(source, num_modes=100)
    finally:
        ops.wipe()
    assert result["status"] == "partial"
    assert len(result["buckling_modes"]) < 100
    assert any("요청한" in message for message in result["messages"])


def test_equal_dof_constrained_node_mode_shape_matches_its_master(tmp_path: Path) -> None:
    """Regression for a real bug found while closing this feature out:
    ops.nodeDOFs() reports a real (non-negative) equation number for an
    equalDOF-constrained DOF under the Transformation constraint handler, but
    indexing the externally-solved buckling eigenvector at that equation does
    not give the constrained node's own physical value - it silently came
    back exactly 0.0 for every constrained DOF before the fix. Two parallel
    pinned-pinned columns, tied node-by-node via equalDOF(Ux), must show
    identical Ux in every accepted mode."""
    n_elements = 8
    lines = [
        "import openseespy.opensees as ops",
        "ops.wipe()",
        "ops.model('basic', '-ndm', 2, '-ndf', 3)",
    ]
    for i in range(n_elements + 1):
        y = _L * i / n_elements
        lines.append(f"ops.node({i + 1}, 0.0, {y})")
        lines.append(f"ops.node({101 + i}, 500.0, {y})")
    lines.append("ops.fix(1, 1, 1, 0)")
    lines.append(f"ops.fix({n_elements + 1}, 1, 0, 0)")
    lines.append("ops.fix(101, 1, 1, 0)")
    lines.append(f"ops.fix({101 + n_elements}, 1, 0, 0)")
    lines.append("ops.geomTransf('PDelta', 1)")
    for i in range(n_elements):
        lines.append(
            f"ops.element('elasticBeamColumn', {i + 1}, {i + 1}, {i + 2}, {_A}, {_E}, {_I}, 1)"
        )
        lines.append(
            f"ops.element('elasticBeamColumn', {101 + i}, {101 + i}, {102 + i}, {_A}, {_E}, {_I}, 1)"
        )
    for i in range(1, n_elements):
        lines.append(f"ops.equalDOF({i + 1}, {101 + i}, 1)")
    lines.append("ops.timeSeries('Linear', 1)")
    lines.append("ops.pattern('Plain', 1, 1)")
    lines.append(f"ops.load({n_elements + 1}, 0.0, -1.0, 0.0)")
    lines.append(f"ops.load({101 + n_elements}, 0.0, -1.0, 0.0)")
    source = tmp_path / "equaldof_columns.py"
    source.write_text("\n".join(lines), encoding="utf-8")

    try:
        result = run_buckling_analysis(source, num_modes=2)
    finally:
        ops.wipe()

    assert any("equalDOF" in message for message in result["messages"])
    for mode in result["buckling_modes"]:
        shapes = {item["node_tag"]: item["displacement"] for item in mode["node_results"]}
        for i in range(1, n_elements):
            assert shapes[i + 1][0] == pytest.approx(shapes[101 + i][0], abs=1.0e-9)


def test_rigid_diaphragm_constrained_node_mode_shape_matches_rigid_body_kinematics(
    tmp_path: Path,
) -> None:
    """Same regression as the equalDOF test above, for rigidDiaphragm - the
    verified relation is u_c = u_r + omega x (r_c - r_r) (checked against a
    real OpenSeesPy static solve for all three perpDirn values before being
    trusted in the solver; here it is checked end to end against a real
    buckling solve instead of an isolated formula)."""
    e, i_section, a, h = 200_000.0, 8_333.33, 10_000.0, 3_000.0
    corners = {1: (0.0, 0.0), 2: (500.0, 0.0), 3: (500.0, 500.0), 4: (0.0, 500.0)}
    centroid_x, centroid_y = 250.0, 250.0
    lines = [
        "import openseespy.opensees as ops",
        "ops.wipe()",
        "ops.model('basic', '-ndm', 3, '-ndf', 6)",
    ]
    for tag, (x, y) in corners.items():
        lines.append(f"ops.node({tag}, {x}, {y}, 0.0)")
        lines.append(f"ops.node({tag + 10}, {x}, {y}, {h})")
        lines.append(f"ops.fix({tag}, 1, 1, 1, 1, 1, 1)")
    lines.append(f"ops.node(100, {centroid_x}, {centroid_y}, {h})")
    lines.append("ops.fix(100, 1, 1, 1, 1, 1, 0)")  # a pure-torsion diaphragm mode
    lines.append("ops.rigidDiaphragm(3, 100, 11, 12, 13, 14)")
    lines.append("ops.geomTransf('PDelta', 1, 1.0, 0.0, 0.0)")
    for tag in corners:
        lines.append(
            f"ops.element('elasticBeamColumn', {tag}, {tag}, {tag + 10}, {a}, {e}, "
            f"{e / 2.6}, {i_section}, {i_section}, {2 * i_section}, 1)"
        )
    lines.append("ops.timeSeries('Linear', 1)")
    lines.append("ops.pattern('Plain', 1, 1)")
    for tag in corners:
        lines.append(f"ops.load({tag + 10}, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0)")
    source = tmp_path / "rigid_diaphragm_frame.py"
    source.write_text("\n".join(lines), encoding="utf-8")

    try:
        result = run_buckling_analysis(source, num_modes=1)
    finally:
        ops.wipe()

    assert any("rigidDiaphragm" in message for message in result["messages"])
    shapes = {
        item["node_tag"]: item["displacement"]
        for item in result["buckling_modes"][0]["node_results"]
    }
    master_ux, master_uy, master_rz = shapes[100][0], shapes[100][1], shapes[100][5]
    for tag, (x, y) in corners.items():
        top = shapes[tag + 10]
        dx, dy = x - centroid_x, y - centroid_y
        assert top[0] == pytest.approx(master_ux - dy * master_rz, abs=1.0e-9)
        assert top[1] == pytest.approx(master_uy + dx * master_rz, abs=1.0e-9)


def test_buckling_result_never_populates_the_modal_fields(tmp_path: Path) -> None:
    """End-to-end (real worker subprocess + JSON round trip): a buckling run's
    AnalysisResult.mode_shapes must stay empty - the two analyses are wired
    through completely separate result fields (see runner.py's
    _to_domain_result), so nothing downstream (Results UI) could ever
    mistake one for the other."""
    source = _write_euler_column(tmp_path, 4)
    request = AnalysisRequest(
        source_path=source, kind=AnalysisKind.BUCKLING, options={"num_modes": 2}
    )
    result = OpenSeesProcessRunner().run(request)

    assert result.mode_shapes == ()
    assert len(result.buckling_modes) == 2
    assert result.buckling_modes[0].mode_number == 1


def test_scope_disclaimer_is_always_present(tmp_path: Path) -> None:
    source = _write_euler_column(tmp_path, 4)
    try:
        result = run_buckling_analysis(source, num_modes=1)
    finally:
        ops.wipe()
    assert any(
        "Material yielding" in message and "not included" in message
        for message in result["messages"]
    )
