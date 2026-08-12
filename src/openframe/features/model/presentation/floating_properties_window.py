"""A small floating window for property editors too tall for the top bar."""

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget


class _FloatingPropertiesWindow(QDialog):
    """A small non-modal window for a property editor whose content is too
    tall to sit inline in the canvas-top bar without stretching the whole
    bar's height and shrinking the canvas — 부재 속성 (section/material + pin
    releases + node insertion) is the one case of this so far, since it stacks
    several rows vertically while every other top-bar section (지점/노드 유형/
    하중) lays its content out as a single horizontal row. Non-modal so the
    canvas stays clickable to select a different member while the window is
    open — the fields inside it already resync to whatever is selected on
    every ``_sync_property_panel`` call, window open or not."""

    def __init__(
        self,
        title: str,
        content: QWidget,
        on_close: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle(title)
        self._on_close = on_close
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(content)
        self.setFixedWidth(320)

    def closeEvent(self, event) -> None:
        self._on_close()
        super().closeEvent(event)
