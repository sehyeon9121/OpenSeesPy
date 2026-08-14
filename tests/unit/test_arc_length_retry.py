"""Unit coverage for Arc-Length's own retry ladder (_advance_one_arc_length_step)
and the Adaptive Radius bookkeeping in run_nonlinear_static_analysis's ArcLength
branch.

Mirrors test_nonlinear_static_solver_retry.py's approach: a real model that fails
under one radius but converges under a smaller one is hard to construct
deterministically, so ops.analyze/ops.algorithm/ops.integrator are scripted
directly to verify the control flow itself (radius reduction order, give-up
conditions, Automatic Recovery on/off) - real-model accuracy is covered separately
by test_arc_length_solver.py's von Mises truss benchmark.
"""

from pathlib import Path
from unittest.mock import call, patch

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees import nonlinear_static_solver as nls
from openframe.infrastructure.opensees.nonlinear_static_solver import (
    _StepDiagnostics,
    _advance_one_arc_length_step,
)


def test_fallback_algorithm_recovers_a_step_the_primary_cannot() -> None:
    with (
        patch.object(ops, "analyze", side_effect=[1, 0]),
        patch.object(ops, "algorithm") as algorithm,
        patch.object(ops, "integrator") as integrator,
    ):
        recovered_with: set[str] = set()
        result = _advance_one_arc_length_step(
            0.01, 1.0, algorithm="Newton", recovered_with=recovered_with, min_radius=0.0001
        )

    assert result is True
    assert recovered_with == {"ModifiedNewton"}
    assert algorithm.call_args_list[-1] == call("Newton")
    # Only one radius (the nominal one) was ever tried - the fallback algorithm
    # succeeded before any reduction was needed.
    assert integrator.call_args_list == [call("ArcLength", 0.01, 1.0)]


def test_radius_halves_when_the_full_radius_never_converges() -> None:
    # Full radius fails on Newton + all 3 fallbacks (4 calls), then a halved
    # radius succeeds on the first (primary-algorithm) attempt.
    with (
        patch.object(ops, "analyze", side_effect=[1, 1, 1, 1, 0]),
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator") as integrator,
        # diagnostics is inspected below, so _record_test_iterations' own
        # ops.testIter() call must be mocked too - unlike the other tests in this
        # file, which pass diagnostics=None and never reach it.
        patch.object(ops, "testIter", return_value=0),
    ):
        recovered_with: set[str] = set()
        diagnostics = _StepDiagnostics()
        result = _advance_one_arc_length_step(
            0.01,
            1.0,
            algorithm="Newton",
            recovered_with=recovered_with,
            diagnostics=diagnostics,
            min_radius=0.0001,
        )

    assert result is True
    radii = [call_args[0][1] for call_args in integrator.call_args_list]
    assert radii == [0.01, 0.005]
    assert diagnostics.bisections == 1
    assert diagnostics.last_radius == pytest.approx(0.005)


def test_gives_up_once_the_next_radius_would_fall_below_min_radius() -> None:
    with (
        patch.object(ops, "analyze", return_value=1),
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator") as integrator,
    ):
        result = _advance_one_arc_length_step(
            0.001,
            1.0,
            algorithm="Newton",
            recovered_with=set(),
            min_radius=0.0009,
        )

    assert result is False
    # 0.001 -> the next candidate (0.0005) is below min_radius (0.0009), so only
    # the first radius is ever attempted.
    radii = [call_args[0][1] for call_args in integrator.call_args_list]
    assert radii == [0.001]


def test_stops_at_max_reductions_even_if_still_above_min_radius() -> None:
    with (
        patch.object(ops, "analyze", return_value=1),
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator") as integrator,
    ):
        result = _advance_one_arc_length_step(
            0.01,
            1.0,
            algorithm="Newton",
            recovered_with=set(),
            max_reductions=2,
            min_radius=1.0e-8,
        )

    assert result is False
    radii = [call_args[0][1] for call_args in integrator.call_args_list]
    assert radii == [0.01, 0.005, 0.0025]


