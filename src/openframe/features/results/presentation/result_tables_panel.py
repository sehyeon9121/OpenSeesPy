"""Comprehensive, Midas-style spreadsheet view of every computed result quantity.

This panel lays out every node/member/mode at once across dedicated tabs, wide
enough to actually read as a data export.
"""

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
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
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.diagrams import member_diagrams
from openframe.features.results.reactions import support_reactions

_DOF_LABELS_2D = ("UX", "UY", "RZ")
_DOF_LABELS_3D = ("UX", "UY", "UZ", "RX", "RY", "RZ")


class ResultTablesPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultTablesPanel")
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._unit_system = DEFAULT_UNIT_SYSTEM

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("resultTablesHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        title = QLabel("RESULT TABLES")
        title.setObjectName("resultDataTitle")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        self.status_label = QLabel("해석을 실행하면 값이 표시됩니다.")
        self.status_label.setObjectName("resultDetailsText")
        header_layout.addWidget(self.status_label)
        layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("resultTablesTabs")
        layout.addWidget(self.tabs, 1)

        self.displacement_table = self._add_table_tab("절점 변위")
        self.reaction_table = self._add_table_tab("지점 반력")
        self.member_force_table = self._add_table_tab("부재력")
        self.modal_table = self._add_table_tab("고유주기 · 질량참여율")
        self._modal_tab_index = self.tabs.indexOf(self.modal_table.parentWidget())

        self._refresh()

    def _add_table_tab(self, title: str) -> QTableWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(6, 6, 6, 6)
        table = QTableWidget(0, 0)
        table.setObjectName("resultTablesGrid")
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        header_view = table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_view.setDefaultSectionSize(108)
        page_layout.addWidget(table)
        self.tabs.addTab(page, title)
        return table

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self._refresh()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self._refresh()

    def show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._refresh()

    def clear_result(self) -> None:
        """Drop the tabulated result so a new model never shows the previous one."""
        self._result = None
        self._refresh()

    def _is_truss_model(self) -> bool:
        if self._model is None or not self._model.elements:
            return False
        return all(
            "truss" in element.element_type.lower()
            for element in self._model.elements.values()
        )

    def _refresh(self) -> None:
        result = self._result
        if result is None:
            self.status_label.setText("해석을 실행하면 값이 표시됩니다.")
        else:
            self.status_label.setText(
                f"{len(result.node_results)} NODES · {len(result.element_results)} ELEMENTS"
            )
        self._refresh_displacements()
        self._refresh_reactions()
        self._refresh_member_forces()
        self._refresh_modal()

    def _refresh_displacements(self) -> None:
        unit = self._unit_system
        model = self._model
        result = self._result
        is_3d = model is not None and model.ndm == 3
        labels = _DOF_LABELS_3D if is_3d else _DOF_LABELS_2D
        dof_count = len(labels)
        translations = 3 if is_3d else 2
        units = (unit.length,) * translations + ("rad",) * (dof_count - translations)
        headers = ["NODE"] + [f"{label} ({u})" for label, u in zip(labels, units)]
        table = self.displacement_table
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        nodes = (
            []
            if result is None
            else sorted(result.node_results.values(), key=lambda item: item.node_tag)
        )
        table.setRowCount(len(nodes))
        for row, node in enumerate(nodes):
            values = (*node.displacement, *([0.0] * dof_count))[:dof_count]
            table.setItem(row, 0, QTableWidgetItem(str(node.node_tag)))
            for column, value in enumerate(values, start=1):
                table.setItem(row, column, QTableWidgetItem(f"{value:.6g}"))

    def _refresh_reactions(self) -> None:
        unit = self._unit_system
        model = self._model
        result = self._result
        table = self.reaction_table
        is_3d = model is not None and model.ndm == 3
        if is_3d:
            headers = [
                "NODE",
                f"RX ({unit.force})",
                f"RY ({unit.force})",
                f"RZ ({unit.force})",
                f"MX ({unit.moment})",
                f"MY ({unit.moment})",
                f"MZ ({unit.moment})",
            ]
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            node_tags = [] if model is None else sorted(
                boundary.node_tag for boundary in model.boundaries
            )
            table.setRowCount(len(node_tags))
            for row, node_tag in enumerate(node_tags):
                node_result = None if result is None else result.node_results.get(node_tag)
                values = (
                    (0.0,) * 6
                    if node_result is None
                    else (*node_result.reaction, *([0.0] * 6))[:6]
                )
                table.setItem(row, 0, QTableWidgetItem(str(node_tag)))
                for column, value in enumerate(values, start=1):
                    table.setItem(row, column, QTableWidgetItem(f"{value:.6g}"))
            return

        headers = ["NODE", f"RX ({unit.force})", f"RY ({unit.force})", f"MZ ({unit.moment})"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        reactions = (
            () if result is None or model is None else support_reactions(model, result)
        )
        table.setRowCount(len(reactions))
        for row, reaction in enumerate(reactions):
            for column, value in enumerate(
                (reaction.node_tag, reaction.fx, reaction.fy, reaction.mz)
            ):
                table.setItem(
                    row,
                    column,
                    QTableWidgetItem(str(value) if column == 0 else f"{value:.6g}"),
                )

    def _refresh_member_forces(self) -> None:
        model = self._model
        is_3d = model is not None and model.ndm == 3
        if not is_3d and self._is_truss_model():
            self._refresh_truss_member_forces()
            return

        unit = self._unit_system
        result = self._result
        table = self.member_force_table
        if is_3d:
            width = 6
            ends = (
                (f"N-i ({unit.force})", f"Vy-i ({unit.force})", f"Vz-i ({unit.force})",
                 f"T-i ({unit.moment})", f"My-i ({unit.moment})", f"Mz-i ({unit.moment})"),
                (f"N-j ({unit.force})", f"Vy-j ({unit.force})", f"Vz-j ({unit.force})",
                 f"T-j ({unit.moment})", f"My-j ({unit.moment})", f"Mz-j ({unit.moment})"),
            )
        else:
            width = 3
            ends = (
                (f"N-i ({unit.force})", f"V-i ({unit.force})", f"M-i ({unit.moment})"),
                (f"N-j ({unit.force})", f"V-j ({unit.force})", f"M-j ({unit.moment})"),
            )
        headers = ["ELEMENT", *ends[0], *ends[1]]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        elements = (
            []
            if result is None
            else sorted(result.element_results.values(), key=lambda item: item.element_tag)
        )
        table.setRowCount(len(elements))
        required = width * 2
        for row, element in enumerate(elements):
            table.setItem(row, 0, QTableWidgetItem(str(element.element_tag)))
            values = (
                element.local_forces
                if len(element.local_forces) >= required
                else (0.0,) * required
            )
            for column, value in enumerate(values[:required], start=1):
                table.setItem(row, column, QTableWidgetItem(f"{value:.6g}"))

    def _refresh_truss_member_forces(self) -> None:
        """Member / i-j joints / axial force / tension-compression-zero — what a
        truss result actually needs, instead of frame-shaped N/V/M-i-j columns
        (V and M are always zero for a two-force member, so they say nothing)."""
        unit = self._unit_system
        result = self._result
        model = self._model
        table = self.member_force_table
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(
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

        table.setRowCount(len(elements))
        for row, element in enumerate(elements):
            member = model.elements.get(element.element_tag)
            joints = f"{member.node_i}-{member.node_j}" if member is not None else "-"
            value = values.get(element.element_tag, 0.0)
            is_zero = abs(value) <= noise_floor
            status = "0부재" if is_zero else "인장" if value > 0.0 else "압축"
            for column, text in enumerate(
                (str(element.element_tag), joints, f"{value:.6g}", status)
            ):
                table.setItem(row, column, QTableWidgetItem(text))

    def _refresh_modal(self) -> None:
        model = self._model
        result = self._result
        table = self.modal_table
        modes = () if result is None else result.mode_shapes
        is_3d = model is not None and model.ndm == 3
        labels = _DOF_LABELS_3D if is_3d else _DOF_LABELS_2D
        dof_count = len(labels)

        headers = ["MODE", "PERIOD (s)", "FREQUENCY (Hz)"]
        headers += [f"{label} 참여율 (%)" for label in labels]
        headers += [f"{label} 누적 (%)" for label in labels]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(modes))

        cumulative = [0.0] * dof_count
        for row, mode in enumerate(modes):
            ratios = (*mode.mass_participation_ratio, *([0.0] * dof_count))[:dof_count]
            table.setItem(row, 0, QTableWidgetItem(str(mode.mode_number)))
            table.setItem(row, 1, QTableWidgetItem(f"{mode.period:.6g}"))
            table.setItem(row, 2, QTableWidgetItem(f"{mode.frequency_hz:.6g}"))
            for index, ratio in enumerate(ratios):
                cumulative[index] += ratio
                table.setItem(row, 3 + index, QTableWidgetItem(f"{ratio * 100.0:.3g}"))
            for index, total in enumerate(cumulative):
                table.setItem(
                    row, 3 + dof_count + index, QTableWidgetItem(f"{total * 100.0:.3g}")
                )

        if self._modal_tab_index >= 0:
            self.tabs.setTabVisible(self._modal_tab_index, bool(modes))
