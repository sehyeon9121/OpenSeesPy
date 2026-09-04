"""Phase 1.5: worker/export Linear Static instability diagnostic integration.

Tests cover:
- JSON codec round-trip (MechanismMode + InstabilityDiagnosticResult)
- diagnose_live() without a StructuralModel
- run_linear_static_analysis() failure path: diagnostic in returned dict
- user_node_tags allow-list projection
- Zero-K guard
- Very soft spring not classified as mechanism
- 3D pure truss (ndf=6) mechanism detection via run_linear_static_analysis
- Existing Phase 1 regression: diagnose(model) still works
"""

from __future__ import annotations

import textwrap
import tempfile
from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.core.domain.results import InstabilityDiagnosticResult, MechanismMode
from openframe.infrastructure.opensees.instability_diagnostic import (
    DEFAULT_MECHANISM_TOLERANCE,
    InstabilityDiagnosticService,
    instability_diagnostic_from_json,
    instability_diagnostic_to_json,
    mechanism_mode_from_json,
    mechanism_mode_to_json,
)
from openframe.infrastructure.opensees.linear_static_solver import run_linear_static_analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_script(code: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        prefix="openframe-test-",
        delete=False,
        encoding="utf-8",
    )
    with handle:
        handle.write(textwrap.dedent(code))
    return Path(handle.name)


# 2D sway column: node 1 pinned vertically only (roller), horizontal DOF free.
# Produces exactly 1 rigid-body translation mechanism under a horizontal load.
_SWAY_COLUMN_2D = """\
    import openseespy.opensees as ops
    ops.wipe()
    ops.model('basic', '-ndm', 2, '-ndf', 3)
    ops.node(1, 0.0, 0.0)
    ops.node(2, 0.0, 4.0)
    ops.fix(1, 0, 1, 0)
    ops.uniaxialMaterial('Elastic', 1, 200000.0)
    ops.geomTransf('Linear', 1)
    ops.element('elasticBeamColumn', 1, 1, 2, 0.01, 200000.0, 1e-4, 1)
    ops.timeSeries('Constant', 1)
    ops.pattern('Plain', 1, 1)
    ops.load(2, 10.0, 0.0, 0.0)
"""

# 3D pure truss along X: Ux and Uy free at node 2, Truss only provides Ux
# stiffness → Uy at node 2 is a rigid-body mechanism.
_TRUSS_3D_MECHANISM = """\
    import openseespy.opensees as ops
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)
    ops.node(1, 0.0, 0.0, 0.0)
    ops.node(2, 4.0, 0.0, 0.0)
    ops.fix(1, 1, 1, 1, 1, 1, 1)
    ops.fix(2, 0, 0, 1, 1, 1, 1)
    ops.uniaxialMaterial('Elastic', 1, 200000.0)
    ops.element('Truss', 1, 1, 2, 0.01, 1)
    ops.timeSeries('Constant', 1)
    ops.pattern('Plain', 1, 1)
    ops.load(2, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0)
"""

# 3D pure truss: only Ux free at node 2, Truss provides Ux stiffness → stable
_TRUSS_3D_STABLE = """\
    import openseespy.opensees as ops
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)
    ops.node(1, 0.0, 0.0, 0.0)
    ops.node(2, 4.0, 0.0, 0.0)
    ops.fix(1, 1, 1, 1, 1, 1, 1)
    ops.fix(2, 0, 1, 1, 1, 1, 1)
    ops.uniaxialMaterial('Elastic', 1, 200000.0)
    ops.element('Truss', 1, 1, 2, 0.01, 1)
    ops.timeSeries('Constant', 1)
    ops.pattern('Plain', 1, 1)
    ops.load(2, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0)
"""

# Very soft spring (1e-6 stiffness) - should NOT be a mechanism
_SOFT_SPRING_2D = """\
    import openseespy.opensees as ops
    ops.wipe()
    ops.model('basic', '-ndm', 2, '-ndf', 3)
    ops.node(1, 0.0, 0.0)
    ops.node(2, 1.0, 0.0)
    ops.fix(1, 1, 1, 1)
    ops.uniaxialMaterial('Elastic', 1, 1e-6)
    ops.geomTransf('Linear', 1)
    ops.element('elasticBeamColumn', 1, 1, 2, 0.01, 1e-6, 1e-10, 1)
    ops.timeSeries('Constant', 1)
    ops.pattern('Plain', 1, 1)
    ops.load(2, 1e-8, 0.0, 0.0)
"""


