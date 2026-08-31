"""Screen-overlay numbers for the 3D result view, one set per result type.

Qt-free: each label is a structural (x, y, z) plus a short string. The Quick3D
overlay projects those to pixels so they stay readable while the camera orbits,
the same idea as MIDAS putting N/V/M and |U| on the members themselves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from openframe.core.domain import (
    AnalysisResult,
    Node,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.diagrams.base import DiagramKind
from openframe.features.results.diagrams.spatial import spatial_diagram_strips
from openframe.features.results.stress import peak_member_stress

#: Above this many labels the 3D overlay turns into a cloud; keep the largest
#: by |value| and let the table carry the rest.
_LABEL_CAP = 80
_RELATIVE_NOISE = 1.0e-9


@dataclass(frozen=True, slots=True)
class OverlayLabel:
    text: str
    x: float
    y: float
    z: float
    color: str
    abs_value: float


def result_overlay_labels(
    model: StructuralModel,
    result: AnalysisResult,
    result_type: str,
    unit: UnitSystem,
    *,
    scale_percent: int = 50,
    deformation_scale: float = 0.0,
) -> tuple[OverlayLabel, ...]:
    """Labels for the active 3D result type, or empty when that type has none."""
    builders = {
        "deformation": _deformation_labels,
        "displacement": _displacement_labels,
        "reaction": _reaction_labels,
        "axial": lambda m, r, u, **_: _force_labels(m, r, u, DiagramKind.AXIAL, scale_percent),
        "shear": lambda m, r, u, **_: _force_labels(m, r, u, DiagramKind.SHEAR, scale_percent),
        "moment": lambda m, r, u, **_: _force_labels(m, r, u, DiagramKind.MOMENT, scale_percent),
        "stress": _stress_labels,
    }
    builder = builders.get(result_type)
    if builder is None:
        return ()
    labels = builder(model, result, unit, deformation_scale=deformation_scale)
    return _capped(labels)


def _deformation_labels(
    model: StructuralModel,
    result: AnalysisResult,
    unit: UnitSystem,
    *,
    deformation_scale: float,
) -> list[OverlayLabel]:
    """One |U| per member, at midspan of the deformed chord - the number you
    look for on a deflected shape without opening Displacements.
    """
    labels: list[OverlayLabel] = []
    for element in model.elements.values():
        node_i = model.nodes.get(element.node_i)
        node_j = model.nodes.get(element.node_j)
        if node_i is None or node_j is None:
            continue
        mag_i = _translation(result, element.node_i)
        mag_j = _translation(result, element.node_j)
        peak = max(mag_i, mag_j)
        if peak <= 0.0:
            continue
        pi = _displaced(node_i, result, deformation_scale)
        pj = _displaced(node_j, result, deformation_scale)
        mid = tuple(0.5 * (pi[k] + pj[k]) for k in range(3))
        labels.append(
            OverlayLabel(
                f"Δ {peak:.4g} {unit.length}",
                mid[0],
                mid[1],
                mid[2],
                "#b4530a",
                peak,
            )
        )
    return labels


def _displacement_labels(
    model: StructuralModel,
    result: AnalysisResult,
    unit: UnitSystem,
    *,
    deformation_scale: float,
) -> list[OverlayLabel]:
    """|U| at every node that actually moved - nodal quantity, so it sits on
    the joint rather than the member span.
    """
    labels: list[OverlayLabel] = []
    for tag, node in model.nodes.items():
        magnitude = _translation(result, tag)
        if magnitude <= 0.0:
            continue
        x, y, z = _displaced(node, result, deformation_scale)
        labels.append(
            OverlayLabel(
                f"Δ {magnitude:.4g} {unit.length}",
                x,
                y,
                z,
                "#b4530a",
                magnitude,
            )
        )
    return labels


def _reaction_labels(
    model: StructuralModel,
    result: AnalysisResult,
    unit: UnitSystem,
    *,
    deformation_scale: float,
) -> list[OverlayLabel]:
    """Resultant support force at each restrained node. Components live in
    the reaction table; the overlay only needs the magnitude an engineer
    checks against the applied load.
    """
    del deformation_scale
    restrained = {
        boundary.node_tag for boundary in model.boundaries if any(boundary.restraints)
    }
    raw: list[tuple[int, float, float, float, float]] = []
    for tag in restrained:
        node = model.nodes.get(tag)
        node_result = result.node_results.get(tag)
        if node is None or node_result is None:
            continue
        values = (*node_result.reaction, 0.0, 0.0, 0.0)
        fx, fy, fz = float(values[0]), float(values[1]), float(values[2])
        magnitude = math.sqrt(fx * fx + fy * fy + fz * fz)
        raw.append((tag, node.x, node.y, node.z, magnitude))
    peak = max((item[4] for item in raw), default=0.0)
    labels: list[OverlayLabel] = []
    for _tag, x, y, z, magnitude in raw:
        if magnitude <= peak * _RELATIVE_NOISE:
            continue
        labels.append(
            OverlayLabel(f"R {magnitude:.4g} {unit.force}", x, y, z, "#0f766e", magnitude)
        )
    return labels


def _force_labels(
    model: StructuralModel,
    result: AnalysisResult,
    unit: UnitSystem,
    kind: DiagramKind,
    scale_percent: int,
) -> list[OverlayLabel]:
    """N / V / M at the ribbon ends, using the same stations the 3D diagram
    already drew so the number sits on the lobe it describes.
    """
    symbol = {DiagramKind.AXIAL: "N", DiagramKind.SHEAR: "V", DiagramKind.MOMENT: "M"}[kind]
    unit_text = unit.moment if kind == DiagramKind.MOMENT else unit.force
    labels: list[OverlayLabel] = []
    for strip in spatial_diagram_strips(model, result, kind, scale_percent):
        start, end = strip.end_values
        maximum = max(abs(start), abs(end), 1.0e-30)
        prefix = symbol
        if kind == DiagramKind.SHEAR:
            prefix = "Vy" if strip.color == "#7254a8" else "Vz"
        elif kind == DiagramKind.MOMENT:
            prefix = "Mz" if strip.color == "#7254a8" else "My"
        if math.isclose(start, end, rel_tol=1.0e-6, abs_tol=maximum * _RELATIVE_NOISE):
            if abs(start) <= maximum * _RELATIVE_NOISE:
                continue
            mid = len(strip.curve) // 2
            point = strip.curve[mid]
            labels.append(
                OverlayLabel(
                    f"{prefix} {start:.4g} {unit_text}",
                    point[0],
                    point[1],
                    point[2],
                    strip.color,
                    abs(start),
                )
            )
            continue
        for value, point in ((start, strip.curve[0]), (end, strip.curve[-1])):
            # Keep a printed 0 at the free end of a cantilever: that zero is
            # the answer, not noise. Noise-only strips never reach here
            # because spatial_diagram_strips already dropped them.
            labels.append(
                OverlayLabel(
                    f"{prefix} {value:.4g} {unit_text}",
                    point[0],
                    point[1],
                    point[2],
                    strip.color,
                    abs(value),
                )
            )
    return labels


def _stress_labels(
    model: StructuralModel,
    result: AnalysisResult,
    unit: UnitSystem,
    *,
    deformation_scale: float,
) -> list[OverlayLabel]:
    labels: list[OverlayLabel] = []
    for element in model.elements.values():
        element_result = result.element_results.get(element.tag)
        node_i = model.nodes.get(element.node_i)
        node_j = model.nodes.get(element.node_j)
        if element_result is None or node_i is None or node_j is None:
            continue
        peak = peak_member_stress(element, element_result, ndm=model.ndm)
        if peak is None or peak <= 0.0:
            continue
        pi = _displaced(node_i, result, deformation_scale)
        pj = _displaced(node_j, result, deformation_scale)
        mid = tuple(0.5 * (pi[k] + pj[k]) for k in range(3))
        labels.append(
            OverlayLabel(
                f"σ {peak:.4g} {unit.stress}",
                mid[0],
                mid[1],
                mid[2],
                "#b4530a",
                peak,
            )
        )
    return labels


def _translation(result: AnalysisResult, node_tag: int) -> float:
    node_result = result.node_results.get(node_tag)
    if node_result is None:
        return 0.0
    values = (*node_result.displacement, 0.0, 0.0, 0.0)
    ux, uy, uz = float(values[0]), float(values[1]), float(values[2])
    return math.sqrt(ux * ux + uy * uy + uz * uz)


def _displaced(node: Node, result: AnalysisResult, scale: float) -> tuple[float, float, float]:
    node_result = result.node_results.get(node.tag)
    values = (*(node_result.displacement if node_result is not None else ()), 0.0, 0.0, 0.0)
    return (
        node.x + float(values[0]) * scale,
        node.y + float(values[1]) * scale,
        node.z + float(values[2]) * scale,
    )


def _capped(labels: list[OverlayLabel]) -> tuple[OverlayLabel, ...]:
    if len(labels) <= _LABEL_CAP:
        return tuple(labels)
    ranked = sorted(labels, key=lambda item: item.abs_value, reverse=True)
    return tuple(ranked[:_LABEL_CAP])
