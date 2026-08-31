"""World-space N/V/M diagram geometry for a 3D frame.

Qt-free on purpose: the result viewport asks for strips of structural (x, y, z)
points, and the Quick3D bridge turns those into cylinders/cubes. Plotting side
matches the 2D ``FrameDiagramRenderer`` (tension-side moment, shear opposite
axial) so a beam that looks familiar in XY is not mirrored when the same
member is viewed in 3D.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from openframe.core.domain import AnalysisResult, Element, StructuralModel
from openframe.core.domain.geometric_transform import (
    auto_reference_vector,
    local_y_z_axes,
    rotate_about_axis,
)
from openframe.features.results.diagrams.base import (
    PLOT_SIDE,
    DiagramKind,
    DiagramPoint,
    MemberDiagram,
)
from openframe.features.results.diagrams.build import max_abs_value, member_diagrams_3d

#: Even spacing along a two-point (end-force) diagram. A linear moment from
#: -PL to 0 is a triangle; without interior stations a single cube would
#: draw it as a rectangle of the average height.
_SPATIAL_SAMPLES = 8

#: Same visual amplitude rule as the 2D renderer: 18% of the model span at
#: the slider's default 50%.
_SPAN_FRACTION = 0.18
_DEFAULT_SCALE_PERCENT = 50.0

_Y_PLANE_COLOR = "#7254a8"
_Z_PLANE_COLOR = "#3d7ea6"

_TRUSS_TYPES = frozenset({"truss", "corottruss"})

#: (attribute on MemberDiagrams3D, local axis name, 2D PLOT_SIDE kind, color)
_COMPONENTS: dict[DiagramKind, tuple[tuple[str, str, DiagramKind, str], ...]] = {
    DiagramKind.AXIAL: (("axial", "y", DiagramKind.AXIAL, _Y_PLANE_COLOR),),
    DiagramKind.SHEAR: (
        ("shear_y", "y", DiagramKind.SHEAR, _Y_PLANE_COLOR),
        ("shear_z", "z", DiagramKind.SHEAR, _Z_PLANE_COLOR),
    ),
    DiagramKind.MOMENT: (
        # Mz is the 2D in-plane analog (plotted in the local-x/y plane).
        ("moment_z", "y", DiagramKind.MOMENT, _Y_PLANE_COLOR),
        ("moment_y", "z", DiagramKind.MOMENT, _Z_PLANE_COLOR),
    ),
}


@dataclass(frozen=True, slots=True)
class SpatialDiagramStrip:
    """One plotted quantity on one member, in structural coordinates.

    ``axis`` is the member centreline; ``curve`` is the offset diagram edge.
    Same length, station-aligned. The viewport draws a filled ribbon between
    them plus an outline along ``curve``.
    """

    element_tag: int
    color: str
    axis: tuple[tuple[float, float, float], ...]
    curve: tuple[tuple[float, float, float], ...]
    #: Diagram values at the member ends (i, j) - the numbers a MIDAS-style
    #: overlay labels on the ribbon. Interior samples exist only to tessellate
    #: the fill; the engineer reads the two ends (and a single mid label when
    #: they agree).
    end_values: tuple[float, float]


def spatial_diagram_strips(
    model: StructuralModel,
    result: AnalysisResult,
    kind: DiagramKind,
    scale_percent: int,
) -> tuple[SpatialDiagramStrip, ...]:
    """Build every non-zero diagram strip for ``kind`` (axial / shear / moment)."""
    components = _COMPONENTS.get(kind)
    if components is None or not model.elements:
        return ()

    collected: list[tuple[Element, MemberDiagram, str, DiagramKind, str]] = []
    diagrams: list[MemberDiagram] = []
    for element in model.elements.values():
        element_result = result.element_results.get(element.tag)
        if element_result is None:
            continue
        try:
            bundle = member_diagrams_3d(element_result)
        except ValueError:
            continue
        is_truss = element.element_type.lower() in _TRUSS_TYPES
        for attribute, axis_name, plot_kind, color in components:
            if is_truss and attribute != "axial":
                continue
            diagram = getattr(bundle, attribute)
            collected.append((element, diagram, axis_name, plot_kind, color))
            diagrams.append(diagram)

    maximum = max_abs_value(diagrams)
    if maximum <= 1.0e-12:
        return ()

    maximum_offset = (
        _model_span(model) * _SPAN_FRACTION * max(scale_percent, 1) / _DEFAULT_SCALE_PERCENT
    )
    strips: list[SpatialDiagramStrip] = []
    for element, diagram, axis_name, plot_kind, color in collected:
        strip = _strip_for_member(
            model, element, diagram, axis_name, plot_kind, maximum, maximum_offset, color
        )
        if strip is not None:
            strips.append(strip)
    return tuple(strips)


def _strip_for_member(
    model: StructuralModel,
    element: Element,
    diagram: MemberDiagram,
    axis_name: str,
    kind: DiagramKind,
    maximum: float,
    maximum_offset: float,
    color: str,
) -> SpatialDiagramStrip | None:
    frame = _member_frame(model, element)
    if frame is None:
        return None
    origin, direction, local_y, local_z, length = frame
    if max(abs(point.value) for point in diagram.points) <= maximum * 1.0e-9:
        return None

    plot_axis = local_y if axis_name == "y" else local_z
    # Offset = -PLOT_SIDE * local axis: positive shear on the +axis side
    # (Vy along +local y, Vz along +local z), hogging moment on the +axis
    # side (tension-side 작도 - sagging hangs the other way). The leading
    # minus is the 3D equivalent of the 2D screen normal being -local_y.
    plot_side = PLOT_SIDE[kind]
    plot_direction = tuple(-plot_side * component for component in plot_axis)

    stations = _sampled_stations(diagram)
    axis_points: list[tuple[float, float, float]] = []
    curve_points: list[tuple[float, float, float]] = []
    for station in stations:
        along = station.position * length
        base = tuple(origin[index] + direction[index] * along for index in range(3))
        offset = station.value / maximum * maximum_offset
        curve = tuple(base[index] + plot_direction[index] * offset for index in range(3))
        axis_points.append(base)
        curve_points.append(curve)
    return SpatialDiagramStrip(
        element.tag,
        color,
        tuple(axis_points),
        tuple(curve_points),
        (diagram.points[0].value, diagram.points[-1].value),
    )


def _member_frame(
    model: StructuralModel, element: Element
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    float,
] | None:
    """``(origin, axis, local_y, local_z, length)`` in the same triad OpenSees
    used when it reported ``localForce``. Otherwise Vy is drawn in the Mz
    plane (and vice versa) on any imported member whose ``geomTransf`` vecxz
    is not the auto Z/X fallback - ``cantilever_frame_3d`` is the exhibit
    (vertical member, script vecxz = +Y, auto = +X, 90° roll).
    """
    node_i = model.nodes.get(element.node_i)
    node_j = model.nodes.get(element.node_j)
    if node_i is None or node_j is None:
        return None
    origin = (node_i.x, node_i.y, node_i.z)
    delta = (node_j.x - node_i.x, node_j.y - node_i.y, node_j.z - node_i.z)
    length = math.sqrt(sum(component * component for component in delta))
    if length <= 1.0e-9:
        return None
    axis = tuple(component / length for component in delta)
    reference = _analysis_vecxz(model, element, axis)
    local_y, local_z = local_y_z_axes(axis, reference)
    return origin, axis, local_y, local_z, length


def _analysis_vecxz(
    model: StructuralModel,
    element: Element,
    axis: tuple[float, float, float],
) -> tuple[float, float, float]:
    """The ``vecxz`` that actually oriented this member in the analysis.

    Imported 3D beams store it on ``model.geometric_transforms`` (the
    script's ``ops.geomTransf`` vector). Canvas-built members have no
    transf tag and were solved with ``auto_reference_vector`` plus
    ``local_axis_angle``, so that remains the fallback. Do not rotate the
    imported vector by ``local_axis_angle`` - that angle is already baked
    into the stored vecxz, or unused (0) on imports.
    """
    if element.transf_tag is not None:
        transform = model.geometric_transforms.get(element.transf_tag)
        if transform is not None and transform.vector_xz is not None:
            return transform.vector_xz
    reference = auto_reference_vector(axis)
    if element.local_axis_angle:
        return rotate_about_axis(reference, axis, math.radians(element.local_axis_angle))
    return reference


def _sampled_stations(diagram: MemberDiagram) -> tuple[DiagramPoint, ...]:
    """Keep the true end (and any interior) values, and fill in even stations
    so a two-point linear diagram still tessellates as a triangle / trapezoid.
    """
    if len(diagram.points) < 2:
        return diagram.points
    positions = [index / _SPATIAL_SAMPLES for index in range(_SPATIAL_SAMPLES + 1)]
    for point in diagram.points:
        positions.append(point.position)
    start, end = diagram.points[0], diagram.points[-1]
    if start.value * end.value < 0.0:
        span = abs(start.value) + abs(end.value)
        if span > 1.0e-15:
            positions.append(abs(start.value) / span)
    unique = sorted({round(position, 12) for position in positions if 0.0 <= position <= 1.0})
    return tuple(DiagramPoint(position, _value_at(diagram, position)) for position in unique)


def _value_at(diagram: MemberDiagram, position: float) -> float:
    points = diagram.points
    if position <= points[0].position:
        return points[0].value
    for previous, current in pairwise(points):
        if position <= current.position:
            span = current.position - previous.position
            if span <= 1.0e-15:
                return current.value
            blend = (position - previous.position) / span
            return previous.value + blend * (current.value - previous.value)
    return points[-1].value


def _model_span(model: StructuralModel) -> float:
    xs = [node.x for node in model.nodes.values()]
    ys = [node.y for node in model.nodes.values()]
    zs = [node.z for node in model.nodes.values()]
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1.0)