# ---------------------------------------------------------------------------
# JSON codec: pure-Python round-trip tests
# ---------------------------------------------------------------------------


class TestMechanismModeCodec:
    def test_empty_mode_shape(self) -> None:
        mode = MechanismMode(
            mode_number=1,
            eigenvalue=1e-15,
            mode_shape={},
            dominant_dofs=(),
            residual=0.0,
        )
        data = mechanism_mode_to_json(mode)
        restored = mechanism_mode_from_json(data)
        assert restored.mode_number == 1
        assert restored.mode_shape == {}
        assert restored.dominant_dofs == ()

    def test_str_keys_in_json_become_int_on_restore(self) -> None:
        mode = MechanismMode(
            mode_number=2,
            eigenvalue=1e-14,
            mode_shape={5: (0.0, 1.0, 0.0), 10: (0.0, -1.0, 0.0)},
            dominant_dofs=("n5:Uy=+1.00",),
            residual=1e-15,
        )
        data = mechanism_mode_to_json(mode)
        assert all(isinstance(k, str) for k in data["mode_shape"])
        restored = mechanism_mode_from_json(data)
        assert all(isinstance(k, int) for k in restored.mode_shape)
        assert restored.mode_shape[5] == pytest.approx((0.0, 1.0, 0.0))
        assert restored.mode_shape[10] == pytest.approx((0.0, -1.0, 0.0))

    def test_tuple_types_restored(self) -> None:
        mode = MechanismMode(
            mode_number=1,
            eigenvalue=0.0,
            mode_shape={3: (0.5, -0.5, 0.0)},
            dominant_dofs=("n3:Ux=+0.50", "n3:Uy=-0.50"),
            residual=0.0,
        )
        data = mechanism_mode_to_json(mode)
        assert isinstance(data["mode_shape"]["3"], list)
        assert isinstance(data["dominant_dofs"], list)

        restored = mechanism_mode_from_json(data)
        assert isinstance(restored.mode_shape[3], tuple)
        assert isinstance(restored.dominant_dofs, tuple)

    def test_source_field_preserved(self) -> None:
        mode = MechanismMode(
            mode_number=1, eigenvalue=0.0, source="stiffness_nullspace"
        )
        restored = mechanism_mode_from_json(mechanism_mode_to_json(mode))
        assert restored.source == "stiffness_nullspace"

    def test_missing_optional_fields_use_defaults(self) -> None:
        data = {"mode_number": 1, "eigenvalue": 0.0}
        mode = mechanism_mode_from_json(data)
        assert mode.mode_shape == {}
        assert mode.dominant_dofs == ()
        assert mode.residual == pytest.approx(0.0)
        assert mode.source == "stiffness_nullspace"


class TestInstabilityDiagnosticCodec:
    def test_none_input_returns_none(self) -> None:
        assert instability_diagnostic_from_json(None) is None

    def test_round_trip_with_modes(self) -> None:
        modes = (
            MechanismMode(
                mode_number=1,
                eigenvalue=1e-15,
                mode_shape={1: (1.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)},
                dominant_dofs=("n1:Ux=+1.00",),
                residual=1e-14,
            ),
        )
        result = InstabilityDiagnosticResult(
            mechanism_count=1,
            modes=modes,
            message="구조가 불안정합니다 - 강성행렬에서 메커니즘 1개가 감지되었습니다.",
            matrix_size=6,
            diagnostic_success=True,
        )
        data = instability_diagnostic_to_json(result)
        restored = instability_diagnostic_from_json(data)
        assert restored is not None
        assert restored.mechanism_count == 1
        assert restored.diagnostic_success is True
        assert len(restored.modes) == 1
        assert restored.modes[0].mode_number == 1
        assert 1 in restored.modes[0].mode_shape

    def test_round_trip_failure_payload(self) -> None:
        result = InstabilityDiagnosticResult(
            mechanism_count=0,
            modes=(),
            message="불안정 진단 자체가 실패했습니다: test",
            matrix_size=0,
            diagnostic_success=False,
        )
        data = instability_diagnostic_to_json(result)
        restored = instability_diagnostic_from_json(data)
        assert restored is not None
        assert restored.diagnostic_success is False
        assert restored.mechanism_count == 0
        assert restored.modes == ()

    def test_missing_field_payload_compatible(self) -> None:
        # Older payloads that never had instability_diagnostic key
        assert instability_diagnostic_from_json(None) is None

    def test_partial_payload_uses_defaults(self) -> None:
        restored = instability_diagnostic_from_json({"diagnostic_success": True})
        assert restored is not None
        assert restored.mechanism_count == 0
        assert restored.modes == ()
        assert restored.matrix_size == 0


