"""Scale-independent nodal force and moment arrows."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, UnitSystem


class NodalLoadItem(QGraphicsItem):
    def __init__(
        self,
        node_tag: int,
        values: tuple[float, ...],
        unit_system: UnitSystem = DEFAULT_UNIT_SYSTEM,
    ) -> None:
        super().__init__()
        self.node_tag = node_tag
        padded_values = (*values, 0.0, 0.0, 0.0)
        self.fx = float(padded_values[0])
        self.fy = float(padded_values[1])
        self.mz = float(padded_values[2])
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setZValue(5.0)
        self.setData(0, ("load", node_tag))
        self.set_unit_system(unit_system)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.unit_system = unit_system
        self.setToolTip(
            f"Node {self.node_tag} | Fx={self.fx:g} {unit_system.force} | "
            f"Fy={self.fy:g} {unit_system.force} | "
            f"Mz={self.mz:g} {unit_system.moment}"
        )
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-125.0, -105.0, 250.0, 210.0)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        load_color = QColor("#e5484d")
        pen = QPen(load_color, 2.4)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(load_color)

        if abs(self.fx) > 1.0e-12:
            self._draw_component_arrow(
                painter,
                direction_x=1.0 if self.fx > 0.0 else -1.0,
                direction_y=0.0,
                label=f"Fx {self.fx:g} {self.unit_system.force}",
            )
        if abs(self.fy) > 1.0e-12:
            # Model +Y is upward while screen +Y is downward.
            self._draw_component_arrow(
                painter,
                direction_x=0.0,
                direction_y=-1.0 if self.fy > 0.0 else 1.0,
                label=f"Fy {self.fy:g} {self.unit_system.force}",
            )
        if abs(self.mz) > 1.0e-12:
            self._draw_moment(painter)

    def _draw_component_arrow(
        self,
        painter: QPainter,
        *,
        direction_x: float,
        direction_y: float,
        label: str,
    ) -> None:
        arrow_length = 54.0
        tail = QPointF(-direction_x * arrow_length, -direction_y * arrow_length)
        tip = QPointF(0.0, 0.0)
        painter.drawLine(tail, tip)

        perpendicular_x = -direction_y
        perpendicular_y = direction_x
        head_length = 11.0
        head_width = 5.5
        left = QPointF(
            -direction_x * head_length + perpendicular_x * head_width,
            -direction_y * head_length + perpendicular_y * head_width,
        )
        right = QPointF(
            -direction_x * head_length - perpendicular_x * head_width,
            -direction_y * head_length - perpendicular_y * head_width,
        )
        arrow_head = QPainterPath()
        arrow_head.moveTo(tip)
        arrow_head.lineTo(left)
        arrow_head.lineTo(right)
        arrow_head.closeSubpath()
        painter.drawPath(arrow_head)

        label_offset = QPointF(6.0, -7.0)
        self._draw_label(painter, label, tail + label_offset)

    def _draw_moment(self, painter: QPainter) -> None:
        arc_rect = QRectF(-24.0, -24.0, 48.0, 48.0)
        if self.mz > 0:
            painter.drawArc(arc_rect, -30 * 16, 275 * 16)
            tip = QPointF(19.0, -14.0)
            first = QPointF(20.0, -4.0)
            second = QPointF(10.0, -11.0)
        else:
            painter.drawArc(arc_rect, 30 * 16, -275 * 16)
            tip = QPointF(19.0, 14.0)
            first = QPointF(20.0, 4.0)
            second = QPointF(10.0, 11.0)
        arrow_head = QPainterPath()
        arrow_head.moveTo(tip)
        arrow_head.lineTo(first)
        arrow_head.lineTo(second)
        arrow_head.closeSubpath()
        painter.drawPath(arrow_head)
        self._draw_label(
            painter,
            f"Mz {self.mz:g} {self.unit_system.moment}",
            QPointF(28.0, 5.0),
        )

    def _draw_label(self, painter: QPainter, text: str, position: QPointF) -> None:
        painter.save()
        painter.setPen(QColor("#c9343b"))
        painter.setFont(QFont("Malgun Gothic", 8))
        painter.drawText(position, text)
        painter.restore()
