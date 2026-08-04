"""Stitch-inspired, extensible structural post-processing workspace."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QSplitter, QVBoxLayout, QWidget

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisKind,
    AnalysisResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.presentation.result_data_panel import ResultDataPanel
from openframe.features.results.presentation.result_summary_panel import (
    ResultSummaryPanel,
)
from openframe.features.results.presentation.result_toolbar import ResultToolbar
from openframe.features.results.presentation.result_type_sidebar import (
    ResultTypeSidebar,
)
from openframe.features.results.presentation.result_viewport import ResultViewport


class ResultsWorkspace(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultsWorkspace")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar = ResultToolbar()
        layout.addWidget(self.toolbar)

        self.result_types = ResultTypeSidebar()
        self.viewport = ResultViewport()
        self.data_panel = ResultDataPanel()
        self.summary = ResultSummaryPanel()

        center = QSplitter(Qt.Orientation.Vertical)
        center.setObjectName("resultCenterSplitter")
        center.setChildrenCollapsible(False)
        center.addWidget(self.viewport)
        center.addWidget(self.data_panel)
        center.setStretchFactor(0, 1)
        center.setStretchFactor(1, 0)
        center.setSizes((520, 225))

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("resultWorkspaceSplitter")
        body.setChildrenCollapsible(False)
        body.addWidget(self.result_types)
        body.addWidget(center)
        body.addWidget(self.summary)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        body.setSizes((230, 875, 275))
        layout.addWidget(body, 1)

        self.result_types.result_type_changed.connect(self._set_result_type)
        self.summary.member_changed.connect(self.data_panel.select_member)
        self.data_panel.member_changed.connect(self.summary.select_member)
        self.set_unit_system(DEFAULT_UNIT_SYSTEM)
        self._set_result_type("overview")

    def set_model(self, model: StructuralModel) -> None:
        # A different model invalidates whatever the previous run produced.
        self.clear_result()
        self.viewport.set_model(model)
        self.data_panel.set_model(model)

    def show_result(self, result: AnalysisResult) -> None:
        self.viewport.show_result(result)
        self.data_panel.show_result(result)
        self.summary.show_result(result)

    def clear_result(self) -> None:
        """Return the workspace to its waiting state, keeping the drawn model."""
        self.viewport.clear_result()
        self.data_panel.clear_result()
        self.summary.clear_result()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.viewport.set_unit_system(unit_system)
        self.data_panel.set_unit_system(unit_system)
        self.summary.set_unit_system(unit_system)

    def set_analysis_kind(self, kind: AnalysisKind) -> None:
        self.toolbar.set_analysis_kind(kind)

    def _set_result_type(self, result_type: str) -> None:
        self.viewport.set_result_type(result_type)
        self.data_panel.set_result_type(result_type)
