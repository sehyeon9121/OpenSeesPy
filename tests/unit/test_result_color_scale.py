import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openframe.features.results.presentation.result_color_scale import (
    color_for_ratio,
    ratio_of,
)


def test_scale_ends_match_the_legend_gradient() -> None:
    assert color_for_ratio(0.0).name() == "#2563eb"
    assert color_for_ratio(1.0).name() == "#e5484d"
    assert color_for_ratio(0.5).name() == "#f7d154"


def test_values_between_stops_are_blended() -> None:
    quarter = color_for_ratio(0.25)

    # Half way from blue to yellow: every channel lies between the two stops.
    assert 37 < quarter.red() < 247
    assert 99 < quarter.green() < 209
    assert 84 < quarter.blue() < 235


def test_ratios_outside_the_scale_are_clamped() -> None:
    assert color_for_ratio(-2.0).name() == color_for_ratio(0.0).name()
    assert color_for_ratio(7.0).name() == color_for_ratio(1.0).name()


def test_ratio_of_is_the_share_of_the_peak() -> None:
    assert ratio_of(5.0, 20.0) == 0.25
    assert ratio_of(-20.0, 20.0) == 1.0


def test_ratio_of_a_zero_peak_is_zero_rather_than_a_division_error() -> None:
    assert ratio_of(0.0, 0.0) == 0.0
