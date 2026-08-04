"""BMD, SFD, AFD and nodal-displacement result panel."""

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
from openframe.features.results.diagrams.base import MemberDiagram
from openframe.features.results.presentation.diagram_plot import DiagramPlot


class ResultsPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultsPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        result_header = QFrame()
        result_header.setObjectName("panelHeader")
        result_header_layout = QHBoxLayout(result_header)
        result_header_layout.setContentsMargins(14, 9, 14, 9)
        result_header_layout.addWidget(QLabel("ANALYSIS RESULTS"))
        result_header_layout.addStretch(1)
        self.status_badge = QLabel("WAITING")
        self.status_badge.setObjectName("waitingBadge")
        result_header_layout.addWidget(self.status_badge)
        layout.addWidget(result_header)

        result_content = QFrame()
        result_content.setObjectName("rightSection")
        result_layout = QVBoxLayout(result_content)
        result_layout.setContentsMargins(12, 10, 12, 12)

        member_row = QHBoxLayout()
        member_row_label = QLabel("MEMBER")
        member_row_label.setObjectName("fieldLabel")
        member_row.addWidget(member_row_label)
        self.member_selector = QComboBox()
        self.member_selector.setObjectName("memberSelector")
        self.member_selector.currentIndexChanged.connect(self._show_selected_member_diagram)
        member_row.addWidget(self.member_selector, 1)
        result_layout.addLayout(member_row)

        self.result_tabs = QTabWidget()
        self.result_tabs.setObjectName("resultTabs")
        self.result_values: dict[str, QLabel] = {}
        self.diagram_plots: dict[str, DiagramPlot] = {}
        self._diagrams_by_kind: dict[str, dict[int, MemberDiagram]] = {
            "axial": {},
            "shear": {},
            "moment": {},
        }
        for key, label, title in (
            ("moment", "BMD", "MAX. BENDING MOMENT"),
            ("shear", "SFD", "MAX. SHEAR FORCE"),
            ("axial", "AFD", "MAX. AXIAL FORCE"),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(8, 12, 8, 12)
            result_label = QLabel(title)
            result_label.setObjectName("resultLabel")
            value = QLabel("—")
            value.setObjectName("resultValue")
            self.result_values[key] = value
            plot = DiagramPlot()
            self.diagram_plots[key] = plot
            page_layout.addWidget(result_label)
            page_layout.addWidget(value)
            page_layout.addWidget(plot, 1)
            self.result_tabs.addTab(page, label)
        result_layout.addWidget(self.result_tabs)

        displacement_label = QLabel("NODAL DISPLACEMENTS")
        displacement_label.setObjectName("fieldLabel")
        result_layout.addWidget(displacement_label)
        self.displacement_table = QTableWidget(0, 3)
        self.displacement_table.setHorizontalHeaderLabels(("NODE", "UX", "UY"))
        self.displacement_table.verticalHeader().setVisible(False)
        self.displacement_table.setMinimumHeight(132)
        result_layout.addWidget(self.displacement_table)
        layout.addWidget(result_content, 1)
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self.set_unit_system(DEFAULT_UNIT_SYSTEM)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self.result_values["moment"].setText(f"—  {unit_system.moment}")
        self.result_values["shear"].setText(f"—  {unit_system.force}")
        self.result_values["axial"].setText(f"—  {unit_system.force}")
        self.displacement_table.setHorizontalHeaderLabels(
            ("NODE", f"UX ({unit_system.length})", f"UY ({unit_system.length})")
        )

    def select_result(self, key: str) -> None:
        indexes = {"moment": 0, "shear": 1, "axial": 2}
        if key in indexes:
            self.result_tabs.setCurrentIndex(indexes[key])

    def show_result(self, result: AnalysisResult) -> None:
        self.status_badge.setText(
            "COMPLETED" if result.status == AnalysisStatus.COMPLETED else "FAILED"
        )

        nodes = sorted(result.node_results.values(), key=lambda item: item.node_tag)
        self.displacement_table.setRowCount(len(nodes))
        for row, node in enumerate(nodes):
            ux = node.displacement[0] if len(node.displacement) > 0 else 0.0
            uy = node.displacement[1] if len(node.displacement) > 1 else 0.0
            self.displacement_table.setItem(row, 0, QTableWidgetItem(str(node.node_tag)))
            self.displacement_table.setItem(row, 1, QTableWidgetItem(f"{ux:.6g}"))
            self.displacement_table.setItem(row, 2, QTableWidgetItem(f"{uy:.6g}"))

        if result.status != AnalysisStatus.COMPLETED:
            self._diagrams_by_kind = {"axial": {}, "shear": {}, "moment": {}}
            self.member_selector.clear()
            for plot in self.diagram_plots.values():
                plot.set_diagram(None)
            self.set_unit_system(self._unit_system)
            return

        axial_diagrams = []
        shear_diagrams = []
        moment_diagrams = []
        for element in sorted(result.element_results.values(), key=lambda item: item.element_tag):
            try:
                axial_diagram, shear_diagram, moment_diagram = member_diagrams(element)
            except ValueError:
                continue
            axial_diagrams.append(axial_diagram)
            shear_diagrams.append(shear_diagram)
            moment_diagrams.append(moment_diagram)

        unit_system = self._unit_system
        self.result_values["axial"].setText(
            f"{max_abs_value(axial_diagrams):.6g}  {unit_system.force}"
        )
        self.result_values["shear"].setText(
            f"{max_abs_value(shear_diagrams):.6g}  {unit_system.force}"
        )
        self.result_values["moment"].setText(
            f"{max_abs_value(moment_diagrams):.6g}  {unit_system.moment}"
        )

        self._diagrams_by_kind = {
            "axial": {diagram.element_tag: diagram for diagram in axial_diagrams},
            "shear": {diagram.element_tag: diagram for diagram in shear_diagrams},
            "moment": {diagram.element_tag: diagram for diagram in moment_diagrams},
        }

        self.member_selector.blockSignals(True)
        self.member_selector.clear()
        for element_tag in self._diagrams_by_kind["moment"]:
            self.member_selector.addItem(f"Element {element_tag}", element_tag)
        self.member_selector.blockSignals(False)

        self._show_selected_member_diagram()

    def _show_selected_member_diagram(self) -> None:
        element_tag = self.member_selector.currentData()
        for key, plot in self.diagram_plots.items():
            diagram = self._diagrams_by_kind[key].get(element_tag)
            unit = self._unit_system.moment if key == "moment" else self._unit_system.force
            plot.set_diagram(diagram, unit)
