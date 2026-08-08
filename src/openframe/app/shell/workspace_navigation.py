"""Top-level MODEL, ANALYSIS, RESULTS and VIEWPORT navigation."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QToolButton, QWidget


class WorkspaceNavigation(QFrame):
    current_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceNavigation")
        self._buttons: dict[str, QToolButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, text in (
            ("model", "MODEL"),
            ("analysis", "ANALYSIS"),
            ("results", "RESULTS"),
            ("viewport", "VIEWPORT"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, name=key: self._select(name))
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self._buttons["model"].setChecked(True)

    def current_section(self) -> str:
        return next(
            (key for key, button in self._buttons.items() if button.isChecked()),
            "model",
        )

    def set_current_section(self, key: str, *, emit: bool = False) -> None:
        if key not in self._buttons:
            raise ValueError(f"Unknown workspace section: {key}")
        self._buttons[key].setChecked(True)
        if emit:
            self.current_changed.emit(key)

    def _select(self, key: str) -> None:
        self.set_current_section(key, emit=True)
