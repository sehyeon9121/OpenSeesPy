"""Geometry helpers behind the moment-reaction arrow.

Regression coverage for two bugs: the arrowhead used to sit at hardcoded coordinates
disconnected from where the arc actually ended, and the two rotational directions must
stay visually distinguishable (opposite sweeps).
"""

import math

import pytest

from openframe.features.results.presentation.support_reaction_item import (
    SupportReactionItem,
)


def test_point_on_circle_matches_the_clock_face_convention() -> None:
    # 0 deg is 3 o'clock; 90 deg is 12 o'clock, i.e. up, which is negative screen y.
    three_oclock = SupportReactionItem._point_on_circle(10.0, 0.0)
    twelve_oclock = SupportReactionItem._point_on_circle(10.0, 90.0)

    assert three_oclock.x() == pytest.approx(10.0)
    assert three_oclock.y() == pytest.approx(0.0, abs=1e-9)
    assert twelve_oclock.x() == pytest.approx(0.0, abs=1e-9)
    assert twelve_oclock.y() == pytest.approx(-10.0)


def test_travel_direction_is_unit_length_and_tangent_to_the_circle() -> None:
    point = SupportReactionItem._point_on_circle(10.0, 40.0)
    travel = SupportReactionItem._travel_direction(40.0, 1.0)

    assert math.hypot(travel.x(), travel.y()) == pytest.approx(1.0)
    # Tangent is perpendicular to the radius at that point.
    dot_product = point.x() * travel.x() + point.y() * travel.y()
    assert dot_product == pytest.approx(0.0, abs=1e-9)


def test_travel_direction_reverses_with_rotation_sense() -> None:
    clockwise = SupportReactionItem._travel_direction(40.0, -1.0)
    counter_clockwise = SupportReactionItem._travel_direction(40.0, 1.0)

    assert clockwise.x() == pytest.approx(-counter_clockwise.x())
    assert clockwise.y() == pytest.approx(-counter_clockwise.y())


def test_positive_and_negative_moments_end_on_opposite_sides() -> None:
    """The arc for +Mz and -Mz must visibly diverge, not overlap or mirror in place."""
    start = SupportReactionItem._MOMENT_START_DEGREES
    sweep = SupportReactionItem._MOMENT_SWEEP_DEGREES
    radius = SupportReactionItem._MOMENT_RADIUS

    positive_end = SupportReactionItem._point_on_circle(radius, start + sweep)
    negative_end = SupportReactionItem._point_on_circle(radius, start - sweep)

    separation = math.hypot(
        positive_end.x() - negative_end.x(), positive_end.y() - negative_end.y()
    )
    assert separation > radius  # far enough apart to read as different directions
