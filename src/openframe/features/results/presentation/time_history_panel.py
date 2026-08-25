"""Response-history (value vs. time) view for a selected node/dof/response.

Follows the same set_model/show_result/clear_result/set_unit_system pattern
every other ResultsWorkspace sub-panel uses, always kept in sync regardless of
whether this panel is the one currently visible.

No separate presentation store: every redraw reads directly from
``AnalysisResult.time_history`` (one ``TimeHistoryStep`` per recorded step,
one ``NodeResult`` per node) - the same time-indexed, per-node structure
Phase 3-I's Animation also reads from.

Phase 3-J connects this panel to Animation without either panel reaching into
the other directly: this panel only ever emits ``go_to_step_requested`` with a
step index (from "Go to Peak" or a graph click's nearest step, both resolved
via the shared ``nearest_step_index`` helper) - ``TimeHistoryResultsPanel``
is the one place that turns that into an Animation call.
"""

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

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.presentation.node_picker_dialog import (
    SearchableNodeSelector,
)
from openframe.features.results.presentation.time_history_curve_view import (
    TimeHistoryCurveView,
)
from openframe.features.results.time_history_navigation import nearest_step_index

#: dof labels by ndm, matching the order OpenSeesPy reports node results in -
#: same convention AnalysisSettingsPanel's CONTROL DOF combo already uses.
_DOF_LABELS_2D = ("UX", "UY", "RZ")
_DOF_LABELS_3D = ("UX", "UY", "UZ", "RX", "RY", "RZ")

#: (combo label, NodeResult field name). Velocity/acceleration are relative to
#: the ground (see time_history_solver.py) - never labeled as absolute/total.
_RESPONSE_KINDS: tuple[tuple[str, str], ...] = (
    ("Displacement", "displacement"),
    ("Velocity", "velocity"),
    ("Acceleration", "acceleration"),
    ("Reaction", "reaction"),
)

_SUMMARY_ROWS: tuple[tuple[str, str], ...] = (
    ("max", "MAX"),
    ("min", "MIN"),
    ("abs_max", "ABS MAX"),
    ("abs_max_time", "TIME @ ABS MAX"),
)


