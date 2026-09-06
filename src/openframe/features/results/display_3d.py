"""3D display quantities shared by the canvas and the numeric inspector.

Display projections never alter the solver's result. Colours encode absolute
magnitudes; scalar labels and extrema retain their signed component values.
"""

import math
from dataclasses import dataclass, field, replace

from openframe.core.domain import (
    AnalysisResult,
    NodeResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.deformation import deflected_polyline
from openframe.features.results.diagrams import (
    DiagramKind,
    member_diagrams_3d,
    spatial_diagram_strips,
)
from openframe.features.results.magnitudes import member_magnitudes, member_station_magnitudes

SHAPE_TYPES = {
    "deformation",
    "displacement",
    "mode_shapes",
    "buckling_modes",
    "mechanism_modes",
}
FORCE_TYPES = {"axial", "shear", "moment"}
COMPONENTS = {
    "deformation": ("DXYZ", "DX", "DY", "DZ", "DXY", "DYZ", "DXZ"),
    "displacement": ("DXYZ", "DX", "DY", "DZ", "DXY", "DYZ", "DXZ"),
    "reaction": ("FXYZ", "FX", "FY", "FZ", "MX", "MY", "MZ"),
    "axial": ("N",),
    "shear": ("Vy + Vz", "Vy", "Vz"),
    "moment": ("My + Mz", "My", "Mz"),
    "stress": ("|σ| envelope",),
}
for _kind in ("mode_shapes", "buckling_modes", "mechanism_modes"):
    COMPONENTS[_kind] = COMPONENTS["deformation"]


@dataclass
class DisplayOptions:
    component: str = "DXYZ"
    deformed: bool = True
    undeformed: bool = True
    scale_mode: str = "auto"
    scale: float = 30.0
    diagram_scale: int = 50
    values: bool = False
    extrema: bool = True
    legend: bool = True
    arrows: bool = True
    node_numbers: bool = False
    member_numbers: bool = False
    mode_index: int = 0


@dataclass
class DisplayData:
    result: AnalysisResult
    scale: float = 0.0
    unit: str = ""
    # Location strings name nodes, members or specific diagram ends.
    values: dict[str, float] = field(default_factory=dict)
    positions: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    member_values: dict[int, float] | None = None
    stations: dict[int, tuple[float, ...]] | None = None
    diagrams: list[dict] = field(default_factory=list)
    labels: list[dict] = field(default_factory=list)
    polylines: dict[int, list[tuple[float, float, float]]] = field(default_factory=dict)
    reactions: dict[int, tuple[float, ...]] | None = None
    context: str = ""
    legend: bool = True


def active_result(result: AnalysisResult, kind: str, index: int) -> tuple[AnalysisResult, str]:
    if kind == "mode_shapes":
        modes = result.mode_shapes
        if not 0 <= index < len(modes):
            return replace(result, node_results={}, element_results={}), "No mode data"
        mode = modes[index]
        return replace(result, node_results=mode.node_results, element_results={}), (
            f"Mode {mode.mode_number} · {mode.frequency_hz:.5g} Hz · T {mode.period:.5g} s\n"
            "Eigenvector · arbitrary amplitude"
        )
    if kind == "buckling_modes":
        modes = result.buckling_modes
        if not 0 <= index < len(modes):
            return replace(result, node_results={}, element_results={}), "No buckling data"
        mode = modes[index]
        return replace(result, node_results=mode.normalized_node_results, element_results={}), (
            f"Mode {mode.mode_number} · λ {mode.buckling_load_factor:.6g}\n"
            "Normalized eigenvector · arbitrary amplitude"
        )
    if kind == "mechanism_modes":
        diagnostic = result.instability_diagnostic
        modes = diagnostic.modes if diagnostic is not None else ()
        if not 0 <= index < len(modes):
            return replace(result, node_results={}, element_results={}), "No mechanism data"
        mode = modes[index]
        nodes = {tag: NodeResult(tag, displacement=v) for tag, v in mode.mode_shape.items()}
        return replace(result, node_results=nodes, element_results={}), (
            f"Mechanism {mode.mode_number} · relative shape\n" + ", ".join(mode.dominant_dofs)
        )
    return result, ""


def translation_axes(component: str) -> tuple[int, ...]:
    return tuple(i for i, axis in enumerate("XYZ") if axis in component)


def build_display(
    model: StructuralModel,
    source: AnalysisResult,
    kind: str,
    options: DisplayOptions,
    unit: UnitSystem,
) -> DisplayData:
    result, context = active_result(source, kind, options.mode_index)
    data = DisplayData(result, context=context)
    data.legend = options.legend
    shape = kind in SHAPE_TYPES or kind == "overview"
    axes = translation_axes(options.component) if shape else (0, 1, 2)
    if shape:
        # For a component-projected shape project the final spatial curve too;
        # projecting rotations in global coordinates before interpolation is wrong.
        nodes = {}
        for tag, node_result in result.node_results.items():
            raw = (*node_result.displacement, 0.0, 0.0, 0.0)
            projected = tuple(raw[i] if i in axes else 0.0 for i in range(3))
            nodes[tag] = replace(node_result, displacement=projected + node_result.displacement[3:])
            value = raw[axes[0]] if len(axes) == 1 else math.hypot(*(raw[i] for i in axes))
            data.values[f"Node {tag}"] = value
        data.result = replace(result, node_results=nodes)
        data.unit = (
            unit.length if kind in {"overview", "deformation", "displacement"} else "relative"
        )
        if source.displacement_stiffness.value == "unit_stiffness":
            data.unit = "relative"
    if shape or kind == "stress":
        peak = max(
            (math.hypot(*nr.displacement[:3]) for nr in data.result.node_results.values()),
            default=0.0,
        )
        span = (
            max(
                (
                    max(getattr(n, a) for n in model.nodes.values())
                    - min(getattr(n, a) for n in model.nodes.values())
                    for a in "xyz"
                ),
                default=1.0,
            )
            if model.nodes
            else 1.0
        )
        data.scale = (
            (0.08 * span / peak if peak > 1e-15 else 1.0)
            if options.scale_mode == "auto"
            else (1.0 if options.scale_mode == "real" else options.scale)
        )
        if not options.deformed or kind == "overview":
            data.scale = 0.0
        for tag, element in model.elements.items():
            stations = deflected_polyline(model, result, tag, data.scale)
            base = deflected_polyline(model, result, tag, 0.0)
            if len(stations) >= 3 and len(base) == len(stations):
                data.polylines[tag] = [
                    tuple(p[i] if i in axes else b[i] for i in range(3))
                    for p, b in zip(stations, base)
                ]
    for tag, node in model.nodes.items():
        nr = data.result.node_results.get(tag)
        disp = (*(nr.displacement if nr else ()), 0.0, 0.0, 0.0)
        data.positions[f"Node {tag}"] = (
            node.x + disp[0] * data.scale,
            node.y + disp[1] * data.scale,
            node.z + disp[2] * data.scale,
        )
    if kind == "reaction":
        data.unit = unit.moment if options.component.startswith("M") else unit.force
        data.reactions = {}
        restrained = {b.node_tag for b in model.boundaries if any(b.restraints)}
        indices = {"FX": 0, "FY": 1, "FZ": 2, "MX": 3, "MY": 4, "MZ": 5}
        for tag in sorted(restrained):
            nr = result.node_results.get(tag)
            if nr is None or not nr.reaction:
                continue
            raw = (*nr.reaction, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            index = indices.get(options.component)
            data.values[f"Node {tag}"] = math.hypot(*raw[:3]) if index is None else raw[index]
            data.reactions[tag] = tuple(
                raw[i] if (i < 3 if index is None else i == index) else 0.0 for i in range(6)
            )
        data.result = replace(
            result,
            node_results={
                tag: replace(node_result, displacement=tuple(0.0 for _ in node_result.displacement))
                for tag, node_result in result.node_results.items()
            },
        )
    if kind in FORCE_TYPES:
        component = {
            "N": "axial",
            "Vy": "shear_y",
            "Vz": "shear_z",
            "My": "moment_y",
            "Mz": "moment_z",
        }.get(options.component, "all")
        data.unit = unit.moment if kind == "moment" else unit.force
        data.member_values = {}
        for strip in spatial_diagram_strips(
            model, result, DiagramKind(kind), options.diagram_scale, component=component
        ):
            data.diagrams.append(
                {"color": strip.color, "axis": list(strip.axis), "curve": list(strip.curve)}
            )
            for end, value, position in zip(
                ("i", "j"), strip.end_values, (strip.curve[0], strip.curve[-1])
            ):
                key = f"Element {strip.element_tag} · {strip.component} · {end}"
                data.values[key], data.positions[key] = value, position
            data.member_values[strip.element_tag] = max(
                data.member_values.get(strip.element_tag, 0.0), *(abs(v) for v in strip.end_values)
            )
        # Include genuine zero results in the inspector even when no ribbon is drawn.
        attrs = {
            "axial": ("axial",),
            "shear": ("shear_y", "shear_z"),
            "moment": ("moment_y", "moment_z"),
        }[kind]
        for tag, er in result.element_results.items():
            try:
                bundle = member_diagrams_3d(er)
            except ValueError:
                continue
            for attr in attrs:
                if component != "all" and component != attr:
                    continue
                points = getattr(bundle, attr).points
                for end, point in zip(("i", "j"), (points[0], points[-1])):
                    key = f"Element {tag} · {attr} · {end}"
                    data.values[key] = point.value
                    element = model.elements.get(tag)
                    if element:
                        data.positions.setdefault(
                            key,
                            data.positions.get(
                                f"Node {element.node_i if end == 'i' else element.node_j}",
                                (0, 0, 0),
                            ),
                        )
    if kind == "stress":
        data.unit = unit.stress
        data.member_values = member_magnitudes(model, result, kind)
        data.stations = member_station_magnitudes(model, result, kind)
        data.context = "Elastic normal stress |σ| envelope\n|N/A| + bending fibre contributions"
        for tag, value in data.member_values.items():
            data.values[f"Element {tag}"] = value
            element = model.elements.get(tag)
            if element:
                pi, pj = (
                    data.positions[f"Node {element.node_i}"],
                    data.positions[f"Node {element.node_j}"],
                )
                data.positions[f"Element {tag}"] = tuple((a + b) / 2 for a, b in zip(pi, pj))
    if not data.context:
        system = "Local" if kind in FORCE_TYPES else "Global"
        data.context = f"{system} component · {options.component}"
    visible = (
        dict(sorted(data.values.items(), key=lambda kv: abs(kv[1]), reverse=True)[:80])
        if options.values
        else {}
    )
    extrema = {}
    if data.values and options.extrema:
        extrema[min(data.values, key=data.values.get)] = "MIN"
        extrema[max(data.values, key=data.values.get)] = "MAX"
        visible.update({key: data.values[key] for key in extrema})
    for key, value in visible.items():
        if key not in data.positions:
            continue
        x, y, z = data.positions[key]
        data.labels.append(
            {
                "text": f"{extrema.get(key, '')} {key}: {value:.5g} {data.unit}".strip(),
                "x": x,
                "y": y,
                "z": z,
                "color": "#0f766e" if kind == "reaction" else "#b4530a",
            }
        )
    return data
