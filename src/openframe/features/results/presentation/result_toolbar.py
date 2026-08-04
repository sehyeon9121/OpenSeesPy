"""Result-case controls shared by every post-processing mode."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisKind


class ResultToolbar(QFrame):
    export_requested = Signal()
    report_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultToolbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        self.result_case = self._add_selector(
            layout,
            "RESULT CASE",
            ("Linear Static 01", "Nonlinear Static (Future)", "Time History (Future)"),
        )
        self.load_case = self._add_selector(
            layout,
            "LOAD CASE",
            ("Default Pattern", "Load Combination (Future)"),
        )
        self.step = self._add_selector(
            layout,
            "STEP",
            ("Final", "Maximum", "Minimum", "Time Step (Future)"),
        )
        self.view_mode = self._add_selector(
            layout,
            "VIEW",
            ("2D Front", "3D Isometric (Future)"),
        )

        layout.addStretch(1)
        export_button = QPushButton("EXPORT DATA")
        export_button.setObjectName("resultSecondaryButton")
        export_button.clicked.connect(self.export_requested)
        report_button = QPushButton("GENERATE REPORT")
        report_button.setObjectName("resultPrimaryButton")
        report_button.clicked.connect(self.report_requested)
        layout.addWidget(export_button)
        layout.addWidget(report_button)

    def set_analysis_kind(self, kind: AnalysisKind) -> None:
        labels = {
            AnalysisKind.LINEAR_STATIC: "Linear Static 01",
            AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static (Future)",
            AnalysisKind.TIME_HISTORY: "Time History (Future)",
        }
        self.result_case.setCurrentText(labels[kind])

    @staticmethod
    def _add_selector(
        layout: QHBoxLayout,
        title: str,
        options: tuple[str, ...],
    ) -> QComboBox:
        field = QFrame()
        field.setObjectName("resultToolbarField")
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("resultToolbarLabel")
        selector = QComboBox()
        selector.setObjectName("resultToolbarSelector")
        selector.addItems(options)
        field_layout.addWidget(label)
        field_layout.addWidget(selector)
        layout.addWidget(field)
        return selector
