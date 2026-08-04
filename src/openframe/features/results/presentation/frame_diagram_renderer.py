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

# Solver noise (e.g. 2e-12 on a member that carries no axial force) is relative to
# whatever the largest value in the diagram is, so an absolute cutoff either misses it
# on a small model or hides real values on a very large one.
_RELATIVE_NOISE_TOLERANCE = 1.0e-9


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


def _interior_peak_index(diagram: MemberDiagram) -> int | None:
    """Index of the largest value strictly inside the member, if it beats both ends."""
    if len(diagram.points) <= 2:
        return None
    end_peak = max(abs(diagram.points[0].value), abs(diagram.points[-1].value))
    interior = range(1, len(diagram.points) - 1)
    candidate = max(interior, key=lambda index: abs(diagram.points[index].value))
    if abs(diagram.points[candidate].value) <= end_peak * (1.0 + 1.0e-9):
        return None
    return candidate


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

        self._draw_signs(scene, element_tag, diagram, base_points, diagram_points, maximum)
        self._draw_values(scene, element_tag, diagram, diagram_points, unit, maximum)

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

        # On a sampled member the peak sits between the ends, and it is the number the
        # engineer is looking for, so label it as well.
        peak = _interior_peak_index(diagram)
        if peak is not None:
            labelled.append((diagram.points[peak].value, diagram_points[peak]))

        noise_floor = maximum * _RELATIVE_NOISE_TOLERANCE
        for value, position in labelled:
            if abs(value) <= noise_floor:
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
