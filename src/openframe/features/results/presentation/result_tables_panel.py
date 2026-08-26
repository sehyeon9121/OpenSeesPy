"""Comprehensive, Midas-style spreadsheet view of every computed result quantity.

This panel lays out every node/member/mode across dedicated tabs. Within a tab,
columns that mix genuinely different categories (a member's i-end vs j-end, or
a mode's period/frequency vs its per-direction mass participation) are split
into their own stacked tables rather than crammed side by side into one wide
row - each block stays narrow enough to read without horizontal scrolling.
"""

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedWidget,
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

        displacement_layout = self._new_tab_page("절점 변위")
        self.displacement_table = self._add_table_section(displacement_layout)

        reaction_layout = self._new_tab_page("지점 반력")
        self.reaction_table = self._add_table_section(reaction_layout)

        member_force_layout = self._new_tab_page("부재력")
        self.member_force_stack = QStackedWidget()
        member_force_layout.addWidget(self.member_force_stack)

        truss_page = QWidget()
        truss_layout = QVBoxLayout(truss_page)
        truss_layout.setContentsMargins(0, 0, 0, 0)
        self.member_force_truss_table = self._add_table_section(truss_layout)
        self.member_force_stack.addWidget(truss_page)

        frame_page = QWidget()
        frame_layout = QVBoxLayout(frame_page)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(10)
        self.member_force_i_table = self._add_table_section(frame_layout, "i단 (시작단)")
        self.member_force_j_table = self._add_table_section(frame_layout, "j단 (끝단)")
        self.member_force_stack.addWidget(frame_page)

        modal_layout = self._new_tab_page("고유주기 · 질량참여율")
        self._modal_tab_index = self.tabs.count() - 1
        self.modal_properties_table = self._add_table_section(modal_layout, "모드 특성")
        self.modal_participation_table = self._add_table_section(
            modal_layout, "방향별 질량참여율 (%)"
        )
        self.modal_cumulative_table = self._add_table_section(
            modal_layout, "누적 질량참여율 (%)"
        )

        # Elastic Buckling - never mixed with the modal tab above: a buckling
        # factor is not a period/frequency, and this analysis never forms a
        # mass matrix, so there is no mass-participation column to show either
        # (see core/domain/results.py's BucklingMode docstring).
        buckling_layout = self._new_tab_page("좌굴 모드")
        self._buckling_tab_index = self.tabs.count() - 1
        summary_caption = QLabel("요약")
        summary_caption.setObjectName("resultGroupLabel")
        buckling_layout.addWidget(summary_caption)
        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(18)
        summary_grid.setVerticalSpacing(4)
        self.buckling_summary_labels: dict[str, QLabel] = {}
        for row, (key, title) in enumerate(
            (
                ("factor", "Critical Buckling Factor"),
                ("case", "Reference Load Case"),
                ("state", "Critical State"),
            )
        ):
            title_label = QLabel(f"{title}:")
            title_label.setObjectName("resultGroupLabel")
            value_label = QLabel("—")
            value_label.setObjectName("resultDetailsText")
            summary_grid.addWidget(title_label, row, 0)
            summary_grid.addWidget(value_label, row, 1)
            self.buckling_summary_labels[key] = value_label
        buckling_layout.addLayout(summary_grid)
        self.buckling_scope_note = QLabel(
            "Elastic global buckling based on the selected reference load pattern. "
            "Material yielding, imperfections and local section buckling are not "
            "included."
        )
        self.buckling_scope_note.setObjectName("resultDetailsText")
        self.buckling_scope_note.setWordWrap(True)
        buckling_layout.addWidget(self.buckling_scope_note)
        self.buckling_modes_table = self._add_table_section(
            buckling_layout, "모드별 좌굴하중계수"
        )

        self._refresh()

    def _new_tab_page(self, title: str) -> QVBoxLayout:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)
        self.tabs.addTab(page, title)
        return layout

    @staticmethod
    def _add_table_section(layout: QVBoxLayout, title: str | None = None) -> QTableWidget:
        if title is not None:
            caption = QLabel(title)
            caption.setObjectName("resultGroupLabel")
            layout.addWidget(caption)
        table = QTableWidget(0, 0)
        table.setObjectName("resultTablesGrid")
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        header_view = table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header_view.setDefaultSectionSize(108)
        layout.addWidget(table, 1)
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
            summary = f"{len(result.node_results)} NODES · {len(result.element_results)} ELEMENTS"
            if result.response_spectrum_settings is not None:
                # Every value below (변위/반력/부재력) is an SRSS combination
                # across modes and directions - see ResponseSpectrumSettings'
                # own docstring for why that makes sign meaningless, the same
                # caveat the buckling tab gives its own scope_note for.
                summary += " · SRSS 결합값(부호 없음, 설계 시 ±로 적용)"
            self.status_label.setText(summary)
        self._refresh_displacements()
        self._refresh_reactions()
        self._refresh_member_forces()
        self._refresh_modal()
        self._refresh_buckling()

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
            self.member_force_stack.setCurrentIndex(0)
            self._refresh_truss_member_forces()
            return
        self.member_force_stack.setCurrentIndex(1)

        unit = self._unit_system
        result = self._result
        if is_3d:
            width = 6
            headers = [
                "ELEMENT",
                f"N ({unit.force})",
                f"Vy ({unit.force})",
                f"Vz ({unit.force})",
                f"T ({unit.moment})",
                f"My ({unit.moment})",
                f"Mz ({unit.moment})",
            ]
        else:
            width = 3
            headers = ["ELEMENT", f"N ({unit.force})", f"V ({unit.force})", f"M ({unit.moment})"]

        elements = (
            []
            if result is None
            else sorted(result.element_results.values(), key=lambda item: item.element_tag)
        )
        for table in (self.member_force_i_table, self.member_force_j_table):
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setRowCount(len(elements))

        required = width * 2
        for row, element in enumerate(elements):
            values = (
                element.local_forces
                if len(element.local_forces) >= required
                else (0.0,) * required
            )
            self.member_force_i_table.setItem(row, 0, QTableWidgetItem(str(element.element_tag)))
            self.member_force_j_table.setItem(row, 0, QTableWidgetItem(str(element.element_tag)))
            for column in range(width):
                self.member_force_i_table.setItem(
                    row, column + 1, QTableWidgetItem(f"{values[column]:.6g}")
                )
                self.member_force_j_table.setItem(
                    row, column + 1, QTableWidgetItem(f"{values[width + column]:.6g}")
                )

    def _refresh_truss_member_forces(self) -> None:
        """Member / i-j joints / axial force / tension-compression-zero — what a
        truss result actually needs, instead of frame-shaped N/V/M-i-j columns
        (V and M are always zero for a two-force member, so they say nothing)."""
        unit = self._unit_system
        result = self._result
        model = self._model
        table = self.member_force_truss_table
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

    @staticmethod
    def _format_participation_percentage(ratio: float) -> str:
        """UI display only - the stored ``ratio``/cumulative sum stays exactly as
        computed. Floating-point summation of many small modes commonly lands a
        fraction of a percent short of (or past) 100%, e.g. 99.999% or 100.0007% -
        clamped here so the table reads as the clean 100.0% the user expects."""
        percentage = ratio * 100.0
        if percentage >= 100.0 - 1.0e-3:
            percentage = 100.0
        return f"{percentage:.3g}"

    def _refresh_modal(self) -> None:
        model = self._model
        result = self._result
        modes = () if result is None else result.mode_shapes
        is_3d = model is not None and model.ndm == 3
        labels = _DOF_LABELS_3D if is_3d else _DOF_LABELS_2D
        dof_count = len(labels)

        properties_headers = ["MODE", "PERIOD (s)", "FREQUENCY (Hz)"]
        direction_headers = ["MODE"] + [f"{label} (%)" for label in labels]

        for table, headers in (
            (self.modal_properties_table, properties_headers),
            (self.modal_participation_table, direction_headers),
            (self.modal_cumulative_table, direction_headers),
        ):
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setRowCount(len(modes))

        cumulative = [0.0] * dof_count
        for row, mode in enumerate(modes):
            ratios = (*mode.mass_participation_ratio, *([0.0] * dof_count))[:dof_count]
            self.modal_properties_table.setItem(row, 0, QTableWidgetItem(str(mode.mode_number)))
            self.modal_properties_table.setItem(row, 1, QTableWidgetItem(f"{mode.period:.6g}"))
            self.modal_properties_table.setItem(
                row, 2, QTableWidgetItem(f"{mode.frequency_hz:.6g}")
            )
            self.modal_participation_table.setItem(
                row, 0, QTableWidgetItem(str(mode.mode_number))
            )
            self.modal_cumulative_table.setItem(row, 0, QTableWidgetItem(str(mode.mode_number)))
            for index, ratio in enumerate(ratios):
                cumulative[index] += ratio
                self.modal_participation_table.setItem(
                    row, 1 + index, QTableWidgetItem(self._format_participation_percentage(ratio))
                )
                self.modal_cumulative_table.setItem(
                    row,
                    1 + index,
                    QTableWidgetItem(self._format_participation_percentage(cumulative[index])),
                )

        if self._modal_tab_index >= 0:
            self.tabs.setTabVisible(self._modal_tab_index, bool(modes))

    def _refresh_buckling(self) -> None:
        result = self._result
        modes = () if result is None else result.buckling_modes

        headers = ["MODE", "BUCKLING FACTOR", "RAW EIGENVALUE"]
        table = self.buckling_modes_table
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(modes))
        for row, mode in enumerate(modes):
            table.setItem(row, 0, QTableWidgetItem(str(mode.mode_number)))
            table.setItem(row, 1, QTableWidgetItem(f"{mode.buckling_load_factor:.6g}"))
            table.setItem(row, 2, QTableWidgetItem(f"{mode.raw_eigenvalue:.6g}"))

        if modes:
            critical = modes[0]
            scale_note = (
                f" (scale x{critical.reference_load_scale:g})"
                if critical.reference_load_scale != 1.0
                else ""
            )
            self.buckling_summary_labels["factor"].setText(f"{critical.buckling_load_factor:.6g}")
            self.buckling_summary_labels["case"].setText(critical.reference_load_case)
            self.buckling_summary_labels["state"].setText(
                f"{critical.buckling_load_factor:.6g} x {critical.reference_load_case}{scale_note}"
            )
        else:
            for label in self.buckling_summary_labels.values():
                label.setText("—")

        if self._buckling_tab_index >= 0:
            self.tabs.setTabVisible(self._buckling_tab_index, bool(modes))
