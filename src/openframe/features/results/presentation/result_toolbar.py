"""Result-case controls shared by every post-processing mode.

Kept deliberately small: this used to also carry a LOAD CASE selector, a
STEP selector, and EXPORT DATA/GENERATE REPORT buttons, none of which were
ever wired to anything anywhere in the app (no load-combination or analysis-
step feature exists to select between, and nothing implements an export or
report). A dropdown or button that does nothing when used is worse than not
having it - a first-time user has no way to tell "not implemented yet" apart
from "broken". What's left is RESULT CASE (a real, if read-only, status of
which analysis just ran) and VIEW (real, but only meaningful for 3D results).
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from openframe.core.domain import AnalysisKind


class ResultToolbar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultToolbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        self.result_case_field, self.result_case = self._add_display(layout, "RESULT CASE")
        self.result_case.setText("Linear Static 01")
        self.view_mode_field, self.view_mode = self._add_display(layout, "VIEW")
        self.view_mode.setText("2D Front")

        layout.addStretch(1)

    def set_dimension(self, ndm: int) -> None:
        """A 2D model has no isometric/orbit view to pick, so VIEW is just
        occupied-looking chrome in that case."""
        self.view_mode_field.setVisible(ndm == 3)

    def set_analysis_kind(self, kind: AnalysisKind) -> None:
        labels = {
            AnalysisKind.LINEAR_STATIC: "Linear Static 01",
            AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
            AnalysisKind.MODAL: "Modal (Eigenvalue)",
            AnalysisKind.TIME_HISTORY: "Time History",
            AnalysisKind.BUCKLING: "Elastic Buckling",
            AnalysisKind.RESPONSE_SPECTRUM: "Response Spectrum",
        }
        self.result_case.setText(labels[kind])

    @staticmethod
    def _add_display(layout: QHBoxLayout, title: str) -> tuple[QFrame, QLabel]:
        field = QFrame()
        field.setObjectName("resultToolbarField")
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("resultToolbarLabel")
        value = QLabel()
        value.setObjectName("resultToolbarValue")
        field_layout.addWidget(label)
        field_layout.addWidget(value)
        layout.addWidget(field)
        return field, value
