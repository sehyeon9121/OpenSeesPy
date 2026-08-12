"""Unit coverage for the algorithm-fallback + step-bisection retry mechanism.

A real material that fails under the *configured* algorithm/step size but succeeds
under a fallback is hard to construct deterministically (small test models tend to
converge or fail the same way regardless of algorithm - see the integration tests in
test_nonlinear_static_solver.py for real solves). ops.analyze/ops.algorithm/
ops.integrator are scripted directly instead, to verify the retry control flow
itself: which algorithms get tried, in what order, and that a step only counts as
failed once bisection is also exhausted.
"""

from unittest.mock import call, patch

import openseespy.opensees as ops

from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.nonlinear_static_solver import (
    _StepDiagnostics,
    _advance_one_step,
    _analyze_with_fallback,
    _model_nonlinearity_warnings,
)


def test_fallback_algorithm_recovers_a_step_the_primary_cannot() -> None:
    with (
        patch.object(ops, "analyze", side_effect=[1, 0]) as analyze,
        patch.object(ops, "algorithm") as algorithm,
    ):
        recovered_with: set[str] = set()
        assert _analyze_with_fallback("Newton", recovered_with) is True

    assert analyze.call_count == 2
    # ModifiedNewton is the first candidate after Newton itself in the fallback list.
    assert recovered_with == {"ModifiedNewton"}
    # The primary algorithm must be restored so later steps aren't left on the
    # fallback's algorithm by accident.
    assert algorithm.call_args_list[-1] == call("Newton")


def test_all_algorithms_failing_reports_failure() -> None:
    with (
        patch.object(ops, "analyze", side_effect=[1, 1, 1, 1]),
        patch.object(ops, "algorithm"),
    ):
        assert _analyze_with_fallback("Newton", set()) is False


def test_step_bisects_when_the_full_increment_never_converges() -> None:
    # Full increment fails on Newton + all 3 fallbacks (4 calls), then a halved
    # increment succeeds twice in a row (covering the same total increment in two
    # half-sized pieces) without needing any fallback algorithm itself.
    with (
        patch.object(ops, "analyze", side_effect=[1, 1, 1, 1, 0, 0]),
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator") as integrator,
    ):
        recovered_with: set[str] = set()
        result = _advance_one_step(
            1.0,
            integrator_type="LoadControl",
            control_node=1,
            control_dof=1,
            algorithm="Newton",
            recovered_with=recovered_with,
        )

    assert result is True
    # First attempt at the full increment, then two half-sized ones once it fails.
    increments = [args[0][1] for args in integrator.call_args_list]
    assert increments == [1.0, 0.5, 0.5]


def test_step_gives_up_after_the_bisection_limit() -> None:
    # Every attempt fails, at every halving depth - eventually _advance_one_step
    # must stop retrying rather than bisect forever.
    with (
        patch.object(ops, "analyze", return_value=1),
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator"),
    ):
        result = _advance_one_step(
            1.0,
            integrator_type="LoadControl",
            control_node=1,
            control_dof=1,
            algorithm="Newton",
            recovered_with=set(),
        )

    assert result is False


def test_apparently_elastic_model_gets_a_nonlinearity_warning() -> None:
    collector = ModelCommandCollector()
    collector.material_types.add("Elastic")
    collector.elements[1] = {"element_type": "Truss"}

    assert _model_nonlinearity_warnings(collector)

    collector.material_types.add("Steel01")
    assert _model_nonlinearity_warnings(collector) == []


def test_automatic_recovery_disabled_skips_the_fallback_algorithms() -> None:
    # Only the primary algorithm's own attempt happens - none of the 3 other
    # standard algorithms _FALLBACK_ALGORITHMS would otherwise try.
    with (
        patch.object(ops, "analyze", return_value=1) as analyze,
        patch.object(ops, "algorithm") as algorithm,
    ):
        result = _analyze_with_fallback(
            "Newton", set(), automatic_recovery=False
        )

    assert result is False
    assert analyze.call_count == 1
    algorithm.assert_not_called()


def test_automatic_recovery_disabled_skips_bisection_too() -> None:
    # The full increment's single failed attempt ends the step immediately -
    # no halved retry, unlike the default (see test_step_bisects_...).
    with (
        patch.object(ops, "analyze", return_value=1),
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator") as integrator,
    ):
        result = _advance_one_step(
            1.0,
            integrator_type="LoadControl",
            control_node=1,
            control_dof=1,
            algorithm="Newton",
            recovered_with=set(),
            automatic_recovery=False,
        )

    assert result is False
    assert integrator.call_count == 1


def test_min_increment_stops_bisecting_before_the_depth_limit_is_reached() -> None:
    # Every attempt fails regardless of size, so each bisection depth costs a
    # full pass through primary + 3 fallback algorithms (4 ops.analyze calls).
    # Without min_increment, depth goes 1.0 -> 0.5 -> 0.25 -> 0.125 -> 0.0625
    # (5 attempts x 4 = 20 calls, stopped by max_bisections=4's depth limit).
    # With min_increment=0.3, the candidate after 0.5 (0.25, below 0.3) is
    # never attempted - only 2 attempts x 4 = 8 calls happen.
    with (
        patch.object(ops, "analyze", return_value=1) as analyze,
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator"),
        patch.object(ops, "testIter", return_value=3),
    ):
        result = _advance_one_step(
            1.0,
            integrator_type="LoadControl",
            control_node=1,
            control_dof=1,
            algorithm="Newton",
            recovered_with=set(),
            min_increment=0.3,
        )

    assert result is False
    assert analyze.call_count == 8


def test_starting_fraction_lets_a_step_skip_straight_to_a_smaller_increment() -> None:
    # Adaptive Step's whole point: a step that starts at 0.5 (because the
    # previous step already proved 1.0 does not converge) never wastes an
    # attempt on the full increment - it goes straight to two half-sized
    # substeps (still covering the full reporting step, same as always).
    with (
        patch.object(ops, "analyze", return_value=0) as analyze,
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator") as integrator,
        patch.object(ops, "testIter", return_value=3),
    ):
        diagnostics = _StepDiagnostics()
        result = _advance_one_step(
            1.0,
            integrator_type="LoadControl",
            control_node=1,
            control_dof=1,
            algorithm="Newton",
            recovered_with=set(),
            starting_fraction=0.5,
            diagnostics=diagnostics,
        )

    assert result is True
    # Two half-sized substeps (never a full 1.0-sized attempt) cover the step.
    assert analyze.call_count == 2
    increments = [args[0][1] for args in integrator.call_args_list]
    assert increments == [0.5, 0.5]
    assert diagnostics.last_fraction == 0.5


def test_last_fraction_records_the_size_that_actually_converged() -> None:
    # Same scenario as test_step_bisects_when_the_full_increment_never_converges
    # (fails at 1.0, succeeds at 0.5 twice) - diagnostics.last_fraction is what
    # Adaptive Step carries forward to the next reporting step's starting_fraction.
    with (
        patch.object(ops, "analyze", side_effect=[1, 1, 1, 1, 0, 0]),
        patch.object(ops, "algorithm"),
        patch.object(ops, "integrator"),
        patch.object(ops, "testIter", return_value=3),
    ):
        diagnostics = _StepDiagnostics()
        result = _advance_one_step(
            1.0,
            integrator_type="LoadControl",
            control_node=1,
            control_dof=1,
            algorithm="Newton",
            recovered_with=set(),
            diagnostics=diagnostics,
        )

    assert result is True
    assert diagnostics.last_fraction == 0.5
