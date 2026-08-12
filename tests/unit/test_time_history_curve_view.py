import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QMouseEvent, Qt
from PySide6.QtWidgets import QApplication

from openframe.features.results.presentation.time_history_curve_view import (
    TimeHistoryCurveView,
)


def _view() -> TimeHistoryCurveView:
    QApplication.instance() or QApplication([])
    view = TimeHistoryCurveView()
    view.resize(500, 300)
    view.show()
    view.set_series((0.0, 1.0, 2.0, 3.0, 4.0), (1.0, -2.0, 3.0, -1.0, 0.5), y_label="U [m]")
    view.grab()  # forces a synchronous paintEvent, populating _last_plot_rect
    return view


def _click_at(view: TimeHistoryCurveView, x: float, y: float) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.mousePressEvent(event)


def test_clicking_inside_the_plot_emits_the_corresponding_time() -> None:
    view = _view()
    assert view._last_plot_rect is not None
    received: list[float] = []
    view.time_clicked.connect(received.append)

    center_x = view._last_plot_rect.center().x()
    center_y = view._last_plot_rect.center().y()
    _click_at(view, center_x, center_y)

    assert len(received) == 1
    assert received[0] == pytest.approx(view._last_max_time / 2.0, abs=0.05)


def test_clicking_at_the_left_edge_gives_time_zero() -> None:
    view = _view()
    received: list[float] = []
    view.time_clicked.connect(received.append)

    _click_at(view, view._last_plot_rect.left(), view._last_plot_rect.center().y())

    assert received[0] == pytest.approx(0.0, abs=1e-6)


def test_clicking_outside_the_plot_area_emits_nothing() -> None:
    view = _view()
    received: list[float] = []
    view.time_clicked.connect(received.append)

    _click_at(view, 2.0, 2.0)  # inside the left axis-label margin, not the plot

    assert received == []


def test_no_series_means_no_click_handling() -> None:
    QApplication.instance() or QApplication([])
    view = TimeHistoryCurveView()
    view.resize(500, 300)
    view.show()
    view.grab()
    received: list[float] = []
    view.time_clicked.connect(received.append)

    _click_at(view, 250.0, 150.0)

    assert received == []