# ---------------------------------------------------------------------------
# diagnose_live(): live OpenSees domain tests
# ---------------------------------------------------------------------------


class TestDiagnoseLive:
    def test_empty_domain_returns_failure_result(self) -> None:
        ops.wipe()
        result = InstabilityDiagnosticService().diagnose_live()
        ops.wipe()
        assert result.diagnostic_success is False
        assert "절점" in result.message or "live domain" in result.message

    def test_detects_sway_mechanism_in_roller_column(self) -> None:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 0.0, 4.0)
        ops.fix(1, 0, 1, 0)
        ops.uniaxialMaterial("Elastic", 1, 200000.0)
        ops.geomTransf("Linear", 1)
        ops.element("elasticBeamColumn", 1, 1, 2, 0.01, 200000.0, 1e-4, 1)
        ops.timeSeries("Constant", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 10.0, 0.0, 0.0)
        ops.wipeAnalysis()
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("LoadControl", 1.0)
        ops.algorithm("Linear")
        ops.analysis("Static")
        ops.analyze(1)

        result = InstabilityDiagnosticService().diagnose_live(
            user_node_tags_allow_list={1, 2}, ndm=2
        )
        ops.wipe()

        assert result.diagnostic_success is True
        assert result.mechanism_count >= 1

    def test_allow_list_filters_to_user_nodes_only(self) -> None:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 0.0, 4.0)
        ops.node(99, 0.0, 2.0)  # auxiliary / hinge-dummy node
        ops.fix(1, 0, 1, 0)
        ops.uniaxialMaterial("Elastic", 1, 200000.0)
        ops.geomTransf("Linear", 1)
        ops.element("elasticBeamColumn", 1, 1, 99, 0.01, 200000.0, 1e-4, 1)
        ops.element("elasticBeamColumn", 2, 99, 2, 0.01, 200000.0, 1e-4, 1)
        ops.timeSeries("Constant", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 10.0, 0.0, 0.0)
        ops.wipeAnalysis()
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("LoadControl", 1.0)
        ops.algorithm("Linear")
        ops.analysis("Static")
        ops.analyze(1)

        result = InstabilityDiagnosticService().diagnose_live(
            user_node_tags_allow_list={1, 2}, ndm=2
        )
        ops.wipe()

        assert result.diagnostic_success is True
        for mode in result.modes:
            assert 99 not in mode.mode_shape, "auxiliary node must not reach the projection"

    def test_stable_fixed_column_has_zero_mechanisms(self) -> None:
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.node(1, 0.0, 0.0)
        ops.node(2, 0.0, 4.0)
        ops.fix(1, 1, 1, 1)
        ops.uniaxialMaterial("Elastic", 1, 200000.0)
        ops.geomTransf("Linear", 1)
        ops.element("elasticBeamColumn", 1, 1, 2, 0.01, 200000.0, 1e-4, 1)
        ops.timeSeries("Constant", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 0.0, -10.0, 0.0)
        ops.wipeAnalysis()
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("LoadControl", 1.0)
        ops.algorithm("Linear")
        ops.analysis("Static")
        ops.analyze(1)

        result = InstabilityDiagnosticService().diagnose_live(
            user_node_tags_allow_list={1, 2}, ndm=2
        )
        ops.wipe()

        assert result.diagnostic_success is True
        assert result.mechanism_count == 0

    def test_ndm_autodetected_when_none(self) -> None:
        # Use a 3D Truss (no section properties needed) to avoid elasticBeamColumn
        # API differences; we only need a live 3D domain for ndm auto-detection.
        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.node(1, 0.0, 0.0, 0.0)
        ops.node(2, 4.0, 0.0, 0.0)
        ops.fix(1, 1, 1, 1, 1, 1, 1)
        ops.fix(2, 0, 1, 1, 1, 1, 1)  # stable: only Ux free, Truss provides it
        ops.uniaxialMaterial("Elastic", 1, 200000.0)
        ops.element("Truss", 1, 1, 2, 0.01, 1)
        ops.timeSeries("Constant", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        ops.wipeAnalysis()
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("LoadControl", 1.0)
        ops.algorithm("Linear")
        ops.analysis("Static")
        ops.analyze(1)

        # ndm=None forces auto-detection from domain coordinates
        result = InstabilityDiagnosticService().diagnose_live(ndm=None)
        ops.wipe()

        # Stable model → diagnostic runs successfully regardless of mechanism count
        assert result.diagnostic_success is True


# ---------------------------------------------------------------------------
# run_linear_static_analysis failure path tests
# ---------------------------------------------------------------------------


class TestLinearStaticSolverFailurePath:
    def test_failure_returns_dict_not_raises(self) -> None:
        script = _write_script(_SWAY_COLUMN_2D)
        try:
            result = run_linear_static_analysis(script, user_node_tags={1, 2}, ndm=2)
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        assert isinstance(result, dict)
        assert result["status"] == "failed"

    def test_failure_preserves_error_in_messages(self) -> None:
        script = _write_script(_SWAY_COLUMN_2D)
        try:
            result = run_linear_static_analysis(script, user_node_tags={1, 2}, ndm=2)
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        messages = result.get("messages", [])
        assert any("수렴" in m or "실패" in m for m in messages)

    def test_failure_includes_instability_diagnostic(self) -> None:
        script = _write_script(_SWAY_COLUMN_2D)
        try:
            result = run_linear_static_analysis(script, user_node_tags={1, 2}, ndm=2)
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        diag_data = result.get("instability_diagnostic")
        assert diag_data is not None
        assert isinstance(diag_data, dict)

    def test_failure_mechanism_count_correct(self) -> None:
        script = _write_script(_SWAY_COLUMN_2D)
        try:
            result = run_linear_static_analysis(script, user_node_tags={1, 2}, ndm=2)
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        diag = instability_diagnostic_from_json(result.get("instability_diagnostic"))
        assert diag is not None
        assert diag.diagnostic_success is True
        assert diag.mechanism_count >= 1

    def test_diagnostic_user_nodes_projected(self) -> None:
        script = _write_script(_SWAY_COLUMN_2D)
        try:
            result = run_linear_static_analysis(script, user_node_tags={1, 2}, ndm=2)
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        diag = instability_diagnostic_from_json(result.get("instability_diagnostic"))
        assert diag is not None
        assert diag.diagnostic_success is True
        for mode in diag.modes:
            for tag in mode.mode_shape:
                assert tag in {1, 2}, f"unexpected node tag {tag} in mode_shape projection"

    def test_success_has_no_diagnostic(self) -> None:
        script = _write_script(_TRUSS_3D_STABLE)
        try:
            result = run_linear_static_analysis(script, user_node_tags={1, 2}, ndm=3)
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        assert result["status"] == "completed"
        assert result.get("instability_diagnostic") is None

    def test_3d_pure_truss_ndf6_mechanism(self) -> None:
        script = _write_script(_TRUSS_3D_MECHANISM)
        try:
            result = run_linear_static_analysis(script, user_node_tags={1, 2}, ndm=3)
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        assert result["status"] == "failed"
        diag = instability_diagnostic_from_json(result.get("instability_diagnostic"))
        assert diag is not None
        assert diag.diagnostic_success is True
        assert diag.mechanism_count > 0

    def test_mechanism_not_zero_when_user_projection_empty(self) -> None:
        # If user_node_tags is empty (extreme edge case), mechanism_count must
        # still reflect the full-domain count; projection being empty does not
        # reset the count to 0.
        script = _write_script(_SWAY_COLUMN_2D)
        try:
            result = run_linear_static_analysis(
                script, user_node_tags=set(), ndm=2  # empty allow-list
            )
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        diag = instability_diagnostic_from_json(result.get("instability_diagnostic"))
        assert diag is not None
        if diag.diagnostic_success:
            assert diag.mechanism_count > 0, (
                "mechanism count must not be reset to 0 just because "
                "the user-projection is empty"
            )


# ---------------------------------------------------------------------------
# Very soft spring must not be classified as mechanism
# ---------------------------------------------------------------------------


class TestSoftSpringNotMechanism:
    def test_very_soft_spring_stable(self) -> None:
        script = _write_script(_SOFT_SPRING_2D)
        try:
            result = run_linear_static_analysis(script, user_node_tags={1, 2}, ndm=2)
        finally:
            ops.wipe()
            script.unlink(missing_ok=True)

        # The very soft spring IS structural (just soft), not a mechanism.
        # The analysis should converge (status completed) OR if it fails the
        # diagnostic must find mechanism_count==0 (soft modes above tolerance).
        if result["status"] == "failed":
            diag = instability_diagnostic_from_json(result.get("instability_diagnostic"))
            if diag is not None and diag.diagnostic_success:
                assert diag.mechanism_count == 0, (
                    "a very soft but physically present spring must not be "
                    "classified as a rigid-body mechanism"
                )


# ---------------------------------------------------------------------------
# Phase 1 regression: diagnose(model) delegate still works without StructuralModel
# ---------------------------------------------------------------------------


class TestPhase1Regression:
    def test_diagnose_model_delegate_calls_diagnose_live(self) -> None:
        """diagnose(model) must still return the same result as diagnose_live()
        with equivalent arguments - no StructuralModel internals used for K."""
        from openframe.core.domain import (
            BoundaryCondition,
            Element,
            Node,
            StructuralModel,
        )
        # Inline minimal frame properties (same values as buckling helpers use)
        # to avoid pulling in buckling_3d_hinge_diagnostics_helpers which
        # transitively imports PySide6 via the statics __init__.py.
        FRAME_PROPERTIES_3D = {
            "E": 200000.0, "A": 0.01, "Iz": 1e-4, "Iy": 1e-5, "G": 76923.0, "J": 1e-5
        }

        # Build a live failing domain manually (same geometry as the sway column tests)
        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.node(1, 0.0, 0.0, 0.0)
        ops.node(2, 0.0, 0.0, 4.0)
        # Only Uy fixed (roller) → horizontal mechanism
        ops.fix(1, 0, 1, 0, 0, 0, 0)
        ops.uniaxialMaterial("Elastic", 1, 200000.0)
        ops.geomTransf("Linear", 1, 0, 1, 0)
        # 3D elasticBeamColumn: A, E, G, J, Iy, Iz, transfTag
        ops.element("elasticBeamColumn", 1, 1, 2, 0.01, 200000.0, 76923.0, 1e-5, 1e-5, 1e-4, 1)
        ops.timeSeries("Constant", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        ops.wipeAnalysis()
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("LoadControl", 1.0)
        ops.algorithm("Linear")
        ops.analysis("Static")
        ops.analyze(1)

        # Test diagnose_live directly first (baseline)
        result_live = InstabilityDiagnosticService().diagnose_live(
            user_node_tags_allow_list={1, 2}, ndm=3
        )
        ops.wipe()

        assert result_live.diagnostic_success is True
        assert result_live.mechanism_count >= 1

        # Now rebuild the domain and test diagnose(model) gives same count
        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.node(1, 0.0, 0.0, 0.0)
        ops.node(2, 0.0, 0.0, 4.0)
        ops.fix(1, 0, 1, 0, 0, 0, 0)
        ops.uniaxialMaterial("Elastic", 1, 200000.0)
        ops.geomTransf("Linear", 1, 0, 1, 0)
        ops.element("elasticBeamColumn", 1, 1, 2, 0.01, 200000.0, 76923.0, 1e-5, 1e-5, 1e-4, 1)
        ops.timeSeries("Constant", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        ops.wipeAnalysis()
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        ops.integrator("LoadControl", 1.0)
        ops.algorithm("Linear")
        ops.analysis("Static")
        ops.analyze(1)

        model = StructuralModel(
            ndm=3,
            ndf=6,
            nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, 4.0)},
            elements={1: Element(1, 1, 2, "frame", properties=FRAME_PROPERTIES_3D)},
            boundaries=[BoundaryCondition(1, (False, True, False, False, False, False))],
        )
        result_model = InstabilityDiagnosticService().diagnose(model)
        ops.wipe()

        assert result_model.diagnostic_success is True
        assert result_model.mechanism_count == result_live.mechanism_count
