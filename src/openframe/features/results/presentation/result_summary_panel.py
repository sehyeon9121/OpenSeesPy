"""Result maxima, legend and selected-member local forces."""

import math
from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    AnalysisStatus,
    UnitSystem,
)
from openframe.features.results.diagrams import max_abs_value, member_diagrams


class ResultSummaryPanel(QFrame):
    member_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultSummaryPanel")
        self.setMinimumWidth(245)
        self.setMaximumWidth(310)
        self._result: AnalysisResult | None = None
        self._unit_system = DEFAULT_UNIT_SYSTEM

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("RESULT SUMMARY")
        title.setObjectName("resultSectionTitle")
        self.status_badge = QLabel("WAITING")
        self.status_badge.setObjectName("waitingBadge")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_badge)
        layout.addLayout(header)

        self.metric_values: dict[str, QLabel] = {}
        for key, title_text in (
            ("displacement", "MAX DISPLACEMENT"),
            ("moment", "MAX BENDING MOMENT"),
            ("shear", "MAX SHEAR FORCE"),
            ("axial", "MAX AXIAL FORCE"),
        ):
            layout.addWidget(self._metric_row(key, title_text))

        legend_title = QLabel("RESULT LEGEND")
        legend_title.setObjectName("resultGroupLabel")
        layout.addWidget(legend_title)
        self.legend = QProgressBar()
        self.legend.setObjectName("resultLegend")
        self.legend.setRange(0, 100)
        self.legend.setValue(100)
        self.legend.setTextVisible(False)
        layout.addWidget(self.legend)
        legend_labels = QHBoxLayout()
        legend_labels.addWidget(QLabel("MIN"))
        legend_labels.addStretch(1)
        legend_labels.addWidget(QLabel("MAX"))
        layout.addLayout(legend_labels)

        selected_title = QLabel("SELECTED ELEMENT")
        selected_title.setObjectName("resultGroupLabel")
        layout.addWidget(selected_title)
        self.member_selector = QComboBox()
        self.member_selector.setObjectName("resultMemberSelector")
        self.member_selector.currentIndexChanged.connect(self._member_selected)
        layout.addWidget(self.member_selector)

        self.end_force_table = QTableWidget(2, 4)
        self.end_force_table.setObjectName("resultEndForceTable")
        self.end_force_table.setVerticalHeaderLabels(("i", "j"))
        self.end_force_table.verticalHeader().setVisible(True)
        self.end_force_table.setMaximumHeight(108)
        layout.addWidget(self.end_force_table)

        details = QGridLayout()
        details.addWidget(QLabel("SYSTEM"), 0, 0)
        self.system_value = QLabel("LOCAL 2D")
        details.addWidget(self.system_value, 0, 1)
        details.addWidget(QLabel("DATA"), 1, 0)
        self.data_value = QLabel("END FORCES")
        details.addWidget(self.data_value, 1, 1)
        layout.addLayout(details)
        layout.addStretch(1)
        self._refresh()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self._refresh()

    def show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._fill_member_selector(sorted(result.element_results))
        self._refresh()

    def clear_result(self) -> None:
        """Drop the summarised result so a new model never shows the previous one."""
        self._result = None
        self._fill_member_selector(())
        self._refresh()

    def _fill_member_selector(self, element_tags: Sequence[int]) -> None:
        self.member_selector.blockSignals(True)
        self.member_selector.clear()
        for element_tag in element_tags:
            self.member_selector.addItem(f"Element {element_tag}", element_tag)
        self.member_selector.blockSignals(False)

    def select_member(self, element_tag: int) -> None:
        index = self.member_selector.findData(element_tag)
        if index >= 0 and index != self.member_selector.currentIndex():
            self.member_selector.blockSignals(True)
            self.member_selector.setCurrentIndex(index)
            self.member_selector.blockSignals(False)
            self._refresh_end_forces()

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
        self.metric_values[key] = value
        row_layout.addWidget(label)
        row_layout.addWidget(value)
        return row

    def _refresh(self) -> None:
        unit = self._unit_system
        self.end_force_table.setHorizontalHeaderLabels(
            ("END", f"N ({unit.force})", f"V ({unit.force})", f"M ({unit.moment})")
        )
        result = self._result
        if result is None or result.status != AnalysisStatus.COMPLETED:
            self.status_badge.setText("WAITING")
            self.metric_values["displacement"].setText(f"—  {unit.length}")
            self.metric_values["moment"].setText(f"—  {unit.moment}")
            self.metric_values["shear"].setText(f"—  {unit.force}")
            self.metric_values["axial"].setText(f"—  {unit.force}")
            self._refresh_end_forces()
            return

        self.status_badge.setText("COMPLETED")
        max_displacement = max(
            (
                math.hypot(
                    node.displacement[0] if len(node.displacement) > 0 else 0.0,
                    node.displacement[1] if len(node.displacement) > 1 else 0.0,
                )
                for node in result.node_results.values()
            ),
            default=0.0,
        )
        axial = []
        shear = []
        moment = []
        for element in result.element_results.values():
            try:
                diagrams = member_diagrams(element)
            except ValueError:
                continue
            axial.append(diagrams[0])
            shear.append(diagrams[1])
            moment.append(diagrams[2])

        self.metric_values["displacement"].setText(
            f"{max_displacement:.6g}  {unit.length}"
        )
        self.metric_values["moment"].setText(
            f"{max_abs_value(moment):.6g}  {unit.moment}"
        )
        self.metric_values["shear"].setText(
            f"{max_abs_value(shear):.6g}  {unit.force}"
        )
        self.metric_values["axial"].setText(
            f"{max_abs_value(axial):.6g}  {unit.force}"
        )
        self._refresh_end_forces()

    def _member_selected(self) -> None:
        self._refresh_end_forces()
        element_tag = self.member_selector.currentData()
        if element_tag is not None:
            self.member_changed.emit(int(element_tag))

    def _refresh_end_forces(self) -> None:
        for row in range(2):
            self.end_force_table.setItem(row, 0, QTableWidgetItem("i" if row == 0 else "j"))
            for column in range(1, 4):
                self.end_force_table.setItem(row, column, QTableWidgetItem("—"))

        if self._result is None:
            return
        element_tag = self.member_selector.currentData()
        element = self._result.element_results.get(element_tag)
        if element is None or len(element.local_forces) < 6:
            return
        values = element.local_forces
        for row, offset in ((0, 0), (1, 3)):
            for column in range(3):
                self.end_force_table.setItem(
                    row,
                    column + 1,
                    QTableWidgetItem(f"{values[offset + column]:.5g}"),
                )
