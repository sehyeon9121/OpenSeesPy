import pytest

from openframe.features.results.time_history_navigation import nearest_step_index


def test_exact_match_returns_that_index() -> None:
    times = (0.0, 0.1, 0.2, 0.3, 0.4)

    assert nearest_step_index(times, 0.2) == 2


def test_rounds_to_the_closer_neighbor() -> None:
    times = (0.0, 0.1, 0.2, 0.3, 0.4)

    assert nearest_step_index(times, 0.24) == 2
    assert nearest_step_index(times, 0.26) == 3


def test_exactly_halfway_rounds_to_the_earlier_step() -> None:
    times = (0.0, 0.2)

    assert nearest_step_index(times, 0.1) == 0


def test_before_the_first_step_clamps_to_zero() -> None:
    times = (1.0, 2.0, 3.0)

    assert nearest_step_index(times, -5.0) == 0


def test_after_the_last_step_clamps_to_the_end() -> None:
    times = (1.0, 2.0, 3.0)

    assert nearest_step_index(times, 100.0) == 2


def test_empty_times_returns_zero() -> None:
    assert nearest_step_index((), 5.0) == 0


def test_single_step_always_returns_zero() -> None:
    assert nearest_step_index((3.5,), 3.5) == 0
    assert nearest_step_index((3.5,), 999.0) == 0
