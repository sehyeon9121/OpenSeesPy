"""``MaterialFreeStaticsSolver.solve()`` wiring to ``InstabilityDiagnosticService``
(Phase 1: linear static only - see solver.py's ``_LinearStaticConvergenceFailure``
and its ``except`` branch).
"""

from __future__ import annotations

import openseespy.opensees as ops
import pytest

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    Node,
    StructuralModel,
)
from openframe.core.domain.results import InstabilityDiagnosticResult
from openframe.features.analysis.statics import solver as solver_module
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver
from openframe.infrastructure.opensees.instability_diagnostic import InstabilityDiagnosticService
from tests.integration.buckling_3d_hinge_diagnostics_helpers import (
    FRAME_PROPERTIES_3D,
    vertical_cantilever,
)


def _single_sway_column() -> StructuralModel:
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, 4.0)},
        elements={1: Element(1, 1, 2, "frame", properties=FRAME_PROPERTIES_3D)},
        boundaries=[BoundaryCondition(1, (False, True, True, True, True, True))],
    )


def test_successful_solve_leaves_instability_diagnostic_none() -> None:
    result = MaterialFreeStaticsSolver().solve(vertical_cantilever())
    ops.wipe()
    assert result.status == AnalysisStatus.COMPLETED
    assert result.instability_diagnostic is None


def test_failed_convergence_runs_diagnostic_against_the_live_domain() -> None:
    result = MaterialFreeStaticsSolver().solve(_single_sway_column())
    ops.wipe()
    assert result.status == AnalysisStatus.FAILED
    diagnostic = result.instability_diagnostic
    assert diagnostic is not None
    assert diagnostic.diagnostic_success is True
    assert diagnostic.mechanism_count == 1
    assert any("메커니즘" in message or "불안정" in message for message in result.messages)


def test_final_wipe_still_runs_after_a_diagnosed_failure() -> None:
    """``finally: ops.wipe()`` must still fire even though the except branch
    now does real work (the diagnostic) before returning - the live domain
    must not leak into the next solve()."""
    MaterialFreeStaticsSolver().solve(_single_sway_column())
    assert ops.getNodeTags() == []


def test_analyze_failure_without_a_confirmed_mechanism_is_reported_as_such(monkeypatch) -> None:
    """``analyze() != 0`` must never be silently read as "confirmed
    mechanism" - if the diagnostic runs but finds zero near-zero modes (some
    other cause of non-convergence), the FAILED result says so explicitly."""

    def _fake_diagnose(self, model, *, tolerance=None):
        return InstabilityDiagnosticResult(
            mechanism_count=0, modes=(), message="", matrix_size=7, diagnostic_success=True
        )

    monkeypatch.setattr(InstabilityDiagnosticService, "diagnose", _fake_diagnose)
    result = MaterialFreeStaticsSolver().solve(_single_sway_column())
    ops.wipe()
    assert result.status == AnalysisStatus.FAILED
    assert result.instability_diagnostic.mechanism_count == 0
    assert any("확인되지 않았습니다" in message for message in result.messages)


def test_diagnostic_service_itself_failing_does_not_mask_the_original_error(monkeypatch) -> None:
    """A bug in the diagnostic itself must never hide the real solve
    failure - solve() still returns FAILED with the original message, just
    without diagnostic detail."""

    def _raise(self, model, *, tolerance=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(InstabilityDiagnosticService, "diagnose", _raise)
    result = MaterialFreeStaticsSolver().solve(_single_sway_column())
    ops.wipe()
    assert result.status == AnalysisStatus.FAILED
    assert result.instability_diagnostic is None
    assert any("확인되지 않았습니다" in message for message in result.messages)


def test_other_solve_failures_do_not_trigger_the_diagnostic(monkeypatch) -> None:
    """Only ``_LinearStaticConvergenceFailure`` (analyze() != 0) should ever
    reach the diagnostic - an unrelated RuntimeError (e.g. from _build/
    _apply_loads) must fall through to the plain FAILED branch untouched."""
    calls: list[StructuralModel] = []

    def _record(self, model, *, tolerance=None):
        calls.append(model)
        raise AssertionError("should not be called for a non-convergence failure")

    monkeypatch.setattr(InstabilityDiagnosticService, "diagnose", _record)

    def _boom(*args, **kwargs):
        raise RuntimeError("unrelated failure")

    monkeypatch.setattr(solver_module.MaterialFreeStaticsSolver, "_apply_loads", staticmethod(_boom))

    result = MaterialFreeStaticsSolver().solve(vertical_cantilever())
    ops.wipe()
    assert result.status == AnalysisStatus.FAILED
    assert result.instability_diagnostic is None
    assert calls == []
