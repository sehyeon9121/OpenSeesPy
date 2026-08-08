import pytest

from openframe.features.model.drawing import (
    EntryMode,
    parse_entry,
    polar_point,
    relative_point,
)
from openframe.features.model.drawing.coordinates import (
    direction_degrees,
    distance,
    resolve_fields,
)


def test_polar_entry_places_a_gable_rafter_by_length_and_angle() -> None:
    """The eaves-to-apex member of a 10 m gable frame, typed rather than clicked."""
    x, y = polar_point((0.0, 4.0), 5.385, 21.8)

    assert x == pytest.approx(5.0, abs=1.0e-3)
    assert y == pytest.approx(6.0, abs=1.0e-3)


def test_typed_entry_accepts_the_drafting_conventions() -> None:
    anchor = (2.0, 1.0)

    assert parse_entry("4<90", anchor) == pytest.approx((2.0, 5.0))
    assert parse_entry("@3,4", anchor) == pytest.approx((5.0, 5.0))
    assert parse_entry("3,4", anchor) == pytest.approx((3.0, 4.0))
    assert parse_entry("3 4", anchor) == pytest.approx((3.0, 4.0))


def test_bare_length_follows_the_current_cursor_direction() -> None:
    anchor = (0.0, 0.0)

    assert parse_entry("5", anchor, direction_degrees=0.0) == pytest.approx((5.0, 0.0))
    assert parse_entry("5", anchor, direction_degrees=90.0) == pytest.approx((0.0, 5.0))
    assert parse_entry("5", anchor) is None


def test_incomplete_entries_are_rejected_without_raising() -> None:
    anchor = (0.0, 0.0)

    assert parse_entry("", anchor) is None
    assert parse_entry("   ", anchor) is None
    assert parse_entry("4<", anchor) is None
    assert parse_entry("abc", anchor) is None
    assert parse_entry("1,2,3", anchor) is None


def test_two_field_entry_resolves_by_mode() -> None:
    anchor = (1.0, 1.0)

    assert resolve_fields(EntryMode.POLAR, anchor, 2.0, 0.0) == pytest.approx((3.0, 1.0))
    assert resolve_fields(EntryMode.RELATIVE, anchor, 2.0, 3.0) == pytest.approx((3.0, 4.0))
    assert resolve_fields(EntryMode.ABSOLUTE, anchor, 2.0, 3.0) == pytest.approx((2.0, 3.0))


def test_direction_and_distance_round_trip_through_a_polar_point() -> None:
    anchor = (1.0, 2.0)
    target = relative_point(anchor, 3.0, 4.0)

    assert distance(anchor, target) == pytest.approx(5.0)
    assert polar_point(
        anchor, distance(anchor, target), direction_degrees(anchor, target)
    ) == pytest.approx(target)
