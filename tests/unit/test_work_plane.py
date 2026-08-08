import pytest

from openframe.features.model.drawing import PlaneKind, WorkPlane


def test_the_default_plane_is_ground_level_and_behaves_like_ordinary_2d() -> None:
    """A 2D canvas is exactly a 3D one whose only plane is the ground at Z=0."""
    plane = WorkPlane()

    assert plane.to_3d(3.0, 4.0) == (3.0, 4.0, 0.0)
    assert plane.to_2d((3.0, 4.0, 0.0)) == (3.0, 4.0)
    assert plane.contains((3.0, 4.0, 0.0)) is True
    assert plane.contains((3.0, 4.0, 0.5)) is False


def test_a_storey_plan_offsets_along_z() -> None:
    second_floor = WorkPlane(PlaneKind.XY, offset=3.5, label="2F")

    assert second_floor.to_3d(2.0, 1.0) == (2.0, 1.0, 3.5)
    assert second_floor.to_2d((2.0, 1.0, 3.5)) == (2.0, 1.0)
    assert second_floor.distance((2.0, 1.0, 3.5)) == pytest.approx(0.0)
    assert second_floor.distance((2.0, 1.0, 0.0)) == pytest.approx(3.5)


def test_a_front_elevation_plane_draws_x_against_z_at_a_fixed_y() -> None:
    front = WorkPlane(PlaneKind.XZ, offset=2.0, label="Y=2")

    assert front.to_3d(5.0, 3.0) == (5.0, 2.0, 3.0)
    assert front.to_2d((5.0, 2.0, 3.0)) == (5.0, 3.0)
    assert front.contains((5.0, 2.0, 3.0)) is True
    assert front.contains((5.0, 2.1, 3.0)) is False


def test_a_side_elevation_plane_draws_y_against_z_at_a_fixed_x() -> None:
    side = WorkPlane(PlaneKind.YZ, offset=-1.5)

    assert side.to_3d(4.0, 6.0) == (-1.5, 4.0, 6.0)
    assert side.to_2d((-1.5, 4.0, 6.0)) == (4.0, 6.0)


def test_round_trip_through_to_3d_and_to_2d_is_the_identity_on_the_plane() -> None:
    for kind in (PlaneKind.XY, PlaneKind.XZ, PlaneKind.YZ):
        plane = WorkPlane(kind, offset=1.25)
        u, v = 7.0, -2.5
        assert plane.to_2d(plane.to_3d(u, v)) == pytest.approx((u, v))


def test_moved_to_keeps_the_orientation_and_changes_only_the_offset() -> None:
    ground = WorkPlane(PlaneKind.XY, offset=0.0, label="1F")

    third_floor = ground.moved_to(7.0)

    assert third_floor.kind is PlaneKind.XY
    assert third_floor.offset == pytest.approx(7.0)
    assert third_floor.label == "1F"


def test_contains_respects_a_custom_tolerance() -> None:
    plane = WorkPlane(PlaneKind.XY, offset=0.0)

    assert plane.contains((0.0, 0.0, 0.02), tolerance=0.05) is True
    assert plane.contains((0.0, 0.0, 0.02), tolerance=0.001) is False
