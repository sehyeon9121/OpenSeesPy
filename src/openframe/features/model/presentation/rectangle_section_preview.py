"""Live-rendered preview of a member's rectangular section."""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class _RectangleSectionPreview(QWidget):
    """A tiny live-rendered rectangle, scaled to the member's own width:height
    ratio, so typing a section's dimensions gives an immediate visual instead
    of trusting two numbers to look "right" in your head."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.setToolTip("입력한 폭·높이 비율의 단면 미리보기")
        self._width = 0.3
        self._height = 0.5

    def set_dimensions(self, width: float, height: float) -> None:
        self._width = max(width, 0.001)
        self._height = max(height, 0.001)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        margin = 8.0
        box = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        scale = min(box.width() / self._width, box.height() / self._height)
        rect_width = self._width * scale
        rect_height = self._height * scale
        rect = QRectF(
            box.center().x() - rect_width / 2.0,
            box.center().y() - rect_height / 2.0,
            rect_width,
            rect_height,
        )
        pen = QPen(QColor("#174ea6"), 1.6)
        painter.setPen(pen)
        painter.setBrush(QColor(23, 78, 166, 45))
        painter.drawRect(rect)
