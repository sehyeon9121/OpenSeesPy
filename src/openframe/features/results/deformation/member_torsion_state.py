"""Saint-Venant twist markers from time-history node rotations.

Projects each node's global rotation vector onto the member local x-axis
(``theta = r · ex``) and interpolates along the deformed centerline. This is
a *visualisation* of the twist component only - bending rotations perpendicular
to ``ex`` are deliberately excluded (see Phase 3-C spec §7).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from openframe.core.domain import (
    AnalysisResult,
    StructuralModel,
    auto_reference_vector,
    local_y_z_axes,
    rotate_about_axis,
)
from openframe.features.results.deformation.deformed_3d_state import Deformed3DState

_TRUSS_TYPES = frozenset({"truss", "corottruss"})
_DEFAULT_MARKER_COUNT = 5
# Twist markers are a visual hint, not a literal radian readout - beyond one
# half-turn the arms just spin in place and quaternion interpolation gets noisy.
_MAX_DISPLAY_TWIST_RAD = math.pi


@dataclass(frozen=True, slots=True)
class TorsionMarkerArm:
    element_tag: int
    marker_index: int
    axis_name: str  # "y" or "z"
    s: float
    theta_display: float
    position_x: float
    position_y: float
    position_z: float
    direction_x: float
    direction_y: float
    direction_z: float
    valid: bool


@dataclass(frozen=True, slots=True)
class MemberTorsionState:
    step_index: int
    markers: tuple[TorsionMarkerArm, ...]
    has_torsion: bool


def _clamp_theta_display(theta_display: float) -> float:
    if not math.isfinite(theta_display):
        return 0.0
    if abs(theta_display) > _MAX_DISPLAY_TWIST_RAD:
        return math.copysign(_MAX_DISPLAY_TWIST_RAD, theta_display)
    return theta_display


def _rotation_vector(displacement: tuple[float, ...]) -> tuple[float, float, float]:
    padded = (*displacement, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)[:6]
    rx, ry, rz = float(padded[3]), float(padded[4]), float(padded[5])
    if not (math.isfinite(rx) and math.isfinite(ry) and math.isfinite(rz)):
        return 0.0, 0.0, 0.0
    return rx, ry, rz


def _unit_vector(
    start: tuple[float, float, float], end: tuple[float, float, float]
) -> tuple[float, float, float] | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length <= 1.0e-12:
        return None
    return (dx / length, dy / length, dz / length)


def _initial_local_axes(
    axis: tuple[float, float, float],
    local_axis_angle: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    reference = auto_reference_vector(axis)
    if local_axis_angle:
        reference = rotate_about_axis(reference, axis, math.radians(local_axis_angle))
    return local_y_z_axes(axis, reference)


def build_member_torsion_state(
    model: StructuralModel,
    result: AnalysisResult,
    deformed_state: Deformed3DState,
    step_index: int,
    rotation_scale: float,
    marker_count: int = _DEFAULT_MARKER_COUNT,
) -> MemberTorsionState | None:
    """Build per-marker orientation data for one time-history step."""
    if not result.time_history or model.ndm != 3 or marker_count < 1:
        return None

    clamped_index = max(0, min(step_index, len(result.time_history) - 1))
    step = result.time_history[clamped_index]
    scale = float(rotation_scale)
    if not math.isfinite(scale):
        scale = 0.0

    markers: list[TorsionMarkerArm] = []
    has_torsion = False

    for element in sorted(model.elements.values(), key=lambda item: item.tag):
        if element.element_type.lower() in _TRUSS_TYPES:
            continue
        node_i = deformed_state.node_lookup.get(element.node_i)
        node_j = deformed_state.node_lookup.get(element.node_j)
        if node_i is None or node_j is None:
            continue

        start = (node_i.deformed_x, node_i.deformed_y, node_i.deformed_z)
        end = (node_j.deformed_x, node_j.deformed_y, node_j.deformed_z)
        axis = _unit_vector(start, end)
        if axis is None:
            continue

        result_i = step.node_results.get(element.node_i)
        result_j = step.node_results.get(element.node_j)
        ri = _rotation_vector(result_i.displacement if result_i is not None else ())
        rj = _rotation_vector(result_j.displacement if result_j is not None else ())
        theta_i = ri[0] * axis[0] + ri[1] * axis[1] + ri[2] * axis[2]
        theta_j = rj[0] * axis[0] + rj[1] * axis[1] + rj[2] * axis[2]
        if abs(theta_i) > 1.0e-12 or abs(theta_j) > 1.0e-12:
            has_torsion = True

        ey0, ez0 = _initial_local_axes(axis, element.local_axis_angle)

        for marker_index in range(marker_count):
            station = marker_index / (marker_count - 1) if marker_count > 1 else 0.0
            theta = (1.0 - station) * theta_i + station * theta_j
            theta_display = _clamp_theta_display(scale * theta)
            ey = rotate_about_axis(ey0, axis, theta_display)
            ez = rotate_about_axis(ez0, axis, theta_display)
            position = tuple(start[k] + station * (end[k] - start[k]) for k in range(3))
            for axis_name, direction in (("y", ey), ("z", ez)):
                markers.append(
                    TorsionMarkerArm(
                        element_tag=element.tag,
                        marker_index=marker_index,
                        axis_name=axis_name,
                        s=station,
                        theta_display=theta_display,
                        position_x=position[0],
                        position_y=position[1],
                        position_z=position[2],
                        direction_x=direction[0],
                        direction_y=direction[1],
                        direction_z=direction[2],
                        valid=True,
                    )
                )

    return MemberTorsionState(
        step_index=clamped_index,
        markers=tuple(markers),
        has_torsion=has_torsion,
    )
