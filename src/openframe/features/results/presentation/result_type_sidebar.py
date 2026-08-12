"""Post-processing result-type navigation."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
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
        self.setMinimumWidth(210)
        self.setMaximumWidth(250)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 11, 10, 11)
        layout.setSpacing(8)

        title = QLabel("RESULT TYPES")
        title.setObjectName("resultSectionTitle")
        layout.addWidget(title)
        description = QLabel("Choose the engineering quantity to display in the viewport.")
        description.setObjectName("resultTypeDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}

        self._add_group(
            layout,
            "SUMMARY",
            "Overall model response",
            (("overview", "Overview"),),
        )
        self._add_group(
            layout,
            "SHAPE & NODE RESPONSE",
            "Geometry, movement and restraints",
            (
                ("deformation", "Deformed Shape"),
                ("displacement", "Nodal Displacements"),
                ("reaction", "Support Reactions"),
            ),
        )
        self._add_group(
            layout,
            "MEMBER FORCE DIAGRAMS",
            "Whole-frame local force plots",
            (
                ("axial", "N    Axial Force"),
                ("shear", "V    Shear Force"),
                ("moment", "M    Bending Moment"),
            ),
        )
        self._add_group(
            layout,
            "NONLINEAR RESPONSE",
            "Incremental pushover history",
            (("pushover", "Pushover Curve"),),
        )
        self._add_group(
            layout,
            "DATA",
            "Numerical verification",
            (("tables", "Result Tables"),),
        )
        self._add_group(
            layout,
            "MODAL RESPONSE",
            "Natural mode shapes",
            (("mode_shapes", "Mode Shapes"),),
        )
        self._add_group(
            layout,
            "TIME HISTORY RESPONSE",
            "Displacement/rotation vs. time",
            (("time_history", "Response History"),),
        )
        layout.addStretch(1)
        self.select_result_type("overview")

    def select_result_type(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)
            self.result_type_changed.emit(key)

    def _add_group(
        self,
        layout: QVBoxLayout,
        title: str,
        hint: str,
        entries: tuple[tuple[str, str], ...],
    ) -> None:
        group = QFrame()
        group.setObjectName("resultTypeGroup")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(7, 7, 7, 7)
        group_layout.setSpacing(2)

        heading = QHBoxLayout()
        heading.setContentsMargins(2, 0, 2, 0)
        name = QLabel(title)
        name.setObjectName("resultTypeGroupTitle")
        count = QLabel(str(len(entries)))
        count.setObjectName("resultTypeGroupCount")
        heading.addWidget(name)
        heading.addStretch(1)
        heading.addWidget(count)
        group_layout.addLayout(heading)

        description = QLabel(hint)
        description.setObjectName("resultTypeGroupHint")
        group_layout.addWidget(description)
        for key, text in entries:
            self._add_button(group_layout, key, text)
        layout.addWidget(group)

    def _add_button(self, layout: QVBoxLayout, key: str, text: str) -> None:
        button = QToolButton()
        button.setObjectName("resultTypeButton")
        button.setText(text)
        button.setCheckable(True)
        button.setProperty("forceDiagram", key in {"axial", "shear", "moment"})
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.clicked.connect(
            lambda checked=False, result_key=key: self.result_type_changed.emit(result_key)
        )
        self._group.addButton(button)
        self.buttons[key] = button
        layout.addWidget(button)
