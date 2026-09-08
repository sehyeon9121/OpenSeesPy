"""Existing model axis conventions and pure load-integration kernels."""

import math

from openframe.core.domain.geometric_transform import (
    auto_reference_vector,
    local_y_z_axes,
    rotate_about_axis,
    validate_orientation_vector,
)
from openframe.core.domain.model import Element, StructuralModel
from openframe.core.domain.surfaces import ShellQuad
from openframe.features.model.surfaces.rectangular_mesh import WallMeshError, _assert_rectangle

from .plan import LoadCompileError, Vector3


def finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise LoadCompileError("invalid_number", f"{label} must be finite: {value!r}") from exc
    if not math.isfinite(number):
        raise LoadCompileError("invalid_number", f"{label} must be finite: {value!r}")
    return number


def member_length(model: StructuralModel, element: Element) -> float:
    try:
        start, end = model.nodes[element.node_i], model.nodes[element.node_j]
    except KeyError as exc:
        raise LoadCompileError("missing_node", f"Member {element.tag}: {exc}") from exc
    delta = tuple(
        finite(getattr(end, key), key) - finite(getattr(start, key), key)
        for key in ("x", "y", "z")[: model.ndm]
    )
    length = math.hypot(*delta)
    if length <= 0.0 or not math.isfinite(length):
        raise LoadCompileError(
            "invalid_length", f"Member {element.tag} has no finite positive length"
        )
    return length


def member_local_axes(model: StructuralModel, element: Element) -> tuple[Vector3, Vector3, Vector3]:
    """Compose the shared auto-reference / Rodrigues / local_y_z_axes helpers.

    Authored members match solver._reference_vector and canvas._local_axes.
    An imported explicit vecxz is already final: do not apply the authored roll
    a second time. Consumers of that plan must honor the same stored transform.
    Rigid offsets need the builder's flexible-axis convention, so reject those
    conversions rather than silently projecting against a different axis.
    """
    if any((*element.offset_i, *element.offset_j)):
        raise LoadCompileError(
            "offset_axes", f"Member {element.tag}: offset load projection is not supported"
        )
    length = member_length(model, element)
    start, end = model.nodes[element.node_i], model.nodes[element.node_j]
    dx, dy = (end.x - start.x) / length, (end.y - start.y) / length
    if model.ndm == 2:
        return (dx, dy, 0.0), (-dy, dx, 0.0), (0.0, 0.0, 1.0)
    axis = (dx, dy, (end.z - start.z) / length)
    if element.transf_tag is not None:
        transform = model.geometric_transforms.get(element.transf_tag)
        if transform is None:
            raise LoadCompileError(
                "missing_transform", f"Member {element.tag}: {element.transf_tag}"
            )
        reference = transform.vector_xz
    else:
        reference = auto_reference_vector(axis)
        angle = finite(element.local_axis_angle, "local_axis_angle")
        reference = rotate_about_axis(reference, axis, math.radians(angle))
    problem = validate_orientation_vector(reference, axis)
    if problem:
        raise LoadCompileError("invalid_axes", f"Member {element.tag}: {problem}")
    if not all(math.isfinite(value) for value in reference):
        raise LoadCompileError("invalid_axes", f"Member {element.tag}: nonfinite reference")
    y_axis, z_axis = local_y_z_axes(axis, reference)
    return axis, y_axis, z_axis


def to_global(local: Vector3, axes: tuple[Vector3, Vector3, Vector3]) -> Vector3:
    return tuple(sum(local[j] * axes[j][i] for j in range(3)) for i in range(3))


def to_local(global_vector: Vector3, axes: tuple[Vector3, Vector3, Vector3]) -> Vector3:
    return tuple(sum(a * b for a, b in zip(global_vector, axis)) for axis in axes)


def integrate_two_node_load(
    length: float,
    start_ratio: float,
    end_ratio: float,
    start: Vector3,
    end: Vector3,
) -> tuple[Vector3, Vector3]:
    """Integral N_i(x)*w(x) dx over [aL,bL]; TWO Gauss points are exact.

    N_i=1-x/L, N_j=x/L; w interpolates between the LOADED interval endpoints.
    N*w is quadratic. Uniform/trapezoidal, full/partial and signed components
    therefore share exactly this kernel (no case-specific closed-form branches).
    """
    midpoint = (start_ratio + end_ratio) / 2.0
    half_span = (end_ratio - start_ratio) / 2.0
    forces = [[0.0] * 3, [0.0] * 3]
    for gauss in (-1 / math.sqrt(3), 1 / math.sqrt(3)):
        xi = midpoint + half_span * gauss
        t = (1 + gauss) / 2
        intensity = tuple((1 - t) * a + t * b for a, b in zip(start, end))
        for node, shape in enumerate((1 - xi, xi)):
            for axis in range(3):
                forces[node][axis] += shape * intensity[axis] * half_span * length
    return tuple(forces[0]), tuple(forces[1])


def rectangular_quad_nodal_areas(model: StructuralModel, quad: ShellQuad) -> tuple[float, ...]:
    """First shell integration policy: A/4, exact on the existing rectangular mesh.

    Reuse the mesher's geometry validation. A future consistent quadrature rule
    can replace this function without changing self-weight or load-plan handling.
    Skew/warped/degenerate quads must not silently use the rectangular formula.
    """
    try:
        corners = tuple(
            tuple(finite(getattr(model.nodes[tag], key), key) for key in ("x", "y", "z"))
            for tag in quad.node_tags()
        )
    except KeyError as exc:
        raise LoadCompileError("missing_node", f"Shell {quad.tag}: {exc}") from exc
    try:
        _assert_rectangle(quad.tag, corners)
    except WallMeshError as exc:
        raise LoadCompileError("unsupported_quad", str(exc)) from exc
    area = math.dist(corners[0], corners[1]) * math.dist(corners[0], corners[3])
    return (area / 4.0,) * 4
