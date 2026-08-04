"""Scale-independent node identifier badge."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget


class NodeLabelItem(QGraphicsItem):
    def __init__(self, node_tag: int) -> None:
        super().__init__()
        self._text = str(node_tag)
        self._font = QFont("Segoe UI", 8)
        self._font.setWeight(QFont.Weight.DemiBold)
        text_width = QFontMetricsF(self._font).horizontalAdvance(self._text)
        self._badge_rect = QRectF(7.0, -25.0, max(20.0, text_width + 10.0), 18.0)

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(6.0)
        self.setData(0, ("node_label", node_tag))
        self.setToolTip(f"Node {node_tag}")

    def boundingRect(self) -> QRectF:
        return self._badge_rect.adjusted(-1.0, -1.0, 1.0, 1.0)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        border_pen = QPen(QColor("#b8c8dd"), 1.0)
        border_pen.setCosmetic(True)
        painter.setPen(border_pen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(self._badge_rect, 4.0, 4.0)

        painter.setPen(QColor("#174ea6"))
        painter.setFont(self._font)
        painter.drawText(self._badge_rect, Qt.AlignmentFlag.AlignCenter, self._text)
