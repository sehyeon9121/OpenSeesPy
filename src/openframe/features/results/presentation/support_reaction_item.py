"""Scale-independent support-reaction arrows drawn at restrained nodes."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, UnitSystem
from openframe.features.results.reactions import SupportReaction

REACTION_COLOR = "#0f8a5f"
REACTION_LABEL_COLOR = "#0b6b4a"


class SupportReactionItem(QGraphicsItem):
    """Draws Rx, Ry and Mz for one support, pointing the way each reaction acts."""

    def __init__(
        self,
        reaction: SupportReaction,
        unit_system: UnitSystem = DEFAULT_UNIT_SYSTEM,
    ) -> None:
        super().__init__()
        self.reaction = reaction
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(7.0)
        self.setData(0, ("result_reaction", reaction.node_tag))
        self.set_unit_system(unit_system)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.unit_system = unit_system
        reaction = self.reaction
        self.setToolTip(
            f"Node {reaction.node_tag} | Rx={reaction.fx:g} {unit_system.force} | "
            f"Ry={reaction.fy:g} {unit_system.force} | "
            f"Mz={reaction.mz:g} {unit_system.moment}"
        )
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-135.0, -115.0, 270.0, 230.0)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(REACTION_COLOR)
        pen = QPen(color, 2.4)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(color)

        reaction = self.reaction
        if reaction.fx != 0.0:
            self._draw_arrow(
                painter,
                direction_x=1.0 if reaction.fx > 0.0 else -1.0,
                direction_y=0.0,
                label=f"Rx {reaction.fx:g} {self.unit_system.force}",
            )
        if reaction.fy != 0.0:
            # Model +Y is upward while screen +Y is downward.
            self._draw_arrow(
                painter,
                direction_x=0.0,
                direction_y=-1.0 if reaction.fy > 0.0 else 1.0,
                label=f"Ry {reaction.fy:g} {self.unit_system.force}",
            )
        if reaction.mz != 0.0:
            self._draw_moment(painter)

    def _draw_arrow(
        self,
        painter: QPainter,
        *,
        direction_x: float,
        direction_y: float,
        label: str,
    ) -> None:
        arrow_length = 62.0
        tail = QPointF(-direction_x * arrow_length, -direction_y * arrow_length)
        tip = QPointF(0.0, 0.0)
        painter.drawLine(tail, tip)

        perpendicular_x = -direction_y
        perpendicular_y = direction_x
        head_length = 11.0
        head_width = 5.5
        arrow_head = QPainterPath()
        arrow_head.moveTo(tip)
        arrow_head.lineTo(
            QPointF(
                -direction_x * head_length + perpendicular_x * head_width,
                -direction_y * head_length + perpendicular_y * head_width,
            )
        )
        arrow_head.lineTo(
            QPointF(
                -direction_x * head_length - perpendicular_x * head_width,
                -direction_y * head_length - perpendicular_y * head_width,
            )
        )
        arrow_head.closeSubpath()
        painter.drawPath(arrow_head)

        self._draw_label(painter, label, tail + QPointF(7.0, -8.0))

    def _draw_moment(self, painter: QPainter) -> None:
        arc_rect = QRectF(-27.0, -27.0, 54.0, 54.0)
        if self.reaction.mz > 0.0:
            painter.drawArc(arc_rect, -30 * 16, 275 * 16)
            tip, first, second = (
                QPointF(21.0, -16.0),
                QPointF(22.0, -5.0),
                QPointF(11.0, -12.0),
            )
        else:
            painter.drawArc(arc_rect, 30 * 16, -275 * 16)
            tip, first, second = (
                QPointF(21.0, 16.0),
                QPointF(22.0, 5.0),
                QPointF(11.0, 12.0),
            )
        arrow_head = QPainterPath()
        arrow_head.moveTo(tip)
        arrow_head.lineTo(first)
        arrow_head.lineTo(second)
        arrow_head.closeSubpath()
        painter.drawPath(arrow_head)
        self._draw_label(
            painter,
            f"Mz {self.reaction.mz:g} {self.unit_system.moment}",
            QPointF(31.0, 6.0),
        )

    @staticmethod
    def _draw_label(painter: QPainter, text: str, position: QPointF) -> None:
        painter.save()
        painter.setPen(QColor(REACTION_LABEL_COLOR))
        painter.setFont(QFont("Malgun Gothic", 8))
        painter.drawText(position, text)
        painter.restore()
