"""Scale-independent 2D structural support symbols."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from openframe.core.domain import SupportKind

SUPPORT_NAMES = {
    SupportKind.FIXED: "고정지점",
    SupportKind.PINNED: "회전지점(힌지)",
    SupportKind.ROLLER_VERTICAL: "이동지점(수평 반력)",
    SupportKind.ROLLER_HORIZONTAL: "이동지점(수직 반력)",
    SupportKind.CUSTOM: "사용자 구속",
}


class SupportItem(QGraphicsItem):
    def __init__(
        self,
        node_tag: int,
        kind: SupportKind,
        restraints: tuple[bool, ...],
    ) -> None:
        super().__init__()
        self.kind = kind
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(-2.0)
        self.setData(0, ("support", node_tag))
        restraint_text = "".join("1" if value else "0" for value in restraints)
        self.setToolTip(f"Node {node_tag} · {SUPPORT_NAMES[kind]} · 구속 [{restraint_text}]")

    def boundingRect(self) -> QRectF:
        return QRectF(-32.0, -32.0, 64.0, 69.0)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#52657a"), 1.8)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor("#f7f9fc"))

        if self.kind == SupportKind.FIXED:
            self._draw_fixed(painter)
        elif self.kind == SupportKind.PINNED:
            self._draw_pinned(painter)
        elif self.kind == SupportKind.ROLLER_VERTICAL:
            # Restrains Ux (blocks horizontal motion) -> rests against a wall.
            self._draw_roller_on_wall(painter)
        elif self.kind == SupportKind.ROLLER_HORIZONTAL:
            # Restrains Uy (blocks vertical motion) -> rests on the ground.
            self._draw_roller_on_ground(painter)
        else:
            self._draw_custom(painter)

    def _draw_fixed(self, painter: QPainter) -> None:
        painter.drawLine(0, 4, 0, 13)
        ground_pen = QPen(QColor("#34485f"), 3.0)
        ground_pen.setCosmetic(True)
        painter.setPen(ground_pen)
        painter.drawLine(-13, 13, 13, 13)
        painter.setPen(QPen(QColor("#52657a"), 1.4))
        for x in range(-10, 15, 5):
            painter.drawLine(x, 14, x - 5, 20)

    def _draw_pinned(self, painter: QPainter) -> None:
        triangle = QPainterPath()
        triangle.moveTo(0, 5)
        triangle.lineTo(-11, 18)
        triangle.lineTo(11, 18)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.drawLine(-14, 19, 14, 19)
        for x in range(-11, 16, 6):
            painter.drawLine(x, 20, x - 4, 25)

    def _draw_roller_on_ground(self, painter: QPainter) -> None:
        triangle = QPainterPath()
        triangle.moveTo(0, 5)
        triangle.lineTo(-10, 16)
        triangle.lineTo(10, 16)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(-8, 17, 6, 6))
        painter.drawEllipse(QRectF(2, 17, 6, 6))
        painter.drawLine(-14, 25, 14, 25)

    def _draw_roller_on_wall(self, painter: QPainter) -> None:
        triangle = QPainterPath()
        triangle.moveTo(5, 0)
        triangle.lineTo(16, -10)
        triangle.lineTo(16, 10)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(17, -8, 6, 6))
        painter.drawEllipse(QRectF(17, 2, 6, 6))
        painter.drawLine(25, -14, 25, 14)

    def _draw_custom(self, painter: QPainter) -> None:
        painter.drawLine(0, 4, 0, 10)
        painter.drawRect(QRectF(-8, 10, 16, 12))
        painter.drawLine(-10, 24, 10, 24)
