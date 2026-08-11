"""Response-history (value vs. time) view for a selected node/dof.

Follows the same set_model/show_result/clear_result/set_unit_system pattern
every other ResultsWorkspace sub-panel uses, always kept in sync regardless of
whether this panel is the one currently visible.
"""

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.presentation.time_history_curve_view import (
    TimeHistoryCurveView,
)

#: dof labels by ndm, matching the order OpenSeesPy reports node results in -
#: same convention AnalysisSettingsPanel's CONTROL DOF combo already uses.
_DOF_LABELS_2D = ("UX", "UY", "RZ")
_DOF_LABELS_3D = ("UX", "UY", "UZ", "RX", "RY", "RZ")


class TimeHistoryPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timeHistoryPanel")
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._unit_system = DEFAULT_UNIT_SYSTEM

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("TIME HISTORY RESPONSE")
        title.setObjectName("resultSectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        layout.addLayout(header)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("NODE"))
        self.node_selector = QComboBox()
        self.node_selector.setObjectName("timeHistoryNodeSelector")
        self.node_selector.currentIndexChanged.connect(self._redraw)
        picker_row.addWidget(self.node_selector, 1)
        picker_row.addWidget(QLabel("DOF"))
        self.dof_selector = QComboBox()
        self.dof_selector.setObjectName("timeHistoryDofSelector")
        self.dof_selector.currentIndexChanged.connect(self._redraw)
        picker_row.addWidget(self.dof_selector, 1)
        layout.addLayout(picker_row)

        self.curve_view = TimeHistoryCurveView()
        layout.addWidget(self.curve_view, 1)

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
        self._fill_node_selector()
        self._redraw()

    def clear_result(self) -> None:
        self._result = None
        self._fill_node_selector()
        self.curve_view.set_empty_message("시간이력해석을 먼저 실행하세요")
        self._redraw()

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

    def _redraw(self) -> None:
        if self._result is None or not self._result.time_history:
            self.curve_view.set_series((), (), y_label="")
            return
        node_tag = self.node_selector.currentData()
        dof_index = self.dof_selector.currentData()
        if node_tag is None or dof_index is None:
            self.curve_view.set_series((), (), y_label="")
            return
        times: list[float] = []
        values: list[float] = []
        for step in self._result.time_history:
            node = step.node_results.get(node_tag)
            if node is None or dof_index >= len(node.displacement):
                continue
            times.append(step.time)
            values.append(node.displacement[dof_index])
        dof_label = self.dof_selector.currentText()
        is_rotation = dof_label.startswith("R")
        unit = "rad" if is_rotation else self._unit_system.length
        self.curve_view.set_empty_message("시간이력해석을 먼저 실행하세요")
        self.curve_view.set_series(
            tuple(times), tuple(values), y_label=f"{dof_label} [{unit}]"
        )
