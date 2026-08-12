"""Top-level MODEL, SETUP, RESULTS and VIEWPORT navigation.

Also carries the current file's breadcrumb (name + status) - the engineering
tools this app takes cues from (MIDAS, SAP2000) always keep "what file am I
in, is it ready" visible next to the section tabs, not buried in a sidebar."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)


class WorkspaceNavigation(QFrame):
    current_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceNavigation")
        self._buttons: dict[str, QToolButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(6)

        self.breadcrumb = QFrame()
        self.breadcrumb.setObjectName("navigationBreadcrumb")
        breadcrumb_layout = QHBoxLayout(self.breadcrumb)
        breadcrumb_layout.setContentsMargins(0, 0, 0, 0)
        breadcrumb_layout.setSpacing(6)
        self.breadcrumb_icon = QLabel("\U0001f4c1")
        self.breadcrumb_icon.setObjectName("breadcrumbIcon")
        self.breadcrumb_icon.hide()
        self.breadcrumb_name = QLabel("")
        self.breadcrumb_name.setObjectName("breadcrumbName")
        self.breadcrumb_status = QLabel("")
        self.breadcrumb_status.setObjectName("breadcrumbStatus")
        self.breadcrumb_status.setVisible(False)
        breadcrumb_layout.addWidget(self.breadcrumb_icon)
        breadcrumb_layout.addWidget(self.breadcrumb_name)
        breadcrumb_layout.addWidget(self.breadcrumb_status)
        layout.addWidget(self.breadcrumb)

        self.divider = QFrame()
        self.divider.setObjectName("navigationDivider")
        self.divider.setFrameShape(QFrame.Shape.VLine)
        self.divider.setFixedHeight(18)
        self.divider.hide()
        layout.addWidget(self.divider)
        layout.addSpacing(6)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, text in (
            ("model", "MODEL"),
            ("setup", "SETUP"),
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

    def set_breadcrumb(self, name: str) -> None:
        self.breadcrumb_name.setText(name)

    def set_breadcrumb_status(self, text: str) -> None:
        self.breadcrumb_status.setText(f"● {text}")
        self.breadcrumb_status.setVisible(bool(text))

    def set_home_mode(self, home: bool) -> None:
        """Keep global navigation visible on Home without selecting a workspace."""
        self.breadcrumb.setVisible(not home)
        self.divider.hide()
        if home:
            self._group.setExclusive(False)
            for button in self._buttons.values():
                button.setChecked(False)
            self._group.setExclusive(True)

    def current_section(self) -> str:
        return next(
            (key for key, button in self._buttons.items() if button.isChecked()),
            "model",
        )

    def append_trailing_widget(self, widget: QWidget) -> None:
        """Reparent a widget (e.g. AppHeader's upload button) onto this row's
        trailing edge, after the stretch — used to place UPLOAD .PY next to
        the section tabs instead of in the brand/actions row above."""
        self.layout().addWidget(widget)

    def set_current_section(self, key: str, *, emit: bool = False) -> None:
        if key not in self._buttons:
            raise ValueError(f"Unknown workspace section: {key}")
        self._buttons[key].setChecked(True)
        if emit:
            self.current_changed.emit(key)

    def _select(self, key: str) -> None:
        self.set_current_section(key, emit=True)
