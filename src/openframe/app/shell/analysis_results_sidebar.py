"""Shell container for analysis settings and contextual model inspection."""

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from openframe.features.analysis.presentation.analysis_settings_panel import (
    AnalysisSettingsPanel,
)
from openframe.features.model.presentation.model_inspector_panel import (
    ModelInspectorPanel,
)


class AnalysisResultsSidebar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisSidebar")
        self.setMinimumWidth(270)
        self.setMaximumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.settings = AnalysisSettingsPanel()
        self.inspector = ModelInspectorPanel()
        layout.addWidget(self.settings)
        layout.addWidget(self.inspector, 1)
