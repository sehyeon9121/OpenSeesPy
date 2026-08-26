"""Input fields that don't misbehave under a scroll gesture."""

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


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


class SafeComboBox(QComboBox):
    """Same fix as ``SafeDoubleSpinBox``, for dropdowns - scrolling past one
    (e.g. a section/material selector in a scrollable property panel) must
    scroll the page, not silently swap the selected item out from under the
    user."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class DownwardComboBox(QComboBox):
    """Dropdown whose popup always opens below it, never above.

    Qt's default popup placement flips the list above the combo box
    whenever it judges there isn't enough room below it on the physical
    screen. For a combo living low in a tall scrollable panel (e.g. the
    Loads command bar), that "no room below" reading is usually just the
    rest of the window being scrolled out of view, not an actual screen
    edge - so force the popup to stay below instead of trusting the guess.
    """

    def showPopup(self) -> None:
        super().showPopup()
        popup = self.view().window()
        anchor = self.mapToGlobal(self.rect().bottomLeft())
        popup.move(anchor.x(), anchor.y())
