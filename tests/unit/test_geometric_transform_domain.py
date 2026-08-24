"""Pure, openseespy-free coverage for the geometric_transform domain module."""

import math

import pytest

from openframe.core.domain.geometric_transform import (
    ORIENTATION_LOCAL_AXES_FAILED,
    ORIENTATION_VECTOR_MISSING,
    ORIENTATION_VECTOR_PARALLEL_TO_AXIS,
    ORIENTATION_VECTOR_ZERO,
    GeometricTransform,
    auto_reference_vector,
    local_y_z_axes,
    rotate_about_axis,
    validate_orientation_vector,
)


def test_overridable_types_are_exactly_linear_pdelta_corotational() -> None:
    assert GeometricTransform(1, "Linear").is_overridable
    assert GeometricTransform(1, "PDelta").is_overridable
    assert GeometricTransform(1, "Corotational").is_overridable
    assert not GeometricTransform(1, "Corotational02").is_overridable
    assert not GeometricTransform(1, "SomeFutureTransform").is_overridable


def test_vector_xz_reads_the_first_three_numeric_arguments() -> None:
    transform = GeometricTransform(1, "Linear", (0.0, 0.0, 1.0))
    assert transform.vector_xz == (0.0, 0.0, 1.0)


def test_vector_xz_is_none_for_a_2d_transform_with_no_arguments() -> None:
    assert GeometricTransform(1, "Linear", ()).vector_xz is None


def test_vector_xz_is_none_when_leading_arguments_are_not_numeric() -> None:
    # e.g. a '-jntOffset' flag appearing before three real numbers would not
    # happen in practice, but the parser must not misread flag text as a
    # vector component rather than crash or silently coerce it.
    transform = GeometricTransform(1, "Linear", ("-jntOffset", 0.0, 0.0))
    assert transform.vector_xz is None


def test_validate_orientation_vector_accepts_a_perpendicular_vector() -> None:
    axis = (1.0, 0.0, 0.0)
    vecxz = (0.0, 0.0, 1.0)
    assert validate_orientation_vector(vecxz, axis) is None


def test_validate_orientation_vector_rejects_missing_vector() -> None:
    assert validate_orientation_vector(None, (1.0, 0.0, 0.0)) == ORIENTATION_VECTOR_MISSING


def test_validate_orientation_vector_rejects_zero_vector() -> None:
    assert (
        validate_orientation_vector((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)) == ORIENTATION_VECTOR_ZERO
    )


def test_validate_orientation_vector_rejects_vector_parallel_to_axis() -> None:
    axis = (2.0, 0.0, 0.0)
    vecxz = (5.0, 0.0, 0.0)
    assert (
        validate_orientation_vector(vecxz, axis) == ORIENTATION_VECTOR_PARALLEL_TO_AXIS
    )


def test_validate_orientation_vector_rejects_degenerate_zero_length_axis() -> None:
    assert (
        validate_orientation_vector((0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
        == ORIENTATION_LOCAL_AXES_FAILED
    )


def test_validate_orientation_vector_is_scale_independent() -> None:
    """A long axis and a long, merely-nearly-parallel vector must not slip
    through just because their raw cross product magnitude looks large."""
    axis = (1000.0, 0.0, 0.0)
    nearly_parallel = (1000.0, 0.0, 1e-10)
    assert (
        validate_orientation_vector(nearly_parallel, axis) == ORIENTATION_VECTOR_PARALLEL_TO_AXIS
    )


def test_auto_reference_vector_picks_global_z_for_a_horizontal_member() -> None:
    assert auto_reference_vector((1.0, 0.0, 0.0)) == (0.0, 0.0, 1.0)


def test_auto_reference_vector_falls_back_to_global_x_for_a_vertical_member() -> None:
    assert auto_reference_vector((0.0, 0.0, 1.0)) == (1.0, 0.0, 0.0)


def test_rotate_about_axis_by_zero_degrees_is_the_identity() -> None:
    vector = (0.0, 0.0, 1.0)
    assert rotate_about_axis(vector, (1.0, 0.0, 0.0), 0.0) == pytest.approx(vector)


def test_rotate_about_axis_by_90_degrees_matches_hand_computed_result() -> None:
    """Rotating global Z by 90 degrees about the X axis (right-hand rule)
    lands on -Y - the textbook case used to sanity-check any rotation
    formula's sign convention."""
    rotated = rotate_about_axis((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), math.pi / 2)
    assert rotated == pytest.approx((0.0, -1.0, 0.0), abs=1e-9)


def test_rotate_about_axis_preserves_the_component_parallel_to_the_axis() -> None:
    """A vector already lying partly along the rotation axis keeps that
    component unchanged - only its perpendicular part swings around -
    which is exactly why a `vecxz` reference vector need not itself be
    perpendicular to the member for this rotation to be meaningful."""
    axis = (1.0, 0.0, 0.0)
    vector = (0.5, 0.0, 1.0)  # 0.5 along axis, 1.0 perpendicular
    rotated = rotate_about_axis(vector, axis, math.pi / 2)
    assert rotated[0] == pytest.approx(0.5, abs=1e-9)


def test_local_y_z_axes_are_unit_length_and_mutually_orthogonal_with_the_axis() -> None:
    axis = (0.0, 1.0, 0.0)
    reference = auto_reference_vector(axis)
    y_axis, z_axis = local_y_z_axes(axis, reference)
    for vector in (y_axis, z_axis):
        length = math.sqrt(sum(component * component for component in vector))
        assert length == pytest.approx(1.0)
    dot_axis_y = sum(a * b for a, b in zip(axis, y_axis, strict=True))
    dot_axis_z = sum(a * b for a, b in zip(axis, z_axis, strict=True))
    dot_y_z = sum(a * b for a, b in zip(y_axis, z_axis, strict=True))
    assert dot_axis_y == pytest.approx(0.0, abs=1e-9)
    assert dot_axis_z == pytest.approx(0.0, abs=1e-9)
    assert dot_y_z == pytest.approx(0.0, abs=1e-9)


def test_local_y_z_axes_rotate_together_with_the_reference_vector() -> None:
    """A 90-degree rotation of the reference vector about the member axis
    (exactly what `Element.local_axis_angle=90` produces) must rotate the
    resulting local y/z axes by the same 90 degrees - swapping which one
    points where the other used to."""
    axis = (1.0, 0.0, 0.0)
    reference = auto_reference_vector(axis)
    y_before, z_before = local_y_z_axes(axis, reference)

    rotated_reference = rotate_about_axis(reference, axis, math.pi / 2)
    y_after, z_after = local_y_z_axes(axis, rotated_reference)

    assert y_after == pytest.approx(z_before, abs=1e-9)
    assert z_after == pytest.approx(tuple(-c for c in y_before), abs=1e-9)
