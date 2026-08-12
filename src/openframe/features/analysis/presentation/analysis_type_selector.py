"""Lightweight MODEL-page widget: show the analysis type, then jump to SETUP.

Used to also offer the four analysis-kind buttons here, but SETUP's own
``AnalysisSettingsPanel`` asks the exact same question immediately afterward -
same store, same choice, just repeated. Choosing (and changing) the kind now
only happens in SETUP; this stays a read-only status plus a shortcut there,
so picking it in SETUP is still what MODEL's summary reflects.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from openframe.core.domain import AnalysisKind
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)

_KIND_LABELS = {
    AnalysisKind.LINEAR_STATIC: "Linear Static",
    AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
    AnalysisKind.MODAL: "Modal (Eigenvalue)",
    AnalysisKind.TIME_HISTORY: "Time History",
}


class AnalysisTypeSelector(QFrame):
    open_setup_requested = Signal()

    def __init__(self, config_store: AnalysisConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisTypeSelector")
        self.config_store = config_store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header("ANALYSIS PREPARATION"))

        body = QFrame()
        body.setObjectName("rightSection")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 14)
        body_layout.setSpacing(6)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("secondaryText")
        self.summary_label.setWordWrap(True)
        body_layout.addWidget(self.summary_label)

        self.open_setup_button = QPushButton("OPEN SETUP PAGE  →")
        self.open_setup_button.setObjectName("openSetupButton")
        self.open_setup_button.clicked.connect(self.open_setup_requested)
        body_layout.addSpacing(4)
        body_layout.addWidget(self.open_setup_button)
        body_layout.addStretch(1)
        layout.addWidget(body)

        self.config_store.kind_changed.connect(self._update_summary)
        self.config_store.options_changed.connect(self._update_summary)
        self._update_summary()

    def _update_summary(self) -> None:
        kind_label = _KIND_LABELS.get(self.config_store.kind, str(self.config_store.kind))
        solver = self.config_store.options.get("system", "BandGeneral")
        self.summary_label.setText(
            f"Selected: {kind_label}\nSolver: {solver}\n\nChange the analysis type on the SETUP page."
        )

    def _header(self, text: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panelHeader")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.addWidget(QLabel(text))
        return frame
