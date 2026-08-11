"""Shell container for MODEL's analysis-type picker and contextual model inspection.

The full analysis settings (solver, nonlinear dialog) live in SETUP now
(``app.shell.setup_workspace.SetupWorkspace``) - this sidebar only shows the
lightweight ``AnalysisTypeSelector``, bound to the same ``AnalysisConfigStore``
so picking a kind here never disagrees with what SETUP shows."""

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)
from openframe.features.analysis.presentation.analysis_type_selector import (
    AnalysisTypeSelector,
)
from openframe.features.model.presentation.model_inspector_panel import (
    ModelInspectorPanel,
)


class AnalysisResultsSidebar(QFrame):
    def __init__(
        self, config_store: AnalysisConfigStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("analysisSidebar")
        self.setMinimumWidth(270)
        self.setMaximumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.type_selector = AnalysisTypeSelector(config_store)
        self.inspector = ModelInspectorPanel()
        layout.addWidget(self.type_selector)
        layout.addWidget(self.inspector, 1)
