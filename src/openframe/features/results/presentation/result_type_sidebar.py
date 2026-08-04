"""Post-processing result-type navigation."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class ResultTypeSidebar(QFrame):
    result_type_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultTypeSidebar")
        self.setMinimumWidth(185)
        self.setMaximumWidth(225)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(3)

        title = QLabel("RESULT TYPES")
        title.setObjectName("resultSectionTitle")
        layout.addWidget(title)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}

        self._add_section(layout, "GENERAL")
        self._add_button(layout, "overview", "Overview")
        self._add_button(layout, "deformation", "Deformed Shape")

        self._add_section(layout, "NODE RESULTS")
        self._add_button(layout, "displacement", "Nodal Displacements")
        self._add_button(layout, "reaction", "Support Reactions")

        self._add_section(layout, "ELEMENT FORCES")
        self._add_button(layout, "axial", "Axial Force (N)")
        self._add_button(layout, "shear", "Shear Force (V)")
        self._add_button(layout, "moment", "Bending Moment (M)")

        self._add_section(layout, "DATA")
        self._add_button(layout, "tables", "Result Tables")
        layout.addStretch(1)
        self.select_result_type("overview")

    def select_result_type(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)
            self.result_type_changed.emit(key)

    def _add_section(self, layout: QVBoxLayout, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("resultGroupLabel")
        layout.addWidget(label)

    def _add_button(self, layout: QVBoxLayout, key: str, text: str) -> None:
        button = QToolButton()
        button.setObjectName("resultTypeButton")
        button.setText(text)
        button.setCheckable(True)
        button.setToolButtonStyle(button.ToolButtonStyle.ToolButtonTextOnly)
        button.clicked.connect(
            lambda checked=False, result_key=key: self.result_type_changed.emit(result_key)
        )
        self._group.addButton(button)
        self.buttons[key] = button
        layout.addWidget(button)
