"""Graph, table and detail views for the active result quantity."""

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.diagrams import member_diagrams
from openframe.features.results.presentation.diagram_plot import DiagramPlot
from openframe.features.results.reactions import support_reactions


class ResultDataPanel(QFrame):
    member_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultDataPanel")
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._result_type = "overview"
        self._unit_system = DEFAULT_UNIT_SYSTEM

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        panel_header = QFrame()
        panel_header.setObjectName("resultDataHeader")
        header_layout = QHBoxLayout(panel_header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        self.quantity_label = QLabel("BENDING MOMENT (M)")
        self.quantity_label.setObjectName("resultDataTitle")
        header_layout.addWidget(self.quantity_label)
        header_layout.addStretch(1)
        self.graph_zoom_out = self._graph_tool_button("-", "그래프 축소")
        self.graph_zoom_in = self._graph_tool_button("+", "그래프 확대")
        self.graph_fit = self._graph_tool_button("FIT", "그래프 전체 맞춤")
        header_layout.addWidget(self.graph_zoom_out)
        header_layout.addWidget(self.graph_zoom_in)
        header_layout.addWidget(self.graph_fit)
        header_layout.addWidget(QLabel("ELEMENT"))
        self.member_selector = QComboBox()
        self.member_selector.setObjectName("resultDataMemberSelector")
        self.member_selector.setMaximumWidth(135)
        self.member_selector.currentIndexChanged.connect(self._member_selected)
        header_layout.addWidget(self.member_selector)
        layout.addWidget(panel_header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("workspaceResultTabs")

        graph_page = QWidget()
        graph_layout = QVBoxLayout(graph_page)
        graph_layout.setContentsMargins(8, 4, 8, 6)
        self.diagram_plot = DiagramPlot()
        self.graph_zoom_out.clicked.connect(self.diagram_plot.zoom_out)
        self.graph_zoom_in.clicked.connect(self.diagram_plot.zoom_in)
        self.graph_fit.clicked.connect(self.diagram_plot.fit_to_view)
        graph_layout.addWidget(self.diagram_plot)
        self.tabs.addTab(graph_page, "GRAPH")

        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(8, 6, 8, 6)
        self.result_table = QTableWidget(0, 4)
        self.result_table.setObjectName("workspaceResultTable")
        self.result_table.verticalHeader().setVisible(False)
        table_layout.addWidget(self.result_table)
        self.tabs.addTab(table_page, "TABLE")

        details_page = QWidget()
        details_layout = QVBoxLayout(details_page)
        details_layout.setContentsMargins(14, 10, 14, 10)
        self.details_text = QLabel(
            "Run an analysis to inspect result cases, increments, convergence notes, "
            "and selected entity details."
        )
        self.details_text.setWordWrap(True)
        self.details_text.setObjectName("resultDetailsText")
        details_layout.addWidget(self.details_text)
        details_layout.addStretch(1)
        self.tabs.addTab(details_page, "DETAILS")
        layout.addWidget(self.tabs, 1)

        self._refresh()

    @staticmethod
    def _graph_tool_button(text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("resultGraphToolButton")
        button.setText(text)
        button.setToolTip(tooltip)
        return button

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self._refresh()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self._refresh()

    def show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._fill_member_selector(sorted(result.element_results))
        self._refresh()

    def clear_result(self) -> None:
        """Drop the tabulated result so a new model never shows the previous one."""
        self._result = None
        self._fill_member_selector(())
        self._refresh()

    def _fill_member_selector(self, element_tags: Sequence[int]) -> None:
        self.member_selector.blockSignals(True)
        self.member_selector.clear()
        for element_tag in element_tags:
            self.member_selector.addItem(f"Element {element_tag}", element_tag)
        self.member_selector.blockSignals(False)

    def set_result_type(self, result_type: str) -> None:
        self._result_type = result_type
        if result_type == "tables":
            self.tabs.setCurrentIndex(1)
        self._refresh()

    def select_member(self, element_tag: int) -> None:
        index = self.member_selector.findData(element_tag)
        if index >= 0 and index != self.member_selector.currentIndex():
            self.member_selector.blockSignals(True)
            self.member_selector.setCurrentIndex(index)
            self.member_selector.blockSignals(False)
            self._refresh()

    def _member_selected(self) -> None:
        self._refresh()
        element_tag = self.member_selector.currentData()
        if element_tag is not None:
            self.member_changed.emit(int(element_tag))

    def _refresh(self) -> None:
        force_keys = {"axial": 0, "shear": 1, "moment": 2}
        diagram_key = self._result_type if self._result_type in force_keys else "moment"
        names = {
            "axial": "AXIAL FORCE (N)",
            "shear": "SHEAR FORCE (V)",
            "moment": "BENDING MOMENT (M)",
        }
        # The graph always plots a member force, but the header names what the table shows.
        self.quantity_label.setText(
            "SUPPORT REACTIONS" if self._result_type == "reaction" else names[diagram_key]
        )

        diagram = None
        element_tag = self.member_selector.currentData()
        if (
            self._result is not None
            and element_tag is not None
            and (self._model is None or self._model.ndm == 2)
        ):
            element = self._result.element_results.get(element_tag)
            if element is not None:
                try:
                    diagram = member_diagrams(element)[force_keys[diagram_key]]
                except ValueError:
                    diagram = None
        unit = (
            self._unit_system.moment
            if diagram_key == "moment"
            else self._unit_system.force
        )
        self.diagram_plot.set_diagram(diagram, unit)
        self._refresh_table()

        status = self._result.status.value if self._result is not None else "not_run"
        time_steps = len(self._result.time_points) if self._result is not None else 0
        self.details_text.setText(
            f"Analysis status: {status}\n"
            f"Active quantity: {self.quantity_label.text()}\n"
            f"Available time steps: {time_steps}\n"
            "The same panel will support nonlinear increments and time-history steps."
        )

    def _is_truss_model(self) -> bool:
        if self._model is None or not self._model.elements:
            return False
        return all(
            "truss" in element.element_type.lower()
            for element in self._model.elements.values()
        )

    def _refresh_truss_axial_table(self) -> None:
        """Member / i-j joints / axial force / 인장·압축·0부재 — what a 부재력 표
        for a truss actually needs, instead of the frame table's N/V/M-i columns
        (V and M are always zero for a two-force member, so they say nothing)."""
        unit = self._unit_system
        result = self._result
        model = self._model
        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(
            ("부재", "절점 (i-j)", f"축력 N ({unit.force})", "상태")
        )
        elements = (
            []
            if result is None or model is None
            else sorted(result.element_results.values(), key=lambda item: item.element_tag)
        )
        values = {}
        for element in elements:
            try:
                axial = member_diagrams(element)[0]
            except ValueError:
                continue
            values[element.element_tag] = axial.points[0].value
        noise_floor = max((abs(v) for v in values.values()), default=0.0) * 1.0e-9

        self.result_table.setRowCount(len(elements))
        for row, element in enumerate(elements):
            member = model.elements.get(element.element_tag)
            joints = f"{member.node_i}-{member.node_j}" if member is not None else "-"
            value = values.get(element.element_tag, 0.0)
            is_zero = abs(value) <= noise_floor
            status = "0부재" if is_zero else "인장" if value > 0.0 else "압축"
            for column, text in enumerate(
                (str(element.element_tag), joints, f"{value:.6g}", status)
            ):
                self.result_table.setItem(row, column, QTableWidgetItem(text))

    def _refresh_table(self) -> None:
        unit = self._unit_system
        result = self._result
        is_3d = self._model is not None and self._model.ndm == 3
        if self._result_type == "axial" and self._is_truss_model() and not is_3d:
            self._refresh_truss_axial_table()
            return
        if self._result_type in {"axial", "shear", "moment"}:
            if is_3d:
                self.result_table.setColumnCount(7)
                self.result_table.setHorizontalHeaderLabels(
                    (
                        "ELEMENT",
                        f"N-i ({unit.force})",
                        f"Vy-i ({unit.force})",
                        f"Vz-i ({unit.force})",
                        f"T-i ({unit.moment})",
                        f"My-i ({unit.moment})",
                        f"Mz-i ({unit.moment})",
                    )
                )
                elements = [] if result is None else sorted(
                    result.element_results.values(), key=lambda item: item.element_tag
                )
                self.result_table.setRowCount(len(elements))
                for row, element in enumerate(elements):
                    values = (*element.local_forces, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
                    for column, value in enumerate((element.element_tag, *values[:6])):
                        self.result_table.setItem(
                            row,
                            column,
                            QTableWidgetItem(
                                str(value) if column == 0 else f"{value:.6g}"
                            ),
                        )
                return
            self.result_table.setColumnCount(4)
            self.result_table.setHorizontalHeaderLabels(
                ("ELEMENT", f"N-i ({unit.force})", f"V-i ({unit.force})", f"M-i ({unit.moment})")
            )
            elements = [] if result is None else sorted(
                result.element_results.values(), key=lambda item: item.element_tag
            )
            self.result_table.setRowCount(len(elements))
            for row, element in enumerate(elements):
                values = (*element.local_forces, 0.0, 0.0, 0.0)
                for column, value in enumerate(
                    (element.element_tag, values[0], values[1], values[2])
                ):
                    self.result_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(str(value) if column == 0 else f"{value:.6g}"),
                    )
            return

        if self._result_type == "reaction":
            if is_3d:
                self.result_table.setColumnCount(7)
                self.result_table.setHorizontalHeaderLabels(
                    (
                        "NODE",
                        f"RX ({unit.force})",
                        f"RY ({unit.force})",
                        f"RZ ({unit.force})",
                        f"MX ({unit.moment})",
                        f"MY ({unit.moment})",
                        f"MZ ({unit.moment})",
                    )
                )
                node_tags = sorted(
                    boundary.node_tag for boundary in self._model.boundaries
                )
                self.result_table.setRowCount(len(node_tags))
                for row, node_tag in enumerate(node_tags):
                    node_result = None if result is None else result.node_results.get(node_tag)
                    values = (
                        (0.0,) * 6
                        if node_result is None
                        else (*node_result.reaction, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)[:6]
                    )
                    for column, value in enumerate((node_tag, *values)):
                        self.result_table.setItem(
                            row,
                            column,
                            QTableWidgetItem(
                                str(value) if column == 0 else f"{value:.6g}"
                            ),
                        )
                return
            self.result_table.setColumnCount(4)
            self.result_table.setHorizontalHeaderLabels(
                (
                    "NODE",
                    f"RX ({unit.force})",
                    f"RY ({unit.force})",
                    f"MZ ({unit.moment})",
                )
            )
            reactions = (
                ()
                if result is None or self._model is None
                else support_reactions(self._model, result)
            )
            self.result_table.setRowCount(len(reactions))
            for row, reaction in enumerate(reactions):
                for column, value in enumerate(
                    (reaction.node_tag, reaction.fx, reaction.fy, reaction.mz)
                ):
                    self.result_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(str(value) if column == 0 else f"{value:.6g}"),
                    )
            return

        if is_3d:
            self.result_table.setColumnCount(7)
            self.result_table.setHorizontalHeaderLabels(
                (
                    "NODE",
                    f"UX ({unit.length})",
                    f"UY ({unit.length})",
                    f"UZ ({unit.length})",
                    "RX (rad)",
                    "RY (rad)",
                    "RZ (rad)",
                )
            )
            nodes = [] if result is None else sorted(
                result.node_results.values(), key=lambda item: item.node_tag
            )
            self.result_table.setRowCount(len(nodes))
            for row, node in enumerate(nodes):
                values = (*node.displacement, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
                for column, value in enumerate((node.node_tag, *values[:6])):
                    self.result_table.setItem(
                        row,
                        column,
                        QTableWidgetItem(
                            str(value) if column == 0 else f"{value:.6g}"
                        ),
                    )
            return

        self.result_table.setColumnCount(4)
        self.result_table.setHorizontalHeaderLabels(
            (
                "NODE",
                f"UX ({unit.length})",
                f"UY ({unit.length})",
                "RZ (rad)",
            )
        )
        nodes = [] if result is None else sorted(
            result.node_results.values(), key=lambda item: item.node_tag
        )
        self.result_table.setRowCount(len(nodes))
        for row, node in enumerate(nodes):
            values = (*node.displacement, 0.0, 0.0, 0.0)
            for column, value in enumerate((node.node_tag, values[0], values[1], values[2])):
                self.result_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(str(value) if column == 0 else f"{value:.6g}"),
                )
