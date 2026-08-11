"""Stitch-inspired, extensible structural post-processing workspace."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisKind,
    AnalysisResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.presentation.result_summary_panel import (
    ResultSummaryPanel,
)
from openframe.features.results.presentation.result_tables_panel import (
    ResultTablesPanel,
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
        self.summary = ResultSummaryPanel()
        self.tables_panel = ResultTablesPanel()

        # The graphics/graph view and its summary sidebar make no sense once the
        # user has switched to the tables result type: a Midas-style data export
        # wants the full width for itself, not a strip beside a 3D viewport.
        normal_page = QSplitter(Qt.Orientation.Horizontal)
        normal_page.setObjectName("resultNormalSplitter")
        normal_page.setChildrenCollapsible(False)
        normal_page.addWidget(self.viewport)
        normal_page.addWidget(self.summary)
        normal_page.setStretchFactor(0, 1)
        normal_page.setStretchFactor(1, 0)
        normal_page.setSizes((875, 275))

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(normal_page)
        self.content_stack.addWidget(self.tables_panel)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("resultWorkspaceSplitter")
        body.setChildrenCollapsible(False)
        body.addWidget(self.result_types)
        body.addWidget(self.content_stack)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes((230, 1150))
        layout.addWidget(body, 1)

        self.result_types.result_type_changed.connect(self._set_result_type)
        self.set_unit_system(DEFAULT_UNIT_SYSTEM)
        self._set_result_type("overview")

    def set_model(self, model: StructuralModel) -> None:
        # A different model invalidates whatever the previous run produced.
        self.clear_result()
        self.toolbar.set_dimension(model.ndm)
        self.viewport.set_model(model)
        self.summary.set_model(model)
        self.tables_panel.set_model(model)

    def show_result(self, result: AnalysisResult) -> None:
        self.viewport.show_result(result)
        self.summary.show_result(result)
        self.tables_panel.show_result(result)

    def clear_result(self) -> None:
        """Return the workspace to its waiting state, keeping the drawn model."""
        self.viewport.clear_result()
        self.summary.clear_result()
        self.tables_panel.clear_result()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.viewport.set_unit_system(unit_system)
        self.summary.set_unit_system(unit_system)
        self.tables_panel.set_unit_system(unit_system)

    def set_analysis_kind(self, kind: AnalysisKind) -> None:
        self.toolbar.set_analysis_kind(kind)

    def set_result_type(self, result_type: str) -> None:
        """Select a result type as if the user had clicked it in the sidebar."""
        button = self.result_types.buttons.get(result_type)
        if button is not None:
            button.setChecked(True)
        self._set_result_type(result_type)

    def _set_result_type(self, result_type: str) -> None:
        if result_type == "tables":
            self.content_stack.setCurrentWidget(self.tables_panel)
            return
        self.content_stack.setCurrentWidget(self.content_stack.widget(0))
        self.viewport.set_result_type(result_type)
        self.summary.set_result_type(result_type)
