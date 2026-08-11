"""Base-shear-vs-control-displacement (pushover) curve plot.

This is a genuine X/Y chart: both axes carry real, independent units, the origin
sits at the plot's bottom-left corner, and the curve is a sequence of converged
load steps rather than samples along a length.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, LoadDisplacementPoint, UnitSystem

_TICK_COUNT = 5


class LoadDisplacementCurveView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("loadDisplacementCurveView")
        self.setMinimumHeight(200)
        self._points: tuple[LoadDisplacementPoint, ...] = ()
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._incomplete = False

    def set_curve(
        self,
        points: tuple[LoadDisplacementPoint, ...],
        *,
        unit_system: UnitSystem = DEFAULT_UNIT_SYSTEM,
        incomplete: bool = False,
    ) -> None:
        """``incomplete`` marks a curve that stopped short of the requested number of
        steps because a later step failed to converge - still real data, just not the
        whole picture, so the plot notes it rather than pretending it finished."""
        self._points = points
        self._unit_system = unit_system
        self._incomplete = incomplete
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(QFont("Malgun Gothic", 8))
        painter.fillRect(self.rect(), QColor("#ffffff"))

        if len(self._points) < 2:
            painter.setPen(QColor("#9aa7b8"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "비선형 해석을 먼저 실행하세요"
            )
            painter.end()
            return

        displacements = [point.control_displacement for point in self._points]
        shears = [point.base_shear for point in self._points]
        max_disp = max((abs(value) for value in displacements), default=0.0) or 1.0
        max_shear = max((abs(value) for value in shears), default=0.0) or 1.0

        font_metrics = painter.fontMetrics()
        label_height = float(font_metrics.height() + 2)
        y_axis_labels = [self._format(max_shear * step / _TICK_COUNT) for step in range(_TICK_COUNT + 1)]
        x_axis_labels = [self._format(max_disp * step / _TICK_COUNT) for step in range(_TICK_COUNT + 1)]
        # left_margin has to fit three things side by side, in this order from the
        # widget's left edge: the rotated axis-name label, a gap, then the tick-
        # number column. Reserving enough *total* width isn't enough on its own -
        # the number column used to still be drawn starting at x=0 regardless, so a
        # wide enough number (e.g. "160") stretched leftward straight through the
        # axis-name label's own column and the two overlapped.
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
        top_margin = label_height + 20.0
        bottom_margin = 2.0 * label_height + 12.0
        right_margin = max(14.0, font_metrics.horizontalAdvance(x_axis_labels[-1]) / 2.0 + 6.0)
        plot_rect = QRectF(self.rect()).adjusted(
            left_margin, top_margin, -right_margin, -bottom_margin
        )
        if plot_rect.width() <= 1.0 or plot_rect.height() <= 1.0:
            painter.end()
            return

        def to_screen(displacement: float, shear: float) -> tuple[float, float]:
            x = plot_rect.left() + (displacement / max_disp) * plot_rect.width()
            y = plot_rect.bottom() - (shear / max_shear) * plot_rect.height()
            return x, y

        painter.setPen(QColor("#1f2937"))
        title = "밑면전단력 - 변위 곡선 (Pushover Curve)"
        if self._incomplete:
            title += "  —  마지막 스텝에서 수렴 실패, 그 이전까지만 표시"
        # A narrow viewport (or the longer "incomplete" title) can be shorter than
        # the full title - elide it instead of letting it overflow past the widget's
        # left/right edges, which reads as clipped/cut-off text rather than a title.
        title = font_metrics.elidedText(
            title, Qt.TextElideMode.ElideRight, int(self.rect().width() - 8.0)
        )
        painter.drawText(
            QRectF(4.0, 2.0, self.rect().width() - 8.0, label_height),
            Qt.AlignmentFlag.AlignHCenter,
            title,
        )

        # Gridlines + axis tick labels, evenly spaced across each axis's data range.
        painter.setPen(QPen(QColor("#e5e9f0"), 1.0))
        for step in range(_TICK_COUNT + 1):
            fraction = step / _TICK_COUNT
            y = plot_rect.bottom() - fraction * plot_rect.height()
            painter.drawLine(plot_rect.left(), y, plot_rect.right(), y)
            x = plot_rect.left() + fraction * plot_rect.width()
            painter.drawLine(x, plot_rect.top(), x, plot_rect.bottom())

        painter.setPen(QColor("#7b8a9e"))
        for step in range(_TICK_COUNT + 1):
            fraction = step / _TICK_COUNT
            y = plot_rect.bottom() - fraction * plot_rect.height()
            painter.drawText(
                QRectF(
                    number_column_left,
                    y - label_height / 2.0,
                    left_margin - 8.0 - number_column_left,
                    label_height,
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._format(max_shear * fraction),
            )
            x = plot_rect.left() + fraction * plot_rect.width()
            label = self._format(max_disp * fraction)
            label_width = float(font_metrics.horizontalAdvance(label) + 12)
            painter.drawText(
                QRectF(x - label_width / 2.0, plot_rect.bottom() + 4.0, label_width, label_height),
                Qt.AlignmentFlag.AlignHCenter,
                label,
            )

        force_unit = self._unit_system.force
        length_unit = self._unit_system.length
        painter.drawText(
            QRectF(0.0, plot_rect.bottom() + label_height + 4.0, self.rect().width(), label_height),
            Qt.AlignmentFlag.AlignHCenter,
            f"제어 절점 변위 [{length_unit}]",
        )
        painter.save()
        # Translating to axis_title_width (not into the number column - see
        # number_column_left above) keeps this label in its own reserved strip,
        # to the left of the tick numbers rather than drawn on top of them.
        painter.translate(axis_title_width, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(
            QRectF(-plot_rect.height() / 2.0, -label_height, plot_rect.height(), label_height),
            Qt.AlignmentFlag.AlignHCenter,
            f"밑면전단력 [{force_unit}]",
        )
        painter.restore()

        painter.setPen(QPen(QColor("#7b8a9e"), 1.2))
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.topLeft())
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.bottomRight())

        curve_path = QPainterPath()
        first_x, first_y = to_screen(displacements[0], shears[0])
        curve_path.moveTo(first_x, first_y)
        for displacement, shear in zip(displacements[1:], shears[1:], strict=True):
            curve_path.lineTo(*to_screen(displacement, shear))
        painter.setPen(QPen(QColor("#174ea6"), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve_path)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#174ea6"))
        marker_radius = 3.0
        for displacement, shear in zip(displacements, shears, strict=True):
            x, y = to_screen(displacement, shear)
            painter.drawEllipse(QRectF(x - marker_radius, y - marker_radius, 2 * marker_radius, 2 * marker_radius))

        painter.end()

    @staticmethod
    def _format(value: float) -> str:
        return f"{value:.3g}"
