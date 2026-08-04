"""Scale-independent value-vs-position line plot for one member force diagram."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from openframe.features.results.diagrams.base import MemberDiagram


class DiagramPlot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("diagramPlot")
        self.setMinimumHeight(130)
        self._diagram: MemberDiagram | None = None
        self._unit: str = ""

    def set_diagram(self, diagram: MemberDiagram | None, unit: str = "") -> None:
        self._diagram = diagram
        self._unit = unit
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        plot_rect = QRectF(self.rect()).adjusted(28.0, 10.0, -10.0, -10.0)

        if self._diagram is None or len(self._diagram.points) < 2:
            painter.setPen(QColor("#9aa7b8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "부재를 선택하세요")
            painter.end()
            return

        points = self._diagram.points
        values = [point.value for point in points]
        max_abs = max((abs(value) for value in values), default=0.0) or 1.0
        baseline_y = plot_rect.center().y()

        def to_screen(position: float, value: float) -> tuple[float, float]:
            x = plot_rect.left() + position * plot_rect.width()
            y = baseline_y - (value / max_abs) * (plot_rect.height() / 2.0)
            return x, y

        painter.setPen(QColor("#7b8a9e"))
        painter.drawText(
            QRectF(0.0, plot_rect.top() - 8.0, 26.0, 16.0),
            Qt.AlignmentFlag.AlignRight,
            f"{max_abs:.3g}",
        )
        painter.drawText(
            QRectF(0.0, plot_rect.bottom() - 8.0, 26.0, 16.0),
            Qt.AlignmentFlag.AlignRight,
            f"{-max_abs:.3g}",
        )

        painter.setPen(QPen(QColor("#c7d2e0"), 1.0))
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.topLeft())
        painter.drawLine(
            plot_rect.left(), baseline_y, plot_rect.right(), baseline_y
        )

        fill_path = QPainterPath()
        start_x, _ = to_screen(points[0].position, 0.0)
        fill_path.moveTo(start_x, baseline_y)
        for point in points:
            x, y = to_screen(point.position, point.value)
            fill_path.lineTo(x, y)
        end_x, _ = to_screen(points[-1].position, 0.0)
        fill_path.lineTo(end_x, baseline_y)
        fill_path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(23, 78, 166, 55))
        painter.drawPath(fill_path)

        line_path = QPainterPath()
        first_x, first_y = to_screen(points[0].position, points[0].value)
        line_path.moveTo(first_x, first_y)
        for point in points[1:]:
            x, y = to_screen(point.position, point.value)
            line_path.lineTo(x, y)
        painter.setPen(QPen(QColor("#174ea6"), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(line_path)

        painter.setPen(QColor("#1f2937"))
        for point in points:
            x, y = to_screen(point.position, point.value)
            label = f"{point.value:.3g}"
            if self._unit:
                label = f"{label} {self._unit}"
            offset = -18.0 if point.value >= 0 else 4.0
            painter.drawText(
                QRectF(x - 40.0, y + offset, 80.0, 14.0),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

        painter.end()
