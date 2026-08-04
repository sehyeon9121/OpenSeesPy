"""Scale-independent support-reaction arrows drawn at restrained nodes."""

import math

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

    #: Degrees of arc drawn. Short enough that the curve reads as "this much rotation"
    #: rather than nearly a full circle, and its two ends stay far apart on screen.
    _MOMENT_SWEEP_DEGREES = 130.0
    _MOMENT_START_DEGREES = -35.0
    _MOMENT_RADIUS = 22.0

    def _draw_moment(self, painter: QPainter) -> None:
        # Positive Mz is counter-clockwise (right-hand rule); this view is drawn the way
        # it would be on paper (not mirrored), so a positive reaction sweeps
        # counter-clockwise on screen too - verified against a cantilever's fixed-end
        # moment reaction, which is oriented opposite the tip load that causes it.
        direction = 1.0 if self.reaction.mz > 0.0 else -1.0
        end_degrees = self._MOMENT_START_DEGREES + direction * self._MOMENT_SWEEP_DEGREES

        rect = QRectF(
            -self._MOMENT_RADIUS, -self._MOMENT_RADIUS,
            2.0 * self._MOMENT_RADIUS, 2.0 * self._MOMENT_RADIUS,
        )
        path = QPainterPath()
        path.arcMoveTo(rect, self._MOMENT_START_DEGREES)
        path.arcTo(rect, self._MOMENT_START_DEGREES, direction * self._MOMENT_SWEEP_DEGREES)
        # An open arc path still gets filled as a pie slice unless the brush is cleared
        # first - only the arrowhead below should be solid.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setBrush(QColor(REACTION_COLOR))

        # The arrowhead sits exactly at the curve's end, pointing along the direction of
        # travel there, so the curve and the head read as one continuous arrow.
        tip = self._point_on_circle(self._MOMENT_RADIUS, end_degrees)
        travel = self._travel_direction(end_degrees, direction)
        self._draw_arrowhead_at(painter, tip, travel)

        label_degrees = self._MOMENT_START_DEGREES + direction * self._MOMENT_SWEEP_DEGREES / 2.0
        label_point = self._point_on_circle(self._MOMENT_RADIUS + 15.0, label_degrees)
        self._draw_label(
            painter,
            f"Mz {self.reaction.mz:g} {self.unit_system.moment}",
            label_point,
        )

    @staticmethod
    def _draw_arrowhead_at(painter: QPainter, tip: QPointF, travel: QPointF) -> None:
        head_length = 10.0
        head_width = 5.0
        back = QPointF(tip.x() - travel.x() * head_length, tip.y() - travel.y() * head_length)
        perpendicular = QPointF(-travel.y(), travel.x())
        arrow_head = QPainterPath()
        arrow_head.moveTo(tip)
        arrow_head.lineTo(
            QPointF(
                back.x() + perpendicular.x() * head_width,
                back.y() + perpendicular.y() * head_width,
            )
        )
        arrow_head.lineTo(
            QPointF(
                back.x() - perpendicular.x() * head_width,
                back.y() - perpendicular.y() * head_width,
            )
        )
        arrow_head.closeSubpath()
        painter.drawPath(arrow_head)

    @staticmethod
    def _point_on_circle(radius: float, degrees: float) -> QPointF:
        # Matches Qt's arc angle convention (0 deg at 3 o'clock, positive = counter-
        # clockwise as drawn on screen), independent of any transform on the item.
        radians = math.radians(degrees)
        return QPointF(radius * math.cos(radians), -radius * math.sin(radians))

    @classmethod
    def _travel_direction(cls, degrees: float, direction: float) -> QPointF:
        radians = math.radians(degrees)
        dx = -math.sin(radians) * direction
        dy = -math.cos(radians) * direction
        length = math.hypot(dx, dy) or 1.0
        return QPointF(dx / length, dy / length)

    @staticmethod
    def _draw_label(painter: QPainter, text: str, position: QPointF) -> None:
        painter.save()
        painter.setPen(QColor(REACTION_LABEL_COLOR))
        painter.setFont(QFont("Malgun Gothic", 8))
        painter.drawText(position, text)
        painter.restore()
