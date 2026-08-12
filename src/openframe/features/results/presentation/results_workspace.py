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
from openframe.features.results.presentation.time_history_results_panel import (
    TimeHistoryResultsPanel,
)


class ResultsWorkspace(QFrame):
    def __init__(
        self, parent: QWidget | None = None, *, compact_2d: bool = False
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resultsWorkspace")
        self.setProperty("compact2d", compact_2d)
        self._compact_2d = compact_2d
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar = ResultToolbar()
        self.toolbar.setVisible(not compact_2d)
        layout.addWidget(self.toolbar)

        self.result_types = ResultTypeSidebar(compact_2d=compact_2d)
        self.viewport = ResultViewport()
        self.summary = ResultSummaryPanel(compact_2d=compact_2d)
        self.tables_panel = ResultTablesPanel()
        self.time_history_results_panel = TimeHistoryResultsPanel()

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
        normal_page.setSizes((875, 300 if compact_2d else 275))

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(normal_page)
        self.content_stack.addWidget(self.tables_panel)
        self.content_stack.addWidget(self.time_history_results_panel)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("resultWorkspaceSplitter")
        body.setChildrenCollapsible(False)
        body.addWidget(self.result_types)
        body.addWidget(self.content_stack)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes((190 if compact_2d else 230, 1190 if compact_2d else 1150))
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
        self.time_history_results_panel.set_model(model)

    def show_result(self, result: AnalysisResult) -> None:
        self.viewport.show_result(result)
        self.summary.show_result(result)
        self.tables_panel.show_result(result)
        self.time_history_results_panel.show_result(result)

    def clear_result(self) -> None:
        """Return the workspace to its waiting state, keeping the drawn model."""
        self.viewport.clear_result()
        self.summary.clear_result()
        self.tables_panel.clear_result()
        self.time_history_results_panel.clear_result()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.viewport.set_unit_system(unit_system)
        self.summary.set_unit_system(unit_system)
        self.tables_panel.set_unit_system(unit_system)
        self.time_history_results_panel.set_unit_system(unit_system)

    def set_analysis_kind(self, kind: AnalysisKind) -> None:
        self.toolbar.set_analysis_kind(kind)

    def set_result_type(self, result_type: str) -> None:
        """Select a result type as if the user had clicked it in the sidebar."""
        button = self.result_types.buttons.get(result_type)
        if button is not None:
            button.setChecked(True)
        self._set_result_type(result_type)

    def _set_result_type(self, result_type: str) -> None:
        # Leaving Time History (to any other result type) must stop the
        # animation timer - see TimeHistoryAnimationPanel's timer-lifecycle
        # notes. A no-op if it was already paused or never started.
        if result_type != "time_history":
            self.time_history_results_panel.animation_panel.pause_animation()
        if result_type == "tables":
            self.content_stack.setCurrentWidget(self.tables_panel)
            return
        if result_type == "time_history":
            self.content_stack.setCurrentWidget(self.time_history_results_panel)
            return
        self.content_stack.setCurrentWidget(self.content_stack.widget(0))
        self.viewport.set_result_type(result_type)
        self.summary.set_result_type(result_type)
