"""Displacement vector drawn from a node's original position to its deformed one."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, UnitSystem
from openframe.features.results.deformation import NodalDisplacement

VECTOR_COLOR = "#b4530a"
PEAK_COLOR = "#e5484d"


class NodeDisplacementItem(QGraphicsItem):
    """Arrow from the undeformed node to where the analysis moved it.

    The item is positioned at the undeformed node in scene coordinates, while the
    arrow itself is expressed in screen pixels so it stays readable at any zoom.
    """

    def __init__(
        self,
        displacement: NodalDisplacement,
        screen_offset: QPointF,
        *,
        is_peak: bool = False,
        show_label: bool = True,
        unit_system: UnitSystem = DEFAULT_UNIT_SYSTEM,
    ) -> None:
        super().__init__()
        self.displacement = displacement
        self._offset = screen_offset
        self._is_peak = is_peak
        self._show_label = show_label
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(9.0)
        self.setData(0, ("result_node_displacement", displacement.node_tag))
        self.set_unit_system(unit_system)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.unit_system = unit_system
        item = self.displacement
        self.setToolTip(
            f"Node {item.node_tag} | UX={item.ux:.6g} {unit_system.length} | "
            f"UY={item.uy:.6g} {unit_system.length} | "
            f"|U|={item.magnitude:.6g} {unit_system.length}"
        )
        self.update()

    def boundingRect(self) -> QRectF:
        reach = max(abs(self._offset.x()), abs(self._offset.y())) + 130.0
        return QRectF(-reach, -reach, 2 * reach, 2 * reach)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(PEAK_COLOR if self._is_peak else VECTOR_COLOR)
        pen = QPen(color, 2.6 if self._is_peak else 1.8)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(color)

        tip = self._offset
        length = math.hypot(tip.x(), tip.y())
        if length < 1.0e-9:
            return
        painter.drawLine(QPointF(0.0, 0.0), tip)

        direction_x = tip.x() / length
        direction_y = tip.y() / length
        head_length = min(11.0, length)
        head_width = head_length * 0.45
        arrow_head = QPainterPath()
        arrow_head.moveTo(tip)
        arrow_head.lineTo(
            QPointF(
                tip.x() - direction_x * head_length - direction_y * head_width,
                tip.y() - direction_y * head_length + direction_x * head_width,
            )
        )
        arrow_head.lineTo(
            QPointF(
                tip.x() - direction_x * head_length + direction_y * head_width,
                tip.y() - direction_y * head_length - direction_x * head_width,
            )
        )
        arrow_head.closeSubpath()
        painter.drawPath(arrow_head)

        if not self._show_label:
            return
        painter.save()
        painter.setPen(color)
        font = QFont("Malgun Gothic", 8)
        font.setBold(self._is_peak)
        painter.setFont(font)
        painter.drawText(
            tip + QPointF(7.0, -5.0),
            f"{self.displacement.magnitude:.4g} {self.unit_system.length}",
        )
        painter.restore()
