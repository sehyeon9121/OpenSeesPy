"""Numeric input fields that don't misbehave under a scroll gesture."""

from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox


class SafeDoubleSpinBox(QDoubleSpinBox):
    """Prevent a scrolling gesture from silently changing an engineering value,
    and let the user type as many decimal places as they need. ``decimals()``
    is set generously high (see ``_number``) so Qt's input validator never
    blocks a keystroke; ``textFromValue`` then trims the trailing zeros that
    a high fixed ``decimals()`` would otherwise pad every displayed value
    with, so "5" still reads as "5", not "5.0000000000"."""

    def wheelEvent(self, event) -> None:
        event.ignore()

    def textFromValue(self, value: float) -> str:
        text = f"{value:.{self.decimals()}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"


class SafeSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()