def test_automatic_recovery_disabled_tries_exactly_once() -> None:
    with (
        patch.object(ops, "analyze", return_value=1) as analyze,
        patch.object(ops, "algorithm") as algorithm,
        patch.object(ops, "integrator") as integrator,
    ):
        result = _advance_one_arc_length_step(
            0.01,
            1.0,
            algorithm="Newton",
            recovered_with=set(),
            min_radius=0.0001,
            automatic_recovery=False,
        )

    assert result is False
    assert analyze.call_count == 1
    algorithm.assert_not_called()
    assert integrator.call_count == 1


#: A trivial elastic 1-DOF model - real analyze()/nodeDisp()/getTime() calls need a
#: built, defined model, but since _advance_one_arc_length_step itself is stubbed
#: out below, no actual equilibrium ever needs to be solved: the point is verifying
#: run_nonlinear_static_analysis's own Adaptive Radius bookkeeping (growth/carry-
#: forward across reporting steps), not a real convergence.
_TRIVIAL_MODEL = """
import openseespy.opensees as ops
ops.wipe()
ops.model('basic', '-ndm', 1, '-ndf', 1)
ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)
ops.uniaxialMaterial('Elastic', 1, 1000.0)
ops.element('zeroLength', 1, 1, 2, '-mat', 1, '-dir', 1)
ops.timeSeries('Linear', 1)
ops.pattern('Plain', 1, 1)
ops.load(2, 10.0)
"""


def test_adaptive_radius_grows_back_after_a_reduced_step(tmp_path: Path) -> None:
    source = tmp_path / "trivial.py"
    source.write_text(_TRIVIAL_MODEL, encoding="utf-8")

    calls = {"count": 0}

    def fake_advance(
        nominal_radius: float,
        alpha: float,
        *,
        algorithm: str,
        recovered_with: set[str],
        max_reductions: int,
        diagnostics: _StepDiagnostics,
        automatic_recovery: bool,
        min_radius: float,
    ) -> bool:
        calls["count"] += 1
        if calls["count"] == 1:
            # Step 1 "needed a reduction": report a quarter of what it started at.
            diagnostics.bisections = 1
            diagnostics.last_radius = nominal_radius / 4.0
        else:
            # Every later step "converges cleanly" at whatever radius it started.
            diagnostics.bisections = 0
            diagnostics.last_radius = nominal_radius
        return True

    try:
        with patch.object(nls, "_advance_one_arc_length_step", side_effect=fake_advance):
            result = nls.run_nonlinear_static_analysis(
                source,
                control_node=2,
                control_dof=1,
                integrator_type="ArcLength",
                arc_length_radius=0.01,
                arc_length_max_radius=0.02,
                arc_length_min_radius=0.0001,
                arc_length_max_steps=3,
                arc_length_adaptive=True,
            )
    finally:
        ops.wipe()

    radii = [point["arc_length_radius"] for point in result["load_displacement_curve"]]
    # Step 1 reduced to 0.01/4 = 0.0025 and carried that forward as step 2's
    # starting radius (clean step there, so it is reported as used unchanged).
    assert radii[0] == pytest.approx(0.0025)
    assert radii[1] == pytest.approx(0.0025)
    # Only after a clean step does it grow (x1.5, capped at MAXIMUM RADIUS 0.02):
    # step 3 starts at 0.0025 * 1.5 = 0.00375.
    assert radii[2] == pytest.approx(0.00375)


def test_automatic_recovery_off_also_disables_arc_length_radius_reduction(
    tmp_path: Path,
) -> None:
    """End-to-end regression: with Automatic Recovery off, a step that fails at the
    nominal radius must stop the run immediately - no fallback algorithm, no
    reduction - exactly like Setup's "Use Settings Only" already does for
    LoadControl/DisplacementControl. Failing on the very first step (no prior
    converged steps to report) is the same "no partial curve to fall back on"
    case the plain LoadControl/DisplacementControl path already raises for."""
    source = tmp_path / "trivial.py"
    source.write_text(_TRIVIAL_MODEL, encoding="utf-8")

    with patch.object(ops, "analyze", return_value=1):
        try:
            with pytest.raises(RuntimeError, match="첫 스텝부터 수렴하지 않았습니다"):
                nls.run_nonlinear_static_analysis(
                    source,
                    control_node=2,
                    control_dof=1,
                    integrator_type="ArcLength",
                    arc_length_radius=0.01,
                    arc_length_max_steps=5,
                    automatic_recovery=False,
                )
        finally:
            ops.wipe()
