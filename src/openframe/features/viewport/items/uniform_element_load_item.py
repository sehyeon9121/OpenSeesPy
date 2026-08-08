"""Uniform element-load arrows drawn along a 2D member."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, LoadCaseKind, UniformElementLoad, UnitSystem

LOAD_CASE_COLORS = {
    LoadCaseKind.DEAD: "#2563eb",
    LoadCaseKind.LIVE: "#16a34a",
    LoadCaseKind.SEISMIC: "#f97316",
    LoadCaseKind.WIND: "#8b5cf6",
    LoadCaseKind.OTHER: "#64748b",
    LoadCaseKind.UNCLASSIFIED: "#f59e0b",
}


class UniformElementLoadItem(QGraphicsItem):
    """Draw local-axis ``beamUniform`` components over their loaded member."""

    def __init__(
        self,
        load: UniformElementLoad,
        start: QPointF,
        end: QPointF,
        unit_system: UnitSystem = DEFAULT_UNIT_SYSTEM,
        load_scale: float = 1.0,
    ) -> None:
        super().__init__()
        self.load = load
        self.start = start
        self.end = end
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        self.length = max(math.hypot(dx, dy), 1.0e-9)
        self.tangent = QPointF(dx / self.length, dy / self.length)
        self.local_y = QPointF(self.tangent.y(), -self.tangent.x())
        self.load_scale = min(1.0, max(0.45, float(load_scale)))
        self.arrow_length = max(self.length * 0.16, 0.25) * self.load_scale
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(6.0)
        self.setData(0, ("element_load", load.element_tag))
        self.set_unit_system(unit_system)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.unit_system = unit_system
        load_unit = f"{unit_system.force}/{unit_system.length}"
        self.setToolTip(
            f"{self.load.case_type.value} | Pattern {self.load.pattern_tag or '-'} | "
            f"Element {self.load.element_tag} | Uniform load | "
            f"Wx={self.load.wx:g} {load_unit} | Wy={self.load.wy:g} {load_unit}"
        )
        self.update()

    def boundingRect(self) -> QRectF:
        margin = self.arrow_length * 1.7
        return QRectF(self.start, self.end).normalized().adjusted(-margin, -margin, margin, margin)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if abs(self.load.wy) > 1.0e-12:
            color = (
                "#f59e0b"
                if self.load.case_type == LoadCaseKind.UNCLASSIFIED
                else LOAD_CASE_COLORS[self.load.case_type]
            )
            self._set_component_style(painter, QColor(color))
            direction = self._scaled(self.local_y, 1.0 if self.load.wy > 0 else -1.0)
            self._draw_arrow_row(painter, direction, self.load.wy, "Wy")
        if abs(self.load.wx) > 1.0e-12:
            color = (
                "#8b5cf6"
                if self.load.case_type == LoadCaseKind.UNCLASSIFIED
                else LOAD_CASE_COLORS[self.load.case_type]
            )
            self._set_component_style(painter, QColor(color))
            direction = self._scaled(self.tangent, 1.0 if self.load.wx > 0 else -1.0)
            self._draw_arrow_row(painter, direction, self.load.wx, "Wx")

    def _set_component_style(self, painter: QPainter, color: QColor) -> None:
        pen = QPen(color, 2.0)
        pen.setCosmetic(True)
        if self.isSelected():
            pen.setColor(color.darker(135))
            pen.setWidthF(2.8)
        painter.setPen(pen)
        painter.setBrush(pen.color())

    def _draw_arrow_row(
        self,
        painter: QPainter,
        direction: QPointF,
        magnitude: float,
        component: str,
    ) -> None:
        fractions = (0.06, 0.21, 0.36, 0.50, 0.64, 0.79, 0.94)
        tails: list[QPointF] = []
        for fraction in fractions:
            tip = self._point_on_member(fraction)
            tail = tip - self._scaled(direction, self.arrow_length)
            tails.append(tail)
            painter.drawLine(tail, tip)
            self._draw_arrow_head(painter, tip, direction)
        painter.drawLine(tails[0], tails[-1])

        load_unit = f"{self.unit_system.force}/{self.unit_system.length}"
        label = f"{component} {magnitude:g} {load_unit}"
        label_scene_position = tails[len(tails) // 2] - self._scaled(direction, self.length * 0.035)
        label_device_position = painter.worldTransform().map(label_scene_position)
        painter.save()
        painter.resetTransform()
        painter.setPen(painter.pen().color())
        font = QFont("Malgun Gothic")
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        label_width = painter.fontMetrics().horizontalAdvance(label)
        painter.drawText(label_device_position + QPointF(-label_width / 2.0, -5.0), label)
        painter.restore()

    def _draw_arrow_head(self, painter: QPainter, tip: QPointF, direction: QPointF) -> None:
        head_length = max(self.length * 0.022, 0.035)
        head_width = head_length * 0.48
        perpendicular = QPointF(-direction.y(), direction.x())
        base = tip - self._scaled(direction, head_length)
        left = base + self._scaled(perpendicular, head_width)
        right = base - self._scaled(perpendicular, head_width)
        path = QPainterPath()
        path.moveTo(tip)
        path.lineTo(left)
        path.lineTo(right)
        path.closeSubpath()
        painter.drawPath(path)

    def _point_on_member(self, fraction: float) -> QPointF:
        return QPointF(
            self.start.x() + (self.end.x() - self.start.x()) * fraction,
            self.start.y() + (self.end.y() - self.start.y()) * fraction,
        )

    @staticmethod
    def _scaled(vector: QPointF, scale: float) -> QPointF:
        return QPointF(vector.x() * scale, vector.y() * scale)
