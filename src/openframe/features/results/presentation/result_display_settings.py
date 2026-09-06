"""Context controls for the active 3D result, hosted in the left sidebar."""

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.results.display_3d import (
    COMPONENTS,
    FORCE_TYPES,
    SHAPE_TYPES,
    DisplayOptions,
)


class ResultDisplaySettings(QFrame):
    """MIDAS-style result options whose contents follow the chosen result."""

    options_changed = Signal(object)
    result_type_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultDisplaySettings")
        self._model: StructuralModel | None = None
        self._ndm = 3
        self._result: AnalysisResult | None = None
        self._kind = "overview"
        self._updating = False
        self._options: dict[str, DisplayOptions] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(6)
        title = QLabel("DISPLAY OPTIONS")
        title.setObjectName("resultTypeGroupTitle")
        layout.addWidget(title)

        self.force_kind_row, self.force_kind_selector = self._combo_row("FORCE RESULT")
        self.force_kind_selector.addItem("Axial Force (N)", "axial")
        self.force_kind_selector.addItem("Shear Force (V)", "shear")
        self.force_kind_selector.addItem("Bending Moment (M)", "moment")
        layout.addWidget(self.force_kind_row)
        self.mode_row, self.mode_selector = self._combo_row("MODE / STEP")
        self.component_row, self.component_selector = self._combo_row("COMPONENT")
        layout.addWidget(self.mode_row)
        layout.addWidget(self.component_row)

        self.shape_group = self._group("SHAPE")
        shape_layout = self.shape_group.layout()
        self.deformed = QCheckBox("Deformed")
        self.undeformed = QCheckBox("Undeformed")
        shape_layout.addWidget(self.deformed, 1, 0)
        shape_layout.addWidget(self.undeformed, 1, 1)
        layout.addWidget(self.shape_group)

        self.scale_group = self._group("SCALE")
        scale_layout = self.scale_group.layout()
        self.scale_mode = QComboBox()
        self.scale_mode.addItem("Auto", "auto")
        self.scale_mode.addItem("Real ×1", "real")
        self.scale_mode.addItem("User", "user")
        self.scale_value = QDoubleSpinBox()
        self.scale_value.setRange(0.01, 10000.0)
        self.scale_value.setDecimals(2)
        self.scale_value.setValue(30.0)
        scale_layout.addWidget(self.scale_mode, 1, 0)
        scale_layout.addWidget(self.scale_value, 1, 1)
        layout.addWidget(self.scale_group)

        self.diagram_group = self._group("DIAGRAM SCALE")
        diagram_layout = self.diagram_group.layout()
        self.diagram_scale = QSlider(Qt.Orientation.Horizontal)
        self.diagram_scale.setRange(1, 200)
        self.diagram_value = QLabel("50%")
        self.diagram_value.setObjectName("resultScaleValue")
        diagram_layout.addWidget(self.diagram_scale, 1, 0)
        diagram_layout.addWidget(self.diagram_value, 1, 1)
        layout.addWidget(self.diagram_group)

        display = self._group("TYPE OF DISPLAY")
        display_layout = display.layout()
        self.values = QCheckBox("Values on model")
        self.extrema = QCheckBox("Max / Min on model")
        self.legend = QCheckBox("Legend")
        self.arrows = QCheckBox("Arrows")
        self.node_numbers = QCheckBox("Node No.")
        self.member_numbers = QCheckBox("Member No.")
        display_layout.addWidget(self.values, 1, 0, 1, 2)
        display_layout.addWidget(self.extrema, 2, 0, 1, 2)
        display_layout.addWidget(self.legend, 3, 0)
        display_layout.addWidget(self.arrows, 3, 1)
        display_layout.addWidget(self.node_numbers, 4, 0)
        display_layout.addWidget(self.member_numbers, 4, 1)
        layout.addWidget(display)

        for widget in (self.mode_selector, self.component_selector, self.scale_mode):
            widget.currentIndexChanged.connect(self._read_controls)
        self.force_kind_selector.currentIndexChanged.connect(self._force_kind_changed)
        for widget in (
            self.deformed,
            self.undeformed,
            self.values,
            self.extrema,
            self.legend,
            self.arrows,
            self.node_numbers,
            self.member_numbers,
        ):
            widget.toggled.connect(self._read_controls)
        self.scale_value.valueChanged.connect(self._read_controls)
        self.diagram_scale.valueChanged.connect(self._read_controls)
        self._refresh()

    @staticmethod
    def _group(title: str) -> QFrame:
        group = QFrame()
        group.setObjectName("resultOptionGroup")
        layout = QGridLayout(group)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(5)
        label = QLabel(title)
        label.setObjectName("resultOptionTitle")
        layout.addWidget(label, 0, 0, 1, 2)
        return group

    @staticmethod
    def _combo_row(title: str) -> tuple[QFrame, QComboBox]:
        row = QFrame()
        row.setObjectName("resultOptionGroup")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(7, 6, 7, 7)
        label = QLabel(title)
        label.setObjectName("resultOptionTitle")
        combo = QComboBox()
        combo.setObjectName("resultOptionCombo")
        layout.addWidget(label)
        layout.addWidget(combo)
        return row, combo

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self._ndm = model.ndm
        self._refresh()

    def set_dimension(self, ndm: int) -> None:
        self._ndm = ndm
        self._refresh()

    def show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._refresh_modes()

    def clear_result(self) -> None:
        self._result = None
        self._refresh_modes()

    def set_result_type(self, kind: str) -> None:
        self._kind = kind
        self._refresh()

    def current_options(self) -> DisplayOptions | None:
        if (
            self._ndm != 3
            or self._kind in {"tables", "time_history", "pushover"}
        ):
            return None
        return replace(self._option())

    def _option(self) -> DisplayOptions:
        if self._kind not in self._options:
            option = DisplayOptions()
            if self._kind in FORCE_TYPES:
                option.component = {"axial": "N", "shear": "Vy + Vz", "moment": "My + Mz"}[
                    self._kind
                ]
            elif self._kind == "reaction":
                option.component, option.deformed = "FXYZ", False
            elif self._kind == "stress":
                option.component = "|σ| envelope"
            elif self._kind == "overview":
                option.deformed = False
            self._options[self._kind] = option
        return self._options[self._kind]

    def _refresh(self) -> None:
        self._updating = True
        option = self._option()
        active = self._kind not in {"tables", "time_history", "pushover"}
        self.setVisible(self._ndm == 3 and active)
        self.component_selector.clear()
        for component in COMPONENTS.get(self._kind, ()):
            self.component_selector.addItem(component)
        index = self.component_selector.findText(option.component)
        self.component_selector.setCurrentIndex(max(index, 0))
        self._refresh_modes()
        shape = self._kind in SHAPE_TYPES or self._kind == "stress"
        force = self._kind in FORCE_TYPES
        self.force_kind_row.setVisible(force)
        self.force_kind_selector.blockSignals(True)
        self.force_kind_selector.setCurrentIndex(
            max(self.force_kind_selector.findData(self._kind), 0)
        )
        self.force_kind_selector.blockSignals(False)
        self.component_row.setVisible(self.component_selector.count() > 1)
        self.shape_group.setVisible(shape)
        self.scale_group.setVisible(shape)
        self.diagram_group.setVisible(force)
        self.arrows.setVisible(self._kind == "reaction")
        self.legend.setVisible(self._kind != "reaction")
        self.deformed.setChecked(option.deformed)
        self.undeformed.setChecked(option.undeformed)
        self.scale_mode.setCurrentIndex(max(self.scale_mode.findData(option.scale_mode), 0))
        self.scale_value.setValue(option.scale)
        self.scale_value.setEnabled(option.scale_mode == "user")
        self.diagram_scale.setValue(option.diagram_scale)
        self.diagram_value.setText(f"{option.diagram_scale}%")
        self.values.setChecked(option.values)
        self.extrema.setChecked(option.extrema)
        self.legend.setChecked(option.legend)
        self.arrows.setChecked(option.arrows)
        self.node_numbers.setChecked(option.node_numbers)
        self.member_numbers.setChecked(option.member_numbers)
        self._updating = False

    def _refresh_modes(self) -> None:
        current = self._option().mode_index
        self.mode_selector.blockSignals(True)
        self.mode_selector.clear()
        result = self._result
        if self._kind == "mode_shapes" and result is not None:
            for mode in result.mode_shapes:
                self.mode_selector.addItem(f"Mode {mode.mode_number} · {mode.frequency_hz:.4g} Hz")
        elif self._kind == "buckling_modes" and result is not None:
            for mode in result.buckling_modes:
                self.mode_selector.addItem(
                    f"Mode {mode.mode_number} · λ {mode.buckling_load_factor:.4g}"
                )
        elif (
            self._kind == "mechanism_modes" and result is not None and result.instability_diagnostic
        ):
            for mode in result.instability_diagnostic.modes:
                self.mode_selector.addItem(f"Mechanism {mode.mode_number}")
        self.mode_selector.setCurrentIndex(min(current, self.mode_selector.count() - 1))
        self.mode_selector.blockSignals(False)
        self.mode_row.setVisible(self._kind in {"mode_shapes", "buckling_modes", "mechanism_modes"})

    def _read_controls(self, *_args: object) -> None:
        if self._updating:
            return
        option = self._option()
        if self.component_selector.currentText():
            option.component = self.component_selector.currentText()
        option.mode_index = max(self.mode_selector.currentIndex(), 0)
        option.deformed = self.deformed.isChecked()
        option.undeformed = self.undeformed.isChecked()
        option.scale_mode = self.scale_mode.currentData() or "auto"
        option.scale = self.scale_value.value()
        option.diagram_scale = self.diagram_scale.value()
        option.values = self.values.isChecked()
        option.extrema = self.extrema.isChecked()
        option.legend = self.legend.isChecked()
        option.arrows = self.arrows.isChecked()
        option.node_numbers = self.node_numbers.isChecked()
        option.member_numbers = self.member_numbers.isChecked()
        self.scale_value.setEnabled(option.scale_mode == "user")
        self.diagram_value.setText(f"{option.diagram_scale}%")
        self.options_changed.emit(replace(option))

    def _force_kind_changed(self, *_args: object) -> None:
        kind = self.force_kind_selector.currentData()
        if not self._updating and kind in FORCE_TYPES and kind != self._kind:
            self.result_type_requested.emit(kind)
