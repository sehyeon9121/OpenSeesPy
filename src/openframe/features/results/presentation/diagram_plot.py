"""Scale-independent value-vs-position line plot for one member force diagram."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from openframe.features.results.diagrams.base import MemberDiagram


class DiagramPlot(QWidget):
    _MIN_ZOOM = 0.25
    _MAX_ZOOM = 8.0
    _ZOOM_STEP = 1.25
    _AUTO_FIT_PADDING = 1.45

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("diagramPlot")
        self.setMinimumHeight(130)
        self._diagram: MemberDiagram | None = None
        self._unit: str = ""
        self._zoom_factor = 1.0

    def set_diagram(self, diagram: MemberDiagram | None, unit: str = "") -> None:
        changed = diagram != self._diagram or unit != self._unit
        self._diagram = diagram
        self._unit = unit
        if changed:
            self._zoom_factor = 1.0
        self.update()

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom_factor * self._ZOOM_STEP)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom_factor / self._ZOOM_STEP)

    def fit_to_view(self) -> None:
        self._set_zoom(1.0)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_in()
        elif event.angleDelta().y() < 0:
            self.zoom_out()
        event.accept()

    def _set_zoom(self, zoom_factor: float) -> None:
        self._zoom_factor = max(self._MIN_ZOOM, min(self._MAX_ZOOM, zoom_factor))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        if self._diagram is None or len(self._diagram.points) < 2:
            painter.setPen(QColor("#9aa7b8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "부재를 선택하세요")
            painter.end()
            return

        points = self._diagram.points
        values = [point.value for point in points]
        max_abs = max((abs(value) for value in values), default=0.0) or 1.0
        display_limit = max_abs * self._AUTO_FIT_PADDING / self._zoom_factor

        font_metrics = painter.fontMetrics()
        label_height = float(font_metrics.height() + 2)
        # A sampled member carries many points; labelling each one makes the plot
        # unreadable, so only the ends and the peak between them are named.
        labelled_indexes = self._labelled_indexes(values)
        point_labels = [
            self._point_label(value, max_abs) if index in labelled_indexes else ""
            for index, value in enumerate(values)
        ]
        widest_point_label = max(
            (font_metrics.horizontalAdvance(label) for label in point_labels),
            default=0,
        )
        axis_labels = (f"{display_limit:.3g}", f"{-display_limit:.3g}")
        axis_label_width = max(font_metrics.horizontalAdvance(label) for label in axis_labels)
        endpoint_margin = widest_point_label / 2.0 + 8.0
        left_margin = max(axis_label_width + 14.0, endpoint_margin)
        right_margin = endpoint_margin
        vertical_margin = label_height + 8.0
        plot_rect = QRectF(self.rect()).adjusted(
            left_margin,
            vertical_margin,
            -right_margin,
            -vertical_margin,
        )
        if plot_rect.width() <= 1.0 or plot_rect.height() <= 1.0:
            painter.end()
            return

        baseline_y = plot_rect.center().y()
        min_position = min(point.position for point in points)
        max_position = max(point.position for point in points)
        position_span = max_position - min_position or 1.0

        def to_screen(position: float, value: float) -> tuple[float, float]:
            relative_position = (position - min_position) / position_span
            x = plot_rect.left() + relative_position * plot_rect.width()
            y = baseline_y - (value / display_limit) * (plot_rect.height() / 2.0)
            return x, y

        painter.setPen(QColor("#7b8a9e"))
        painter.drawText(
            QRectF(4.0, plot_rect.top() - label_height / 2.0, left_margin - 10.0, label_height),
            Qt.AlignmentFlag.AlignRight,
            axis_labels[0],
        )
        painter.drawText(
            QRectF(
                4.0,
                plot_rect.bottom() - label_height / 2.0,
                left_margin - 10.0,
                label_height,
            ),
            Qt.AlignmentFlag.AlignRight,
            axis_labels[1],
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
        for point, label in zip(points, point_labels, strict=True):
            if not label:
                continue
            x, y = to_screen(point.position, point.value)
            label_width = float(font_metrics.horizontalAdvance(label) + 8)
            offset = -(label_height + 4.0) if point.value >= 0 else 4.0
            painter.drawText(
                QRectF(x - label_width / 2.0, y + offset, label_width, label_height),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

        painter.end()

    def _point_label(self, value: float, peak: float) -> str:
        # An end that carries nothing comes back as solver noise such as -8.5e-14;
        # printed verbatim it reads as a defect rather than as zero.
        shown = 0.0 if abs(value) <= peak * 1.0e-9 else value
        label = f"{shown:.3g}"
        return f"{label} {self._unit}" if self._unit else label

    @staticmethod
    def _labelled_indexes(values: list[float]) -> set[int]:
        """Both ends, plus the largest interior value when it exceeds them."""
        if len(values) <= 2:
            return set(range(len(values)))
        indexes = {0, len(values) - 1}
        interior = range(1, len(values) - 1)
        peak = max(interior, key=lambda index: abs(values[index]))
        if abs(values[peak]) > max(abs(values[0]), abs(values[-1])) * (1.0 + 1.0e-9):
            indexes.add(peak)
        return indexes
