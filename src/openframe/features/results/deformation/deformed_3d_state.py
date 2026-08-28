"""Pure 3D deformed-state builder for time-history animation.

Every displayed position is ``original + translation_scale × (Ux, Uy, Uz)``.
Nothing here touches Qt, QML, or the domain model's stored node coordinates -
callers pass a ``StructuralModel`` and ``AnalysisResult`` read-only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from openframe.core.domain import AnalysisResult, StructuralModel

#: Same ~8% rule of thumb as ResultViewport / 2D Time History animation.
_AUTO_SCALE_TARGET_FRACTION = 0.08
_MIN_AUTO_SCALE = 1.0
_MAX_AUTO_SCALE = 10_000.0


@dataclass(frozen=True, slots=True)
class DeformedNode3D:
    node_tag: int
    original_x: float
    original_y: float
    original_z: float
    deformed_x: float
    deformed_y: float
    deformed_z: float
    valid: bool


@dataclass(frozen=True, slots=True)
class Deformed3DState:
    """One time step's worth of 3D node positions for rendering."""

    step_index: int
    step_time: float
    nodes: tuple[DeformedNode3D, ...]
    node_lookup: dict[int, DeformedNode3D]
    max_translation_magnitude: float


def _translation_components(displacement: tuple[float, ...]) -> tuple[float, float, float]:
    padded = (*displacement, 0.0, 0.0, 0.0)
    ux, uy, uz = float(padded[0]), float(padded[1]), float(padded[2])
    if not (math.isfinite(ux) and math.isfinite(uy) and math.isfinite(uz)):
        return 0.0, 0.0, 0.0
    return ux, uy, uz


def build_deformed_3d_state(
    model: StructuralModel,
    result: AnalysisResult,
    step_index: int,
    translation_scale: float,
) -> Deformed3DState | None:
    """Build per-node original/deformed coordinates for one time-history step.

    Missing node results keep the original position with ``valid=False``.
    Unknown result node tags (not in the model) are ignored. Out-of-range
    ``step_index`` values are clamped. ``translation_scale == 0`` still returns
    valid geometry at the undeformed positions.
    """
    if not result.time_history or not model.nodes:
        return None

    clamped_index = max(0, min(step_index, len(result.time_history) - 1))
    step = result.time_history[clamped_index]
    scale = float(translation_scale)
    if not math.isfinite(scale):
        scale = 0.0

    nodes: list[DeformedNode3D] = []
    lookup: dict[int, DeformedNode3D] = {}
    max_magnitude = 0.0

    for node_tag in sorted(model.nodes):
        node = model.nodes[node_tag]
        node_result = step.node_results.get(node_tag)
        if node_result is None:
            entry = DeformedNode3D(
                node_tag=node_tag,
                original_x=node.x,
                original_y=node.y,
                original_z=node.z,
                deformed_x=node.x,
                deformed_y=node.y,
                deformed_z=node.z,
                valid=False,
            )
        else:
            ux, uy, uz = _translation_components(node_result.displacement)
            magnitude = math.sqrt(ux * ux + uy * uy + uz * uz)
            max_magnitude = max(max_magnitude, magnitude)
            entry = DeformedNode3D(
                node_tag=node_tag,
                original_x=node.x,
                original_y=node.y,
                original_z=node.z,
                deformed_x=node.x + ux * scale,
                deformed_y=node.y + uy * scale,
                deformed_z=node.z + uz * scale,
                valid=True,
            )
        nodes.append(entry)
        lookup[node_tag] = entry

    return Deformed3DState(
        step_index=clamped_index,
        step_time=step.time,
        nodes=tuple(nodes),
        node_lookup=lookup,
        max_translation_magnitude=max_magnitude,
    )


def compute_3d_translation_auto_scale(
    model: StructuralModel,
    result: AnalysisResult,
    *,
    target_fraction: float = _AUTO_SCALE_TARGET_FRACTION,
) -> float:
    """Return a display multiplier from model extent and peak |U| over all steps."""
    if not model.nodes or not result.time_history:
        return _MIN_AUTO_SCALE

    max_displacement = 0.0
    for step in result.time_history:
        for node_result in step.node_results.values():
            ux, uy, uz = _translation_components(node_result.displacement)
            max_displacement = max(max_displacement, math.sqrt(ux * ux + uy * uy + uz * uz))

    if max_displacement <= 0.0:
        return _MIN_AUTO_SCALE

    xs = [node.x for node in model.nodes.values()]
    ys = [node.y for node in model.nodes.values()]
    zs = [node.z for node in model.nodes.values()]
    span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1.0)
    raw = (span * target_fraction) / max_displacement
    return max(_MIN_AUTO_SCALE, min(_MAX_AUTO_SCALE, raw))


def member_deformed_endpoints(
    model: StructuralModel,
    state: Deformed3DState,
    element_tag: int,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """Straight deformed member line from transformed end nodes (MVP - no curvature)."""
    element = model.elements.get(element_tag)
    if element is None:
        return None
    node_i = state.node_lookup.get(element.node_i)
    node_j = state.node_lookup.get(element.node_j)
    if node_i is None or node_j is None:
        return None
    return (
        (node_i.deformed_x, node_i.deformed_y, node_i.deformed_z),
        (node_j.deformed_x, node_j.deformed_y, node_j.deformed_z),
    )