class TimeHistoryPanel(QFrame):
    #: A step index to jump Animation to - from "Go to Peak" or a graph
    #: click's nearest step. TimeHistoryResultsPanel listens for this; this
    #: panel never touches TimeHistoryAnimationPanel directly.
    go_to_step_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timeHistoryPanel")
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._result_times: tuple[float, ...] = ()
        self._unit_system = DEFAULT_UNIT_SYSTEM
        #: The currently displayed curve's own abs-max step, in
        #: self._result.time_history's index space (None when there is no
        #: valid data to peek at - never defaulted to 0, see Phase 3-J spec).
        self._current_peak_step_index: int | None = None
        #: Set by a graph click; independent of the peak above.
        self._clicked_step_index: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("TIME HISTORY RESULTS")
        title.setObjectName("resultSectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("RESPONSE"))
        self.response_selector = QComboBox()
        self.response_selector.setObjectName("timeHistoryResponseSelector")
        for label, field in _RESPONSE_KINDS:
            self.response_selector.addItem(label, field)
        self.response_selector.currentIndexChanged.connect(self._on_selector_changed)
        picker_row.addWidget(self.response_selector, 1)
        picker_row.addWidget(QLabel("NODE"))
        self.node_selector = SearchableNodeSelector()
        self.node_selector.setObjectName("timeHistoryNodeSelector")
        self.node_selector.currentIndexChanged.connect(self._on_selector_changed)
        picker_row.addWidget(self.node_selector, 1)
        picker_row.addWidget(QLabel("DOF"))
        self.dof_selector = QComboBox()
        self.dof_selector.setObjectName("timeHistoryDofSelector")
        self.dof_selector.currentIndexChanged.connect(self._on_selector_changed)
        picker_row.addWidget(self.dof_selector, 1)
        self.go_to_peak_button = QPushButton("Go to Peak")
        self.go_to_peak_button.setObjectName("resultActionButton")
        self.go_to_peak_button.setEnabled(False)
        self.go_to_peak_button.clicked.connect(self._go_to_peak_clicked)
        picker_row.addWidget(self.go_to_peak_button)
        layout.addLayout(picker_row)

        self.status_note = QLabel("")
        self.status_note.setObjectName("secondaryText")
        self.status_note.setWordWrap(True)
        self.status_note.setVisible(False)
        layout.addWidget(self.status_note)

        self.curve_view = TimeHistoryCurveView()
        self.curve_view.time_clicked.connect(self._on_graph_time_clicked)
        layout.addWidget(self.curve_view, 1)

        selection_row = QHBoxLayout()
        self.selected_time_label = QLabel("")
        self.selected_time_label.setObjectName("secondaryText")
        self.selected_time_label.setVisible(False)
        selection_row.addWidget(self.selected_time_label)
        self.view_in_animation_button = QPushButton("View in Animation")
        self.view_in_animation_button.setObjectName("resultActionButton")
        self.view_in_animation_button.setVisible(False)
        self.view_in_animation_button.clicked.connect(self._view_in_animation_clicked)
        selection_row.addWidget(self.view_in_animation_button)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        self.summary_values: dict[str, QLabel] = {}
        for key, title_text in _SUMMARY_ROWS:
            summary_row.addWidget(self._metric_row(key, title_text))
        layout.addLayout(summary_row)

    def _metric_row(self, key: str, title: str) -> QFrame:
        row = QFrame()
        row.setObjectName("resultMetricRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(9, 6, 9, 6)
        row_layout.setSpacing(1)
        label = QLabel(title)
        label.setObjectName("resultMetricLabel")
        value = QLabel("—")
        value.setObjectName("resultMetricValue")
        self.summary_values[key] = value
        row_layout.addWidget(label)
        row_layout.addWidget(value)
        return row

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self._redraw()

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        full_labels = _DOF_LABELS_3D if model.ndm == 3 else _DOF_LABELS_2D
        self.dof_selector.blockSignals(True)
        self.dof_selector.clear()
        for index, label in enumerate(full_labels[: model.ndf]):
            self.dof_selector.addItem(label, index)
        self.dof_selector.blockSignals(False)

    def show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._result_times = tuple(step.time for step in result.time_history)
        self._clear_click_selection()
        self._fill_node_selector()
        self._redraw()

    def clear_result(self) -> None:
        self._result = None
        self._result_times = ()
        self._clear_click_selection()
        self._fill_node_selector()
        self.curve_view.set_empty_message("시간이력해석을 먼저 실행하세요")
        self._redraw()

    def _clear_click_selection(self) -> None:
        self._clicked_step_index = None
        self.selected_time_label.setVisible(False)
        self.view_in_animation_button.setVisible(False)

    def _fill_node_selector(self) -> None:
        previous = self.node_selector.currentData()
        self.node_selector.blockSignals(True)
        self.node_selector.clear()
        if self._result is not None and self._result.time_history:
            node_tags = sorted(self._result.time_history[0].node_results)
            for node_tag in node_tags:
                self.node_selector.addItem(f"Node {node_tag}", node_tag)
            if previous is not None:
                index = self.node_selector.findData(previous)
                if index >= 0:
                    self.node_selector.setCurrentIndex(index)
        self.node_selector.blockSignals(False)

    def _response_unit(self, response_field: str, *, is_rotation: bool) -> str:
        length = self._unit_system.length
        if response_field == "displacement":
            return "rad" if is_rotation else length
        if response_field == "velocity":
            return "rad/s" if is_rotation else f"{length}/s"
        if response_field == "acceleration":
            return "rad/s²" if is_rotation else f"{length}/s²"
        if response_field == "reaction":
            return self._unit_system.moment if is_rotation else self._unit_system.force
        return ""

    def _empty_reason(self, response_field: str, node_tag: int | None) -> str:
        if response_field == "reaction":
            return f"Node {node_tag}은(는) 지점이 아니므로 반력 데이터가 없습니다."
        return "선택한 절점/자유도에는 표시할 데이터가 없습니다."

    def _clear_summary(self) -> None:
        for value in self.summary_values.values():
            value.setText("—")

    def _on_selector_changed(self) -> None:
        # A different response/node/dof is a different curve entirely - a
        # click position picked on the previous one no longer means anything.
        self._clear_click_selection()
        self._redraw()

    def _go_to_peak_clicked(self) -> None:
        if self._current_peak_step_index is not None:
            self.go_to_step_requested.emit(self._current_peak_step_index)

    def _view_in_animation_clicked(self) -> None:
        if self._clicked_step_index is not None:
            self.go_to_step_requested.emit(self._clicked_step_index)

    def _on_graph_time_clicked(self, time: float) -> None:
        if not self._result_times:
            return
        index = nearest_step_index(self._result_times, time)
        self._clicked_step_index = index
        actual_time = self._result_times[index]
        self.selected_time_label.setText(f"Selected: {actual_time:.3f} s (Step {index})")
        self.selected_time_label.setVisible(True)
        self.view_in_animation_button.setVisible(True)
        self._redraw()

    def _redraw(self) -> None:
        self.status_note.setVisible(False)
        self.go_to_peak_button.setEnabled(False)
        self._current_peak_step_index = None
        if self._result is None or not self._result.time_history:
            self.curve_view.set_series((), (), y_label="")
            self._clear_summary()
            return
        node_tag = self.node_selector.currentData()
        dof_index = self.dof_selector.currentData()
        response_field = self.response_selector.currentData()
        if node_tag is None or dof_index is None or response_field is None:
            self.curve_view.set_series((), (), y_label="")
            self._clear_summary()
            return

        times: list[float] = []
        values: list[float] = []
        for step in self._result.time_history:
            node = step.node_results.get(node_tag)
            if node is None:
                continue
            series = getattr(node, response_field)
            if dof_index >= len(series):
                continue
            times.append(step.time)
            values.append(series[dof_index])

        dof_label = self.dof_selector.currentText()
        is_rotation = dof_label.startswith("R")
        unit = self._response_unit(response_field, is_rotation=is_rotation)
        response_label = self.response_selector.currentText()

        if not values:
            self.curve_view.set_series((), (), y_label="")
            self.curve_view.set_empty_message(self._empty_reason(response_field, node_tag))
            self._clear_summary()
            return

        max_value = max(values)
        min_value = min(values)
        abs_max_index = max(range(len(values)), key=lambda index: abs(values[index]))
        abs_max_value = abs(values[abs_max_index])
        abs_max_time = times[abs_max_index]

        # abs_max_index indexes the locally-filtered times/values lists, which
        # can skip steps (e.g. a node missing from an early step) - resolving
        # through the shared helper against the full result's own times is
        # what actually guarantees this points at the right time_history entry.
        self._current_peak_step_index = nearest_step_index(self._result_times, abs_max_time)
        self.go_to_peak_button.setEnabled(True)

        self.summary_values["max"].setText(f"{max_value:+.4g} {unit}")
        self.summary_values["min"].setText(f"{min_value:+.4g} {unit}")
        self.summary_values["abs_max"].setText(f"{abs_max_value:.4g} {unit}")
        self.summary_values["abs_max_time"].setText(f"{abs_max_time:.3g} s")

        if response_field == "acceleration":
            self.status_note.setText(
                "Relative acceleration (relative to the ground motion) - this "
                "solver does not compute absolute/total acceleration."
            )
            self.status_note.setVisible(True)

        selected_time: float | None = None
        selected_point: tuple[float, float] | None = None
        selected_label = ""
        if self._clicked_step_index is not None:
            selected_step = self._result.time_history[self._clicked_step_index]
            selected_time = selected_step.time
            selected_node = selected_step.node_results.get(node_tag)
            selected_series = (
                getattr(selected_node, response_field) if selected_node is not None else ()
            )
            if dof_index < len(selected_series):
                selected_value = selected_series[dof_index]
                selected_point = (selected_time, selected_value)
                selected_label = (
                    f"t = {selected_time:.3f} s · {response_label} {dof_label} "
                    f"= {selected_value:+.4g} {unit}"
                )
                self.selected_time_label.setText(
                    f"Selected: {selected_time:.3f} s (Step {self._clicked_step_index})"
                    f"  ·  {response_label} {dof_label}: {selected_value:+.4g} {unit}"
                )
            else:
                selected_label = f"t = {selected_time:.3f} s · Value unavailable"
                self.selected_time_label.setText(
                    f"Selected: {selected_time:.3f} s "
                    f"(Step {self._clicked_step_index}) · Value unavailable"
                )
        self.curve_view.set_empty_message("시간이력해석을 먼저 실행하세요")
        self.curve_view.set_series(
            tuple(times),
            tuple(values),
            y_label=f"{response_label} {dof_label} [{unit}]",
            marker=(abs_max_time, values[abs_max_index]),
            marker_label=f"Abs Max {abs_max_value:.3g} {unit} @ {abs_max_time:.2f}s",
            selected_time=selected_time,
            selected_point=selected_point,
            selected_label=selected_label,
        )
