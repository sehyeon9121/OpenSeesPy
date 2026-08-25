"""Value-vs-time response-history plot for a single selected node/dof.

A genuine X/Y chart like the pushover curve, but unlike a pushover curve (which
is monotonic from zero) a time-history response oscillates on both sides of
zero - the Y axis is therefore ranged symmetrically around zero rather than
assumed to start there, with its own zero gridline drawn for reference.
"""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

_TICK_COUNT = 5


class TimeHistoryCurveView(QWidget):
    #: Emitted with the clicked time (clamped into the plotted range) when the
    #: user clicks inside the plot area - Phase 3-J's "graph click -> nearest
    #: step" entry point. Resolving that time to an actual step index is the
    #: caller's job (this view only knows times/values, not step indices).
    time_clicked = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timeHistoryCurveView")
        self.setMinimumHeight(200)
        self._times: tuple[float, ...] = ()
        self._values: tuple[float, ...] = ()
        self._y_label = ""
        self._empty_message = "시간이력해석을 먼저 실행하세요"
        self._marker: tuple[float, float] | None = None
        self._marker_label = ""
        self._corner_label = ""
        self._selected_time: float | None = None
        self._selected_point: tuple[float, float] | None = None
        self._selected_label = ""
        self._last_plot_rect: QRectF | None = None
        self._last_max_time = 0.0

    def set_series(
        self,
        times: tuple[float, ...],
        values: tuple[float, ...],
        *,
        y_label: str,
        marker: tuple[float, float] | None = None,
        marker_label: str = "",
        corner_label: str = "",
        selected_time: float | None = None,
        selected_point: tuple[float, float] | None = None,
        selected_label: str = "",
    ) -> None:
        """``marker`` is an optional (time, value) point to highlight - e.g.
        where the absolute-max response occurs - drawn as a dot with a small
        text label next to it. ``selected_time`` is a separate, independent
        highlight - the point the user last clicked in the graph - drawn as a
        vertical guide line so it stays visually distinct from the marker.
        ``selected_point`` and ``selected_label`` add the curve value at that
        guide, so a click is useful without opening the animation panel.
        ``corner_label`` identifies the plotted series in the lower-left of
        the graph (used by SETUP's ground-motion preview)."""
        self._times = times
        self._values = values
        self._y_label = y_label
        self._marker = marker
        self._marker_label = marker_label
        self._corner_label = corner_label
        self._selected_time = selected_time
        self._selected_point = selected_point
        self._selected_label = selected_label
        self.update()

    def set_empty_message(self, message: str) -> None:
        self._empty_message = message
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() != Qt.MouseButton.LeftButton
            or self._last_plot_rect is None
            or len(self._times) < 2
        ):
            super().mousePressEvent(event)
            return
        position = event.position()
        if not self._last_plot_rect.contains(position):
            super().mousePressEvent(event)
            return
        fraction = (position.x() - self._last_plot_rect.left()) / self._last_plot_rect.width()
        time = max(0.0, min(1.0, fraction)) * self._last_max_time
        self.time_clicked.emit(time)
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(QFont("Malgun Gothic", 8))
        painter.fillRect(self.rect(), QColor("#ffffff"))

        if len(self._times) < 2:
            painter.setPen(QColor("#9aa7b8"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_message)
            painter.end()
            return

        max_time = self._times[-1] or 1.0
        # Symmetric around zero: an oscillating response's peak positive and
        # negative excursions are rarely equal, but the zero line stays at the
        # visual center regardless, which is the more readable convention for
        # this kind of data (matches how vibration time-histories are normally
        # plotted) than an asymmetric min/max range would be.
        bound = max((abs(value) for value in self._values), default=0.0) or 1.0

        font_metrics = painter.fontMetrics()
        label_height = float(font_metrics.height() + 2)
        y_axis_labels = [
            self._format(bound * step / _TICK_COUNT) for step in range(-_TICK_COUNT, _TICK_COUNT + 1)
        ]
        x_axis_labels = [self._format(max_time * step / _TICK_COUNT) for step in range(_TICK_COUNT + 1)]
        axis_title_width = label_height + 4.0
        axis_title_gap = 4.0
        number_column_left = axis_title_width + axis_title_gap
        number_column_width = (
            max(font_metrics.horizontalAdvance(label) for label in y_axis_labels) + 8.0
        )
        left_margin = max(
            number_column_left + number_column_width,
            font_metrics.horizontalAdvance(x_axis_labels[0]) / 2.0 + 6.0,
        )
        top_margin = label_height + 8.0
        bottom_margin = 2.0 * label_height + 12.0
        right_margin = max(14.0, font_metrics.horizontalAdvance(x_axis_labels[-1]) / 2.0 + 6.0)
        plot_rect = QRectF(self.rect()).adjusted(
            left_margin, top_margin, -right_margin, -bottom_margin
        )
        if plot_rect.width() <= 1.0 or plot_rect.height() <= 1.0:
            painter.end()
            return
        self._last_plot_rect = QRectF(plot_rect)
        self._last_max_time = max_time

        def to_screen(time: float, value: float) -> tuple[float, float]:
            x = plot_rect.left() + (time / max_time) * plot_rect.width()
            # value in [-bound, bound] maps to y in [bottom, top].
            y = plot_rect.center().y() - (value / bound) * (plot_rect.height() / 2.0)
            return x, y

        # Gridlines: _TICK_COUNT+1 on X (0..max_time), 2*_TICK_COUNT+1 on Y
        # (-bound..bound) so the zero line always lands exactly on one of them.
        painter.setPen(QPen(QColor("#e5e9f0"), 1.0))
        for step in range(-_TICK_COUNT, _TICK_COUNT + 1):
            fraction = step / _TICK_COUNT
            y = plot_rect.center().y() - fraction * (plot_rect.height() / 2.0)
            painter.drawLine(plot_rect.left(), y, plot_rect.right(), y)
        for step in range(_TICK_COUNT + 1):
            fraction = step / _TICK_COUNT
            x = plot_rect.left() + fraction * plot_rect.width()
            painter.drawLine(x, plot_rect.top(), x, plot_rect.bottom())

        # Zero line drawn heavier than the other gridlines - the one reference
        # value that actually matters for reading an oscillating response.
        painter.setPen(QPen(QColor("#b7c0cc"), 1.3))
        painter.drawLine(plot_rect.left(), plot_rect.center().y(), plot_rect.right(), plot_rect.center().y())

        painter.setPen(QColor("#7b8a9e"))
        for step in range(-_TICK_COUNT, _TICK_COUNT + 1):
            fraction = step / _TICK_COUNT
            y = plot_rect.center().y() - fraction * (plot_rect.height() / 2.0)
            painter.drawText(
                QRectF(
                    number_column_left,
                    y - label_height / 2.0,
                    left_margin - 8.0 - number_column_left,
                    label_height,
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._format(bound * fraction),
            )
        for step in range(_TICK_COUNT + 1):
            fraction = step / _TICK_COUNT
            x = plot_rect.left() + fraction * plot_rect.width()
            label = self._format(max_time * fraction)
            label_width = float(font_metrics.horizontalAdvance(label) + 12)
            painter.drawText(
                QRectF(x - label_width / 2.0, plot_rect.bottom() + 4.0, label_width, label_height),
                Qt.AlignmentFlag.AlignHCenter,
                label,
            )

        painter.drawText(
            QRectF(0.0, plot_rect.bottom() + label_height + 4.0, self.rect().width(), label_height),
            Qt.AlignmentFlag.AlignHCenter,
            "시간 [s]",
        )
        painter.save()
        painter.translate(axis_title_width, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(
            QRectF(-plot_rect.height() / 2.0, -label_height, plot_rect.height(), label_height),
            Qt.AlignmentFlag.AlignHCenter,
            self._y_label,
        )
        painter.restore()

        painter.setPen(QPen(QColor("#7b8a9e"), 1.2))
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.topLeft())
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.bottomRight())

        curve_path = QPainterPath()
        first_x, first_y = to_screen(self._times[0], self._values[0])
        curve_path.moveTo(first_x, first_y)
        for time, value in zip(self._times[1:], self._values[1:], strict=True):
            curve_path.lineTo(*to_screen(time, value))
        painter.setPen(QPen(QColor("#174ea6"), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve_path)

        if self._corner_label:
            max_label_width = max(40, int(plot_rect.width() * 0.7))
            display_label = font_metrics.elidedText(
                self._corner_label,
                Qt.TextElideMode.ElideRight,
                max_label_width - 14,
            )
            label_width = min(
                float(max_label_width),
                float(font_metrics.horizontalAdvance(display_label) + 14),
            )
            badge_rect = QRectF(
                plot_rect.left() + 6.0,
                plot_rect.bottom() - label_height - 11.0,
                label_width,
                label_height + 5.0,
            )
            painter.setPen(QPen(QColor("#7b8a9e"), 1.0))
            painter.setBrush(QColor(255, 255, 255, 225))
            painter.drawRoundedRect(badge_rect, 4.0, 4.0)
            painter.setPen(QColor("#41536a"))
            painter.drawText(
                badge_rect.adjusted(7.0, 0.0, -7.0, 0.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                display_label,
            )

        if self._selected_time is not None:
            selected_x, _ = to_screen(self._selected_time, 0.0)
            selection_color = QColor("#c7352e")
            selection_pen = QPen(selection_color, 1.4, Qt.PenStyle.DashLine)
            selection_pen.setCosmetic(True)
            painter.setPen(selection_pen)
            painter.drawLine(selected_x, plot_rect.top(), selected_x, plot_rect.bottom())

            if self._selected_point is not None:
                point_x, point_y = to_screen(*self._selected_point)
                painter.setPen(QPen(QColor("#ffffff"), 1.5))
                painter.setBrush(selection_color)
                point_radius = 4.5
                painter.drawEllipse(
                    QRectF(
                        point_x - point_radius,
                        point_y - point_radius,
                        2 * point_radius,
                        2 * point_radius,
                    )
                )

            if self._selected_label:
                max_text_width = max(40, int(plot_rect.width() - 18.0))
                display_label = font_metrics.elidedText(
                    self._selected_label,
                    Qt.TextElideMode.ElideRight,
                    max_text_width - 12,
                )
                callout_width = min(
                    float(max_text_width),
                    float(font_metrics.horizontalAdvance(display_label) + 14),
                )
                callout_height = label_height + 6.0
                callout_x = selected_x + 7.0
                if callout_x + callout_width > plot_rect.right() - 3.0:
                    callout_x = selected_x - callout_width - 7.0
                callout_x = min(
                    max(callout_x, plot_rect.left() + 3.0),
                    plot_rect.right() - callout_width - 3.0,
                )
                callout_rect = QRectF(
                    callout_x,
                    plot_rect.top() + 5.0,
                    callout_width,
                    callout_height,
                )
                painter.setPen(QPen(selection_color, 1.0))
                painter.setBrush(QColor("#fff5f4"))
                painter.drawRoundedRect(callout_rect, 4.0, 4.0)
                painter.setPen(selection_color)
                painter.drawText(
                    callout_rect.adjusted(7.0, 0.0, -7.0, 0.0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    display_label,
                )

        if self._marker is not None:
            marker_time, marker_value = self._marker
            marker_x, marker_y = to_screen(marker_time, marker_value)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#d1453b"))
            radius = 4.0
            painter.drawEllipse(QRectF(marker_x - radius, marker_y - radius, 2 * radius, 2 * radius))
            if self._marker_label:
                painter.setPen(QColor("#d1453b"))
                label_width = float(font_metrics.horizontalAdvance(self._marker_label) + 8)
                label_x = min(max(marker_x - label_width / 2.0, plot_rect.left()), plot_rect.right() - label_width)
                label_y = marker_y - radius - label_height if marker_y - radius - label_height >= plot_rect.top() else marker_y + radius
                painter.drawText(
                    QRectF(label_x, label_y, label_width, label_height),
                    Qt.AlignmentFlag.AlignHCenter,
                    self._marker_label,
                )

        painter.end()

    @staticmethod
    def _format(value: float) -> str:
        return f"{value:.3g}"
