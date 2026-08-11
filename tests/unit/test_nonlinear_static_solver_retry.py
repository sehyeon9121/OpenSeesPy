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
