"""Static wind load (p = q0*Kz*Gf*Cp) - core/domain/wind_load.py. Every
check is a hand-worked example independent of the implementation."""

import pytest

from openframe.core.domain.wind_load import (
    WindLoadParameters,
    story_tributary_heights,
    wind_force_by_story,
    wind_pressure,
)


def test_wind_pressure_is_the_plain_product_of_all_four_factors() -> None:
    assert wind_pressure(reference_pressure=1.2, kz=0.9, gust_factor=0.85, pressure_coefficient=1.3) == (
        pytest.approx(1.2 * 0.9 * 0.85 * 1.3)
    )


def test_tributary_height_two_equal_stories_splits_the_shared_span_in_half() -> None:
    """3m and 6m stories: the 3m one gets no contribution below itself
    (nothing bounds it there) plus half of the 3m span up to the 6m one
    (1.5); the 6m one gets half of that same span (1.5) plus nothing above
    (the roof line)."""
    heights = story_tributary_heights({"1F": 3.0, "2F": 6.0})
    assert heights["1F"] == pytest.approx(1.5)
    assert heights["2F"] == pytest.approx(1.5)


def test_tributary_height_three_stories_middle_one_spans_both_neighbours() -> None:
    heights = story_tributary_heights({"1F": 0.0, "2F": 4.0, "3F": 10.0})
    assert heights["1F"] == pytest.approx(2.0)  # 0 + (4-0)/2
    assert heights["2F"] == pytest.approx((4.0 - 0.0) / 2.0 + (10.0 - 4.0) / 2.0)
    assert heights["3F"] == pytest.approx((10.0 - 4.0) / 2.0)  # + 0 above the roof


def test_tributary_height_is_indifferent_to_input_order() -> None:
    ordered = story_tributary_heights({"1F": 0.0, "2F": 4.0, "3F": 10.0})
    shuffled = story_tributary_heights({"3F": 10.0, "1F": 0.0, "2F": 4.0})
    assert ordered == pytest.approx(shuffled)


def test_wind_force_by_story_hand_worked_example() -> None:
    parameters = WindLoadParameters(
        reference_pressure=1.0, gust_factor=0.85, pressure_coefficient=1.3, exposed_width=10.0
    )
    story_kz = {"1F": 0.85, "2F": 1.0}
    story_elevations = {"1F": 3.0, "2F": 6.0}

    forces = wind_force_by_story(parameters, story_kz, story_elevations)

    tributary = story_tributary_heights(story_elevations)
    expected_1f = wind_pressure(1.0, 0.85, 0.85, 1.3) * 10.0 * tributary["1F"]
    expected_2f = wind_pressure(1.0, 1.0, 0.85, 1.3) * 10.0 * tributary["2F"]
    assert forces["1F"] == pytest.approx(expected_1f)
    assert forces["2F"] == pytest.approx(expected_2f)


def test_wind_force_by_story_skips_a_story_missing_from_story_kz() -> None:
    parameters = WindLoadParameters(
        reference_pressure=1.0, gust_factor=1.0, pressure_coefficient=1.0, exposed_width=10.0
    )
    forces = wind_force_by_story(parameters, {"1F": 1.0}, {"1F": 3.0, "2F": 6.0})
    assert set(forces) == {"1F"}
