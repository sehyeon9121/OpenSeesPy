"""Render whole-frame N/V/M diagrams along member local axes."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.results.diagrams import (
    PLOT_SIDE,
    DiagramKind,
    MemberDiagram,
    member_diagrams,
)

DIAGRAM_INDEX = {
    DiagramKind.AXIAL: 0,
    DiagramKind.SHEAR: 1,
    DiagramKind.MOMENT: 2,
}

# Solver noise (e.g. 2e-12 on a member that carries no axial force) is relative to
# whatever the largest value in the diagram is, so an absolute cutoff either misses it
# on a small model or hides real values on a very large one.
_RELATIVE_NOISE_TOLERANCE = 1.0e-9


def _close(a: QPointF, b: QPointF) -> bool:
    return math.hypot(a.x() - b.x(), a.y() - b.y()) < 1.0e-9


def _sign_runs(diagram: MemberDiagram) -> list[tuple[int, int]]:
    """Index ranges over which the diagram keeps one sign."""
    runs: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(diagram.points)):
        previous = diagram.points[index - 1].value
        current = diagram.points[index].value
        if previous * current < 0.0:
            runs.append((start, index - 1))
            start = index
    runs.append((start, len(diagram.points) - 1))
    return runs


def _interior_peaks(diagram: MemberDiagram) -> list[int]:
    """Indices of every point strictly inside the member where the diagram
    genuinely turns (a local max or min - the slope changes sign there).

    Deliberately not gated on beating the two end values: a span whose
    support/end moments happen to be larger than its own interior sagging
    peak still needs that peak labelled - it is the actual maximum *within*
    that span, and the number an engineer reading that span looks for, not
    noise to hide just because some other point elsewhere is bigger. Member
    sampling already inserts each exact zero-shear (turning point) position
    as one of ``diagram.points`` (see build.py's ``_sample_positions`` /
    ``_shear_zero_crossings``), so this only has to notice it, not
    re-derive it.
    """
    if len(diagram.points) <= 2:
        return []
    peaks = []
    for index in range(1, len(diagram.points) - 1):
        previous_value = diagram.points[index - 1].value
        value = diagram.points[index].value
        next_value = diagram.points[index + 1].value
        if (value - previous_value) * (next_value - value) < 0.0:
            peaks.append(index)
    return peaks


class FrameDiagramRenderer:
    def render(
        self,
        scene: QGraphicsScene,
        model: StructuralModel,
        result: AnalysisResult,
        kind: DiagramKind,
        scale_percent: int,
        unit: str,
    ) -> float:
        diagrams = self._diagrams(result, kind)
        maximum = max(
            (abs(point.value) for diagram in diagrams.values() for point in diagram.points),
            default=0.0,
        )
        if maximum <= 1.0e-12:
            return 0.0

        x_values = [node.x for node in model.nodes.values()]
        y_values = [node.y for node in model.nodes.values()]
        model_span = max(
            max(x_values) - min(x_values),
            max(y_values) - min(y_values),
            1.0,
        )
        maximum_offset = model_span * 0.18 * max(scale_percent, 1) / 50.0
        signed_offset = maximum_offset * PLOT_SIDE[kind]

        # A branch member (e.g. a stem hanging off a beam) legitimately carries part of
        # the moment/shear away, so the diagram genuinely steps between the two collinear
        # halves at that shared node. Each half is still its own independent polygon (so
        # picking/tests keep working per element) but nothing was drawn *between* their
        # tips at that shared point, which reads as "the diagram broke" rather than "the
        # diagram stepped". Collect what touches each node here and bridge it afterwards.
        node_touches: dict[int, list[tuple[QPointF, QPointF, QPointF]]] = {}

        for element in model.elements.values():
            diagram = diagrams.get(element.tag)
            if diagram is None or len(diagram.points) < 2:
                continue
            node_i = model.nodes[element.node_i]
            node_j = model.nodes[element.node_j]
            start = QPointF(node_i.x, -node_i.y)
            end = QPointF(node_j.x, -node_j.y)
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length = math.hypot(dx, dy)
            if length <= 1.0e-12:
                continue
            normal = QPointF(-dy / length, dx / length)
            direction = QPointF(dx / length, dy / length)
            first_point = start + normal * (diagram.points[0].value / maximum * signed_offset)
            last_point = end + normal * (diagram.points[-1].value / maximum * signed_offset)
            node_touches.setdefault(element.node_i, []).append((direction, start, first_point))
            node_touches.setdefault(element.node_j, []).append((direction, end, last_point))
            self._draw_member(
                scene,
                element.tag,
                diagram,
                start,
                end,
                normal,
                maximum,
                signed_offset,
                unit,
                is_truss="truss" in element.element_type.lower(),
            )
        self._bridge_junctions(scene, node_touches)
        return abs(maximum_offset)

    @staticmethod
    def _bridge_junctions(
        scene: QGraphicsScene,
        node_touches: dict[int, list[tuple[QPointF, QPointF, QPointF]]],
    ) -> None:
        for touches in node_touches.values():
            for first in range(len(touches)):
                for second in range(first + 1, len(touches)):
                    direction_a, base, point_a = touches[first]
                    direction_b, _, point_b = touches[second]
                    collinear = abs(
                        direction_a.x() * direction_b.x() + direction_a.y() * direction_b.y()
                    ) > 0.999
                    if not collinear or _close(point_a, point_b):
                        continue
                    bridge = QPainterPath()
                    bridge.moveTo(base)
                    bridge.lineTo(point_a)
                    bridge.lineTo(point_b)
                    bridge.closeSubpath()
                    bridge_item = QGraphicsPathItem(bridge)
                    bridge_item.setPen(Qt.PenStyle.NoPen)
                    bridge_item.setBrush(QColor(113, 82, 171, 55))
                    bridge_item.setZValue(3.5)
                    bridge_item.setData(0, ("result_diagram_bridge",))
                    scene.addItem(bridge_item)
                    riser_pen = QPen(QColor("#7254a8"), 2.4)
                    riser_pen.setCosmetic(True)
                    riser = QGraphicsLineItem(point_a.x(), point_a.y(), point_b.x(), point_b.y())
                    riser.setPen(riser_pen)
                    riser.setZValue(5.0)
                    riser.setData(0, ("result_diagram_bridge",))
                    scene.addItem(riser)

    @staticmethod
    def _diagrams(
        result: AnalysisResult, kind: DiagramKind
    ) -> dict[int, MemberDiagram]:
        diagrams: dict[int, MemberDiagram] = {}
        index = DIAGRAM_INDEX[kind]
        for element in result.element_results.values():
            try:
                diagrams[element.element_tag] = member_diagrams(element)[index]
            except ValueError:
                continue
        return diagrams

    def _draw_member(
        self,
        scene: QGraphicsScene,
        element_tag: int,
        diagram: MemberDiagram,
        start: QPointF,
        end: QPointF,
        normal: QPointF,
        maximum: float,
        maximum_offset: float,
        unit: str,
        *,
        is_truss: bool = False,
    ) -> None:
        base_points: list[QPointF] = []
        diagram_points: list[QPointF] = []
        for point in diagram.points:
            base = self._interpolate(start, end, point.position)
            offset = point.value / maximum * maximum_offset
            base_points.append(base)
            diagram_points.append(base + normal * offset)

        fill_path = QPainterPath()
        fill_path.moveTo(base_points[0])
        for point in base_points[1:]:
            fill_path.lineTo(point)
        for point in reversed(diagram_points):
            fill_path.lineTo(point)
        fill_path.closeSubpath()

        fill_item = QGraphicsPathItem(fill_path)
        fill_item.setPen(Qt.PenStyle.NoPen)
        fill_item.setBrush(QColor(113, 82, 171, 55))
        fill_item.setZValue(4.0)
        fill_item.setData(0, ("result_diagram", element_tag))
        scene.addItem(fill_item)

        outline = QPainterPath()
        outline.moveTo(diagram_points[0])
        for point in diagram_points[1:]:
            outline.lineTo(point)
        outline_item = QGraphicsPathItem(outline)
        outline_pen = QPen(QColor("#7254a8"), 2.4)
        outline_pen.setCosmetic(True)
        outline_item.setPen(outline_pen)
        outline_item.setZValue(5.0)
        outline_item.setData(0, ("result_diagram_outline", element_tag))
        scene.addItem(outline_item)

        connector_pen = QPen(QColor("#9279bb"), 1.2, Qt.PenStyle.DashLine)
        connector_pen.setCosmetic(True)
        for base, point in zip(base_points, diagram_points, strict=True):
            connector = QGraphicsLineItem(base.x(), base.y(), point.x(), point.y())
            connector.setPen(connector_pen)
            connector.setZValue(4.5)
            connector.setData(0, ("result_diagram_connector", element_tag))
            scene.addItem(connector)

        self._draw_signs(scene, element_tag, diagram, base_points, diagram_points, maximum)
        self._draw_values(
            scene, element_tag, diagram, diagram_points, unit, maximum, is_truss=is_truss
        )

    def _draw_signs(
        self,
        scene: QGraphicsScene,
        element_tag: int,
        diagram: MemberDiagram,
        base_points: list[QPointF],
        diagram_points: list[QPointF],
        maximum: float,
    ) -> None:
        # One marker per stretch of constant sign; a sampled member has many points and
        # marking every segment would bury the diagram under symbols.
        noise_floor = maximum * _RELATIVE_NOISE_TOLERANCE
        for start, end in _sign_runs(diagram):
            middle = (start + end) // 2
            value = diagram.points[middle].value
            if abs(value) <= noise_floor:
                continue
            position = self._interpolate(base_points[middle], diagram_points[middle], 0.58)
            self._add_text(
                scene,
                "+" if value > 0.0 else "−",
                position,
                QColor("#2c1d43"),
                10,
                ("result_diagram_sign", element_tag),
            )

    def _draw_values(
        self,
        scene: QGraphicsScene,
        element_tag: int,
        diagram: MemberDiagram,
        diagram_points: list[QPointF],
        unit: str,
        maximum: float,
        *,
        is_truss: bool = False,
    ) -> None:
        first = diagram.points[0]
        last = diagram.points[-1]
        if math.isclose(first.value, last.value, rel_tol=1.0e-6, abs_tol=1.0e-9):
            labelled = [
                (first.value, self._interpolate(diagram_points[0], diagram_points[-1], 0.5))
            ]
        else:
            labelled = [
                (first.value, diagram_points[0]),
                (last.value, diagram_points[-1]),
            ]

        # On a sampled member every genuine turning point sits between the ends,
        # and each one is a number the engineer is looking for, so label them all.
        for peak in _interior_peaks(diagram):
            labelled.append((diagram.points[peak].value, diagram_points[peak]))

        # A truss member's axial force is what tells the user 인장/압축/0부재 — a
        # genuine zero-force member must still get a label (it's the answer, not
        # noise), unlike a near-zero reading on a frame member's diagram.
        truss_axial = is_truss and diagram.kind == DiagramKind.AXIAL
        noise_floor = maximum * _RELATIVE_NOISE_TOLERANCE
        for value, position in labelled:
            is_zero = abs(value) <= noise_floor
            if is_zero and not truss_axial:
                continue
            text = f"{value:.4g} {unit}"
            if truss_axial:
                text += " (0부재)" if is_zero else " (인장)" if value > 0.0 else " (압축)"
            self._add_text(
                scene,
                text,
                position,
                QColor("#66429a"),
                8,
                ("result_diagram_label", element_tag),
            )

    @staticmethod
    def _add_text(
        scene: QGraphicsScene,
        text: str,
        position: QPointF,
        color: QColor,
        size: int,
        identity: tuple[str, int],
    ) -> None:
        item = QGraphicsSimpleTextItem(text)
        font = QFont("Segoe UI", size)
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(font)
        item.setBrush(color)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setPos(position)
        item.setZValue(9.0)
        item.setData(0, identity)
        scene.addItem(item)

    @staticmethod
    def _interpolate(start: QPointF, end: QPointF, ratio: float) -> QPointF:
        return QPointF(
            start.x() + (end.x() - start.x()) * ratio,
            start.y() + (end.y() - start.y()) * ratio,
        )
