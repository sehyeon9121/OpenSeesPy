"""``ops.geomTransf(...)`` references collected from an OpenSeesPy model.

Kept separate from ``model.Element`` because a transformation is a shared
domain object (many elements may reference the same tag), not a per-element
property - mirrors how OpenSeesPy itself models it.
"""

import math
from dataclasses import dataclass, field

#: Transformation types Setup's GEOMETRIC TRANSFORMATION override may
#: substitute for one another - the only three whose
#: ``ops.geomTransf(type, tag, *transfArgs)`` argument shape is identical,
#: which is what makes the substitution safe (see
#: ModelCommandCollector.install(geom_transf_override=...) and
#: run_nonlinear_static_analysis). Any other type name (unrecognized, or a
#: real but unsupported-for-override OpenSees transform) is preserved as-is
#: and never silently coerced into one of these.
OVERRIDABLE_TRANSFORM_TYPES = frozenset({"Linear", "PDelta", "Corotational"})


@dataclass(frozen=True, slots=True)
class GeometricTransform:
    """One ``ops.geomTransf(transform_type, tag, *arguments)`` call.

    ``arguments`` is exactly the raw positional arguments after ``tag`` -
    for a 3D model this is typically ``(vecxz_x, vecxz_y, vecxz_z, ...)``,
    optionally followed by ``'-jntOffset'`` and offset values; for 2D it is
    usually empty. Kept as a raw tuple (not decomposed into named fields) so
    an unrecognized transform type's arguments are preserved exactly as
    given, never guessed at.
    """

    tag: int
    transform_type: str
    arguments: tuple[float | str, ...] = field(default_factory=tuple)

    @property
    def is_overridable(self) -> bool:
        """Whether Setup's GEOMETRIC TRANSFORMATION override may replace this
        transform's type. Unknown/unsupported types are never overridable -
        overriding them would silently discard information this project
        cannot reconstruct."""
        return self.transform_type in OVERRIDABLE_TRANSFORM_TYPES

    @property
    def vector_xz(self) -> tuple[float, float, float] | None:
        """The 3D orientation vector (``vecxz``), when the leading arguments
        are all numeric - ``None`` for a 2D transform (no vector expected) or
        when the arguments could not be parsed as a plain numeric vector."""
        if len(self.arguments) < 3:
            return None
        leading = self.arguments[:3]
        if not all(isinstance(value, (int, float)) for value in leading):
            return None
        return (float(leading[0]), float(leading[1]), float(leading[2]))


#: Reasons ``validate_orientation_vector`` may return - each maps to a fixed,
#: user-facing message via ``ORIENTATION_ERROR_MESSAGES`` below.
ORIENTATION_VECTOR_MISSING = "vector_missing"
ORIENTATION_VECTOR_ZERO = "vector_zero"
ORIENTATION_VECTOR_PARALLEL_TO_AXIS = "vector_parallel_to_axis"
ORIENTATION_LOCAL_AXES_FAILED = "local_axes_failed"

#: Korean message fragment for each reason code above - shared by every call
#: site that reports a blocked 3D orientation (model_collector.py's live
#: ops.element(...) guard is the one that actually fires in practice, since
#: OpenSeesPy itself does not raise a catchable exception for a degenerate
#: vector; kept here rather than duplicated at each call site).
ORIENTATION_ERROR_MESSAGES: dict[str, str] = {
    ORIENTATION_VECTOR_MISSING: "3D orientation vector(vecxz)가 없습니다",
    ORIENTATION_VECTOR_ZERO: "orientation vector가 영벡터입니다",
    ORIENTATION_VECTOR_PARALLEL_TO_AXIS: (
        "orientation vector가 부재축과 평행하여 로컬축을 계산할 수 없습니다"
    ),
    ORIENTATION_LOCAL_AXES_FAILED: "로컬축 계산에 실패했습니다",
}


def validate_orientation_vector(
    vector_xz: tuple[float, float, float] | None,
    axis_vector: tuple[float, float, float],
) -> str | None:
    """Return a failure reason code, or ``None`` if ``vector_xz`` is usable to
    build a 3D beam-column's local axis system with ``axis_vector`` (the
    member's own i->j direction) - mirrors the degeneracy OpenSeesPy itself
    would reject at ``ops.element(...)`` time (``cross(axis, vecxz)`` too
    small to normalize), checked ahead of time so the analysis can be blocked
    with a clear reason instead of a raw OpenSeesError.
    """
    if vector_xz is None:
        return ORIENTATION_VECTOR_MISSING
    magnitude = math.sqrt(sum(component * component for component in vector_xz))
    if math.isclose(magnitude, 0.0, abs_tol=1e-12):
        return ORIENTATION_VECTOR_ZERO
    axis_magnitude = math.sqrt(sum(component * component for component in axis_vector))
    if math.isclose(axis_magnitude, 0.0, abs_tol=1e-12):
        # A zero-length member has no well-defined axis at all - not the
        # vector's fault, but local axes still cannot be built.
        return ORIENTATION_LOCAL_AXES_FAILED
    cross = (
        axis_vector[1] * vector_xz[2] - axis_vector[2] * vector_xz[1],
        axis_vector[2] * vector_xz[0] - axis_vector[0] * vector_xz[2],
        axis_vector[0] * vector_xz[1] - axis_vector[1] * vector_xz[0],
    )
    cross_magnitude = math.sqrt(sum(component * component for component in cross))
    # Normalized by the product of magnitudes so the parallel test is scale-
    # independent - a tiny cross product from two long vectors is still
    # "parallel" in direction, which is what actually matters here.
    if math.isclose(cross_magnitude / (magnitude * axis_magnitude), 0.0, abs_tol=1e-9):
        return ORIENTATION_VECTOR_PARALLEL_TO_AXIS
    return None
