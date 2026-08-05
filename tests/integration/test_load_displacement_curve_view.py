"""Regression coverage for LoadDisplacementCurveView's margin math.

Margins used to be sized only from the Y-axis tick numbers - the rotated axis-name
label (translated by a bare hardcoded 12px, not its own height) and the leftmost/
rightmost X-axis tick labels (centred on the plot's own edges, half sticking out
past it) were never accounted for, so labels could be drawn partly off the widget.
paintEvent has no clip region, so "off the widget" reads as text getting cut off
rather than an exception - this can't be asserted via pixel content in this sandbox
(Malgun Gothic doesn't render here), so these checks confirm the widget paints
without crashing across the narrow/long-title conditions that triggered it."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, LoadDisplacementPoint
from openframe.features.results.presentation.load_displacement_curve_view import (
    LoadDisplacementCurveView,
)

_CURVE = tuple(
    LoadDisplacementPoint(step=i, control_displacement=i * 0.02434, base_shear=i * 8.0)
    for i in range(1, 21)
)


def test_paints_without_crashing_at_narrow_widths_with_the_incomplete_title() -> None:
    application = QApplication.instance() or QApplication([])
    for width, height in ((700, 420), (300, 220), (180, 150), (120, 120)):
        view = LoadDisplacementCurveView()
        view.resize(width, height)
        view.set_curve(_CURVE, unit_system=DEFAULT_UNIT_SYSTEM, incomplete=True)
        view.show()
        application.processEvents()
        pixmap = view.grab()
        assert pixmap.width() == width
        view.close()
