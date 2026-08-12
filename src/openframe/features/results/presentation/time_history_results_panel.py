"""Time History RESULTS: a Response History / Animation toggle over the same
AnalysisResult - no separate result storage, both children read the one
result this wrapper hands them via show_result()."""

from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisResult, StructuralModel, UnitSystem
from openframe.features.results.presentation.time_history_animation_panel import (
    TimeHistoryAnimationPanel,
)
from openframe.features.results.presentation.time_history_panel import TimeHistoryPanel


class TimeHistoryResultsPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timeHistoryResultsPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(14, 10, 14, 0)
        tab_row.setSpacing(6)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self.response_history_tab = QPushButton("Response History")
        self.animation_tab = QPushButton("Animation")
        for button in (self.response_history_tab, self.animation_tab):
            button.setObjectName("resultViewTabButton")
            button.setCheckable(True)
            self._tab_group.addButton(button)
            tab_row.addWidget(button)
        tab_row.addStretch(1)
        self.response_history_tab.setChecked(True)
        layout.addLayout(tab_row)

        self.content_stack = QStackedWidget()
        self.response_history_panel = TimeHistoryPanel()
        self.animation_panel = TimeHistoryAnimationPanel()
        self.content_stack.addWidget(self.response_history_panel)
        self.content_stack.addWidget(self.animation_panel)
        layout.addWidget(self.content_stack, 1)

        self.response_history_tab.clicked.connect(lambda: self.content_stack.setCurrentIndex(0))
        self.animation_tab.clicked.connect(lambda: self.content_stack.setCurrentIndex(1))
        # Leaving the Animation sub-tab (for Response History, or this whole
        # result type being swapped out from the outside) must stop the timer -
        # see TimeHistoryAnimationPanel's own timer-lifecycle notes.
        self.content_stack.currentChanged.connect(self._on_tab_changed)
        # Phase 3-J: the only link between the two children - neither panel
        # reaches into the other's widgets directly, this wrapper is the one
        # place "go to this step" turns into an Animation call + tab switch.
        self.response_history_panel.go_to_step_requested.connect(self._go_to_step)

    def _on_tab_changed(self, index: int) -> None:
        if index != self.content_stack.indexOf(self.animation_panel):
            self.animation_panel.pause_animation()

    def _go_to_step(self, step_index: int) -> None:
        self.animation_panel.set_current_step(step_index)
        self.animation_tab.setChecked(True)
        self.content_stack.setCurrentWidget(self.animation_panel)

    def set_model(self, model: StructuralModel) -> None:
        self.response_history_panel.set_model(model)
        self.animation_panel.set_model(model)

    def show_result(self, result: AnalysisResult) -> None:
        self.response_history_panel.show_result(result)
        self.animation_panel.show_result(result)

    def clear_result(self) -> None:
        self.response_history_panel.clear_result()
        self.animation_panel.clear_result()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.response_history_panel.set_unit_system(unit_system)
        self.animation_panel.set_unit_system(unit_system)
