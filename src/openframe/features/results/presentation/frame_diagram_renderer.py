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
from openframe.features.results.diagrams import DiagramKind, MemberDiagram, member_diagrams

DIAGRAM_INDEX = {
    DiagramKind.AXIAL: 0,
    DiagramKind.SHEAR: 1,
    DiagramKind.MOMENT: 2,
}

# Which side of the member each quantity is plotted on, following the drawing conventions
# used in structural mechanics. ``normal`` below points along -local_y, so:
#   N, V  -> +1 plots a positive value on the +local_y side (above a beam, and on the
#            outer face of a column), matching the usual A.F.D / S.F.D layout.
#   M     -> -1 keeps the bending moment on the tension side (a sagging beam moment is
#            drawn below the member), which is the 인장측 작도 convention.
# Only the plotted offset is affected; printed values keep their true sign.
PLOT_SIDE = {
    DiagramKind.AXIAL: -1.0,
    DiagramKind.SHEAR: -1.0,
    DiagramKind.MOMENT: 1.0,
}


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
            self._draw_member(
                scene,
                element.tag,
                diagram,
                start,
                end,
                normal,
                maximum,
                maximum_offset * PLOT_SIDE[kind],
                unit,
            )
        return abs(maximum_offset)

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

        self._draw_signs(scene, element_tag, diagram, base_points, diagram_points)
        self._draw_values(scene, element_tag, diagram, diagram_points, unit)

    def _draw_signs(
        self,
        scene: QGraphicsScene,
        element_tag: int,
        diagram: MemberDiagram,
        base_points: list[QPointF],
        diagram_points: list[QPointF],
    ) -> None:
        for index in range(len(diagram.points) - 1):
            first = diagram.points[index]
            second = diagram.points[index + 1]
            if first.value * second.value < 0.0:
                fractions = (0.25, 0.75)
            else:
                fractions = (0.5,)
            for fraction in fractions:
                value = first.value + (second.value - first.value) * fraction
                if abs(value) <= 1.0e-12:
                    continue
                base = self._interpolate(base_points[index], base_points[index + 1], fraction)
                curve = self._interpolate(
                    diagram_points[index], diagram_points[index + 1], fraction
                )
                position = self._interpolate(base, curve, 0.58)
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
    ) -> None:
        first = diagram.points[0]
        last = diagram.points[-1]
        if math.isclose(first.value, last.value, rel_tol=1.0e-6, abs_tol=1.0e-9):
            positions = ((first.value, self._interpolate(diagram_points[0], diagram_points[-1], 0.5)),)
        else:
            positions = ((first.value, diagram_points[0]), (last.value, diagram_points[-1]))
        for value, position in positions:
            if abs(value) <= 1.0e-12:
                continue
            self._add_text(
                scene,
                f"{value:.4g} {unit}",
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
