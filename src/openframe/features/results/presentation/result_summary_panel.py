"""Result maxima, legend and selected-member local forces."""

import math
from collections.abc import Sequence
from typing import ClassVar

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
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.diagrams import max_abs_value, member_diagrams
from openframe.features.results.magnitudes import (
    DISPLACEMENT_TYPES,
    FORCE_INDEX,
    magnitude_range,
    member_magnitudes,
)
from openframe.features.results.reactions import support_reactions


class ResultSummaryPanel(QFrame):
    member_changed = Signal(int)

    def __init__(
        self, parent: QWidget | None = None, *, compact_2d: bool = False
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resultSummaryPanel")
        self.setProperty("compact2d", compact_2d)
        # Context inspector: narrow enough to leave the viewport dominant, wide
        # enough for a max-value + end-force table without wrapping into toy-sized
        # chips. Same band whether or not compact_2d is set.
        self.setMinimumWidth(220)
        self.setMaximumWidth(280)
        self._compact_2d = compact_2d
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._result_type = "overview"
        self._unit_system = DEFAULT_UNIT_SYSTEM

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Inspector")
        title.setObjectName("resultSectionTitle")
        self.status_badge = QLabel("WAITING")
        self.status_badge.setObjectName("waitingBadge")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_badge)
        layout.addLayout(header)

        self.metric_values: dict[str, QLabel] = {}
        self.metric_rows: dict[str, QFrame] = {}
        for key, title_text in (
            ("displacement", "MAX DISPLACEMENT"),
            ("rotation", "MAX ROTATION"),
            ("reaction", "MAX REACTION"),
            ("moment", "MAX MOMENT"),
            ("shear", "MAX SHEAR"),
            ("axial", "MAX AXIAL"),
            ("stress", "MAX STRESS"),
        ):
            row = self._metric_row(key, title_text)
            self.metric_rows[key] = row
            layout.addWidget(row)

        self.legend_title = QLabel("LEGEND")
        self.legend_title.setObjectName("resultGroupLabel")
        layout.addWidget(self.legend_title)
        self.legend = QProgressBar()
        self.legend.setObjectName("resultLegend")
        self.legend.setRange(0, 100)
        self.legend.setValue(100)
        self.legend.setTextVisible(False)
        layout.addWidget(self.legend)
        legend_labels = QHBoxLayout()
        self.legend_minimum = QLabel("MIN")
        self.legend_maximum = QLabel("MAX")
        legend_labels.addWidget(self.legend_minimum)
        legend_labels.addStretch(1)
        legend_labels.addWidget(self.legend_maximum)
        layout.addLayout(legend_labels)
        self.legend_caption = QLabel("Run analysis to populate the scale.")
        self.legend_caption.setObjectName("resultDetailsText")
        self.legend_caption.setWordWrap(True)
        layout.addWidget(self.legend_caption)

        self.selected_title = QLabel("ELEMENT")
        self.selected_title.setObjectName("resultGroupLabel")
        layout.addWidget(self.selected_title)
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

        self.details_panel = QFrame()
        details = QGridLayout(self.details_panel)
        details.setContentsMargins(0, 0, 0, 0)
        details.addWidget(QLabel("SYSTEM"), 0, 0)
        self.system_value = QLabel("LOCAL 2D")
        details.addWidget(self.system_value, 0, 1)
        details.addWidget(QLabel("DATA"), 1, 0)
        self.data_value = QLabel("END FORCES")
        details.addWidget(self.data_value, 1, 1)
        layout.addWidget(self.details_panel)
        # Soft "learning card" copy is kept only for the unused compact_2d shell.
        # Default Results must read as a professional post-processor, not a tutorial.
        self.learning_title = QLabel("NOTE")
        self.learning_title.setObjectName("resultGroupLabel")
        layout.addWidget(self.learning_title)
        self.learning_hint = QLabel()
        self.learning_hint.setObjectName("direct2DResultLearningHint")
        self.learning_hint.setWordWrap(True)
        layout.addWidget(self.learning_hint)
        layout.addStretch(1)
        self._apply_context_visibility()
        self._refresh()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self._refresh()

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self.system_value.setText(f"LOCAL {model.ndm}D")
        self._refresh()

    def set_result_type(self, result_type: str) -> None:
        self._result_type = result_type
        self._apply_context_visibility()
        self._refresh()

    def _apply_context_visibility(self) -> None:
        """Show only inspector blocks that belong to the active result type.

        Always on (not only compact_2d): dumping every max metric + legend +
        end-force table at once is what made Results feel sprawling. Filtering
        by type keeps the panel professional and scannable while beginners
        still see the numbers that matter for the view they just picked.
        """
        visible_metrics = {
            "overview": {"displacement", "rotation", "reaction", "moment", "shear", "axial", "stress"},
            "deformation": {"displacement", "rotation"},
            "displacement": {"displacement", "rotation"},
            "reaction": {"reaction"},
            "axial": {"axial"},
            "shear": {"shear"},
            "moment": {"moment"},
            "stress": {"stress"},
            "mode_shapes": {"displacement", "rotation"},
            "buckling_modes": {"displacement", "rotation"},
            "pushover": set(),
        }.get(self._result_type, set())
        for key, row in self.metric_rows.items():
            row.setVisible(key in visible_metrics)

        legend_visible = self._result_type in {
            "overview",
            "deformation",
            "displacement",
            "axial",
            "shear",
            "moment",
            "stress",
            "mode_shapes",
            "buckling_modes",
        }
        self.legend_title.setVisible(legend_visible)
        self.legend.setVisible(legend_visible)
        self.legend_minimum.setVisible(legend_visible)
        self.legend_maximum.setVisible(legend_visible)
        self.legend_caption.setVisible(legend_visible)

        member_result = self._result_type in {"axial", "shear", "moment"}
        self.selected_title.setVisible(member_result)
        self.member_selector.setVisible(member_result)
        self.end_force_table.setVisible(member_result)
        self.details_panel.setVisible(member_result)

        # Tutorial copy stays off in the default professional shell.
        show_note = self._compact_2d and self._result_type in {
            "overview",
            "deformation",
            "displacement",
            "reaction",
            "axial",
            "shear",
            "moment",
        }
        self.learning_title.setVisible(show_note)
        self.learning_hint.setVisible(show_note)
        if show_note:
            hints = {
                "overview": "Governing maxima for the active result case.",
                "deformation": "Display scale may magnify deformation for visibility.",
                "displacement": "Nodal translation and rotation components.",
                "reaction": "Support forces balancing applied loads.",
                "axial": "Tension / compression along the member axis.",
                "shear": "Transverse shear demand along the member.",
                "moment": "Bending demand along the member.",
            }
            self.learning_hint.setText(hints.get(self._result_type, ""))

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

    @staticmethod
    def _node_rotation_degrees(displacement: Sequence[float], ndm: int) -> float:
        """처짐각 — the rotation the node's displacement vector carries, in
        degrees. A 2D node's third DOF (index 2) is Rz directly; a 3D node
        has three rotational DOF (indices 3..5, Rx/Ry/Rz) with no single
        "the" bending angle, so its combined magnitude (like MAX
        DISPLACEMENT already does for Ux/Uy/Uz) is the closest analogue.
        Solver output is always radians - there is no unit-system notion of
        angle (see ``UnitSystem``), so this always converts to degrees.
        """
        if ndm == 3:
            if len(displacement) < 6:
                return 0.0
            return math.degrees(math.hypot(displacement[3], displacement[4], displacement[5]))
        if len(displacement) < 3:
            return 0.0
        return math.degrees(abs(displacement[2]))

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
        usable_statuses = {AnalysisStatus.COMPLETED, AnalysisStatus.PARTIAL}
        if result is None or result.status not in usable_statuses:
            self.status_badge.setText("WAITING")
            self.metric_values["displacement"].setText(f"—  {unit.length}")
            self.metric_values["rotation"].setText("—  °")
            self.metric_values["reaction"].setText(f"—  {unit.force}")
            self.metric_values["moment"].setText(f"—  {unit.moment}")
            self.metric_values["shear"].setText(f"—  {unit.force}")
            self.metric_values["axial"].setText(f"—  {unit.force}")
            self.metric_values["stress"].setText(f"—  {unit.stress}")
            self._refresh_legend()
            self._refresh_end_forces()
            return

        self.status_badge.setText(
            "PARTIAL" if result.status == AnalysisStatus.PARTIAL else "COMPLETED"
        )
        max_displacement = max(
            (
                math.hypot(
                    node.displacement[0] if len(node.displacement) > 0 else 0.0,
                    node.displacement[1] if len(node.displacement) > 1 else 0.0,
                    node.displacement[2]
                    if self._model is not None
                    and self._model.ndm == 3
                    and len(node.displacement) > 2
                    else 0.0,
                )
                for node in result.node_results.values()
            ),
            default=0.0,
        )
        ndm = self._model.ndm if self._model is not None else 2
        max_rotation = max(
            (self._node_rotation_degrees(node.displacement, ndm) for node in result.node_results.values()),
            default=0.0,
        )
        axial = []
        shear = []
        moment = []
        if self._model is None or self._model.ndm == 2:
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
        self.metric_values["rotation"].setText(f"{max_rotation:.4g}  °")
        reactions = (
            () if self._model is None else support_reactions(self._model, result)
        )
        max_reaction = max(
            (math.hypot(reaction.fx, reaction.fy) for reaction in reactions),
            default=0.0,
        )
        self.metric_values["reaction"].setText(
            f"{max_reaction:.6g}  {unit.force}"
        )
        if self._model is not None and self._model.ndm == 3:
            force_maxima = {
                kind: max(member_magnitudes(self._model, result, kind).values(), default=0.0)
                for kind in ("moment", "shear", "axial")
            }
            self.metric_values["moment"].setText(
                f"{force_maxima['moment']:.6g}  {unit.moment}"
            )
            self.metric_values["shear"].setText(
                f"{force_maxima['shear']:.6g}  {unit.force}"
            )
            self.metric_values["axial"].setText(
                f"{force_maxima['axial']:.6g}  {unit.force}"
            )
        else:
            self.metric_values["moment"].setText(
                f"{max_abs_value(moment):.6g}  {unit.moment}"
            )
            self.metric_values["shear"].setText(
                f"{max_abs_value(shear):.6g}  {unit.force}"
            )
            self.metric_values["axial"].setText(
                f"{max_abs_value(axial):.6g}  {unit.force}"
            )
        stress_values = (
            member_magnitudes(self._model, result, "stress")
            if self._model is not None
            else {}
        )
        max_stress = max(stress_values.values(), default=0.0)
        self.metric_values["stress"].setText(f"{max_stress:.6g}  {unit.stress}")
        self._refresh_legend()
        self._refresh_end_forces()

    #: What the coloured members mean for each result type.
    _LEGEND_CAPTIONS: ClassVar[dict[str, str]] = {
        "axial": "Members coloured by peak axial force.",
        "shear": "Members coloured by peak shear force.",
        "moment": "Members coloured by peak bending moment.",
        "stress": "Members coloured by peak normal stress |sigma|.",
        "overview": "Members coloured by nodal displacement.",
        "deformation": "Members coloured by nodal displacement.",
        "displacement": "Members coloured by nodal displacement.",
    }

    def _refresh_legend(self) -> None:
        unit = self._unit_system
        result = self._result
        if (
            self._model is None
            or result is None
            or result.status not in {AnalysisStatus.COMPLETED, AnalysisStatus.PARTIAL}
            or self._result_type not in self._LEGEND_CAPTIONS
        ):
            self.legend_minimum.setText("MIN")
            self.legend_maximum.setText("MAX")
            self.legend_caption.setText(
                "Choose a force diagram or a displacement view to colour the members."
            )
            return

        magnitudes = member_magnitudes(self._model, result, self._result_type)
        lowest, highest = magnitude_range(magnitudes)
        if self._result_type in FORCE_INDEX:
            symbol = unit.moment if self._result_type == "moment" else unit.force
        elif self._result_type == "stress":
            symbol = unit.stress
        elif self._result_type in DISPLACEMENT_TYPES:
            symbol = unit.length
        else:
            symbol = ""
        self.legend_minimum.setText(f"{lowest:.4g} {symbol}")
        self.legend_maximum.setText(f"{highest:.4g} {symbol}")
        self.legend_caption.setText(self._LEGEND_CAPTIONS[self._result_type])

    def _member_selected(self) -> None:
        self._refresh_end_forces()
        element_tag = self.member_selector.currentData()
        if element_tag is not None:
            self.member_changed.emit(int(element_tag))

    def _refresh_end_forces(self) -> None:
        is_3d = self._model is not None and self._model.ndm == 3
        if is_3d:
            self.end_force_table.setColumnCount(7)
            self.end_force_table.setHorizontalHeaderLabels(
                (
                    "END",
                    f"N ({self._unit_system.force})",
                    f"Vy ({self._unit_system.force})",
                    f"Vz ({self._unit_system.force})",
                    f"T ({self._unit_system.moment})",
                    f"My ({self._unit_system.moment})",
                    f"Mz ({self._unit_system.moment})",
                )
            )
        else:
            self.end_force_table.setColumnCount(4)
            self.end_force_table.setHorizontalHeaderLabels(
                (
                    "END",
                    f"N ({self._unit_system.force})",
                    f"V ({self._unit_system.force})",
                    f"M ({self._unit_system.moment})",
                )
            )
        for row in range(2):
            self.end_force_table.setItem(row, 0, QTableWidgetItem("i" if row == 0 else "j"))
            for column in range(1, self.end_force_table.columnCount()):
                self.end_force_table.setItem(row, column, QTableWidgetItem("—"))

        if self._result is None:
            return
        element_tag = self.member_selector.currentData()
        element = self._result.element_results.get(element_tag)
        required = 12 if is_3d else 6
        if element is None or len(element.local_forces) < required:
            return
        values = element.local_forces
        width = 6 if is_3d else 3
        for row, offset in ((0, 0), (1, width)):
            for column in range(width):
                self.end_force_table.setItem(
                    row,
                    column + 1,
                    QTableWidgetItem(f"{values[offset + column]:.5g}"),
                )
