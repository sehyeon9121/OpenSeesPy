"""Pure, openseespy-free coverage for the geometric_transform domain module."""

from openframe.core.domain.geometric_transform import (
    ORIENTATION_LOCAL_AXES_FAILED,
    ORIENTATION_VECTOR_MISSING,
    ORIENTATION_VECTOR_PARALLEL_TO_AXIS,
    ORIENTATION_VECTOR_ZERO,
    GeometricTransform,
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
