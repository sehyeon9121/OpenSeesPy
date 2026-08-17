"""One row of Time History SETUP's multi-direction Ground Motion table.

``AnalysisSettingsPanel`` stacks one instance per translational DOF (X/Y for
a 2D model, X/Y/Z for 3D - rotational excitation is out of scope) - the
Direction itself is therefore fixed per row by construction, which is also
why two rows can never activate the same direction (Setup's own duplicate-
direction guard). Each row owns its own Built-in/Imported source, unit,
scaling method and value, and exposes the resolved state through
:meth:`to_options`/:meth:`scaling_summary` rather than the panel reaching
into its widgets directly - this file is the only place that knows how a row
is laid out.

Reuses (never duplicates): ``BuiltInGroundMotionCatalog``,
``GroundMotionPickerDialog``, ``load_ground_motion``,
``compute_ground_motion_scaling``.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import ACCELERATION_UNITS, GroundMotion, GroundMotionRecord
from openframe.features.analysis.presentation.ground_motion_picker_dialog import (
    GroundMotionPickerDialog,
)
from openframe.features.results.presentation.time_history_curve_view import (
    TimeHistoryCurveView,
)
from openframe.infrastructure.ground_motions import BuiltInGroundMotionCatalog
from openframe.infrastructure.opensees.ground_motion import load_ground_motion
from openframe.infrastructure.opensees.ground_motion_scaling import (
    GroundMotionScaling,
    compute_ground_motion_scaling,
)

_UNIT_LABELS = {"g": "g", "m/s2": "m/s²", "cm/s2": "cm/s²", "model": "Model Unit"}


class TimeHistoryDirectionRow(QFrame):
    #: Emitted whenever anything that changes build_options()'s output
    #: changes - the panel connects this straight to its own sync/precheck.
    changed = Signal()

    def __init__(
        self,
        dof: int,
        axis_label: str,
        catalog: BuiltInGroundMotionCatalog,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.dof = dof
        self.setObjectName("timeHistoryDirectionRow")
        self._catalog = catalog
        self._length_unit = "m"
        self._builtin_record: GroundMotionRecord | None = None
        self._builtin_motion: GroundMotion | None = None
        self._imported_path: Path | None = None
        self._imported_motion: GroundMotion | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        self.enabled_checkbox = QCheckBox(f"{axis_label}  (DOF {dof})")
        self.enabled_checkbox.toggled.connect(self._on_enabled_toggled)
        header_row.addWidget(self.enabled_checkbox)
        header_row.addStretch(1)
        self.unit_combo = QComboBox()
        for unit in ACCELERATION_UNITS:
            self.unit_combo.addItem(_UNIT_LABELS[unit], unit)
        self.unit_combo.currentIndexChanged.connect(self._emit_changed)
        header_row.addWidget(QLabel("Unit:"))
        header_row.addWidget(self.unit_combo)
        layout.addLayout(header_row)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        source_row = QHBoxLayout()
        self.source_group = QButtonGroup(self)
        self.builtin_radio = QRadioButton("Built-in")
        self.imported_radio = QRadioButton("Imported File")
        self.imported_radio.setChecked(True)
        self.source_group.addButton(self.builtin_radio)
        self.source_group.addButton(self.imported_radio)
        self.builtin_radio.toggled.connect(self._on_source_changed)
        source_row.addWidget(self.builtin_radio)
        source_row.addWidget(self.imported_radio)
        source_row.addStretch(1)
        body_layout.addLayout(source_row)

        record_row = QHBoxLayout()
        self.record_label = QLabel("(no record selected)")
        self.record_label.setWordWrap(True)
        record_row.addWidget(self.record_label, 1)
        self.select_button = QPushButton("Select…")
        self.select_button.clicked.connect(self._choose_record_or_file)
        record_row.addWidget(self.select_button)
        body_layout.addLayout(record_row)

        scaling_row = QHBoxLayout()
        self.scaling_group = QButtonGroup(self)
        self.factor_radio = QRadioButton("Direct Scale Factor")
        self.target_pga_radio = QRadioButton("Target PGA")
        self.factor_radio.setChecked(True)
        self.scaling_group.addButton(self.factor_radio)
        self.scaling_group.addButton(self.target_pga_radio)
        self.factor_radio.toggled.connect(self._on_scaling_method_changed)
        self.scale_factor_spin = QDoubleSpinBox()
        self.scale_factor_spin.setRange(-1.0e6, 1.0e6)
        self.scale_factor_spin.setDecimals(6)
        self.scale_factor_spin.setValue(1.0)
        self.scale_factor_spin.valueChanged.connect(self._emit_changed)
        self.target_pga_spin = QDoubleSpinBox()
        self.target_pga_spin.setRange(0.0, 1.0e6)
        self.target_pga_spin.setDecimals(6)
        self.target_pga_spin.setValue(0.0)
        self.target_pga_spin.setEnabled(False)
        self.target_pga_spin.setToolTip(
            "Expressed in this model's own acceleration unit (length/s^2), "
            "regardless of the Unit selected above for the record itself."
        )
        self.target_pga_spin.valueChanged.connect(self._emit_changed)
        scaling_row.addWidget(self.factor_radio)
        scaling_row.addWidget(self.scale_factor_spin)
        scaling_row.addWidget(self.target_pga_radio)
        scaling_row.addWidget(self.target_pga_spin)
        body_layout.addLayout(scaling_row)

        readout_grid = QGridLayout()
        readout_grid.setHorizontalSpacing(18)
        readout_grid.setVerticalSpacing(3)
        self.readout_values: dict[str, QLabel] = {}
        for column, name in enumerate(
            ("Record dt", "NPTS", "Duration", "Original PGA", "Effective Scale")
        ):
            key = QLabel(f"{name}:")
            key.setObjectName("setupMetricLabel")
            value = QLabel("—")
            value.setObjectName("setupMetricValue")
            readout_grid.addWidget(key, 0, column)
            readout_grid.addWidget(value, 1, column)
            self.readout_values[name] = value
        body_layout.addLayout(readout_grid)

        preview_label = QLabel("ACCELERATION-TIME PREVIEW")
        preview_label.setObjectName("setupMetricLabel")
        body_layout.addWidget(preview_label)
        self.preview = TimeHistoryCurveView()
        # TimeHistoryCurveView's own paintEvent lays out ~5 Y-axis tick
        # labels plus a rotated axis title - its constructor already
        # declares setMinimumHeight(200) for exactly this reason. A smaller
        # fixed height (140 was tried first) forces the axis text to
        # overlap itself, so this stays at that natural floor rather than
        # shrinking further to fit more rows on screen at once.
        self.preview.setFixedHeight(200)
        self.preview.set_empty_message("No ground motion selected")
        body_layout.addWidget(self.preview)

        layout.addWidget(self.body)
        self._on_enabled_toggled(False)
        self._on_scaling_method_changed(True)
        self._update_record_label()

    # -- source/record selection --------------------------------------

    def _on_enabled_toggled(self, checked: bool) -> None:
        # Always visible (not hidden) once a direction is disabled - only
        # grayed out (setEnabled) - so Source/Record/Scaling stay
        # discoverable and previewable without first hunting for the
        # checkbox that reveals them.
        self.body.setEnabled(checked)
        self.setProperty("active", checked)
        self.style().unpolish(self)
        self.style().polish(self)
        self._emit_changed()

    def _on_source_changed(self, builtin_checked: bool) -> None:
        del builtin_checked
        self._update_record_label()
        self._refresh_readouts()
        self._emit_changed()

    def _on_scaling_method_changed(self, factor_checked: bool) -> None:
        self.scale_factor_spin.setEnabled(factor_checked)
        self.target_pga_spin.setEnabled(not factor_checked)
        self._emit_changed()

    def _choose_record_or_file(self) -> None:
        if self.builtin_radio.isChecked():
            records = self._catalog.list_records()
            dialog = GroundMotionPickerDialog(records, self._builtin_record, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selected = dialog.selected_record()
            if selected is None:
                return
            values = tuple(self._catalog.load_series(selected))
            self._builtin_record = selected
            self._builtin_motion = GroundMotion.from_record(selected, values)
        else:
            path_text, _selected_filter = QFileDialog.getOpenFileName(
                self,
                "지진파(가속도) 파일 선택",
                "",
                "Ground motion files (*.txt *.csv *.AT2 *.dat);;All files (*.*)",
            )
            if not path_text:
                return
            path = Path(path_text)
            try:
                motion = load_ground_motion(path)
            except (ValueError, OSError) as error:
                self._imported_path = None
                self._imported_motion = None
                self.record_label.setText(f"파일을 읽지 못했습니다: {error}")
                self._refresh_readouts()
                self._emit_changed()
                return
            self._imported_path = path
            self._imported_motion = motion
        self._update_record_label()
        self._refresh_readouts()
        self._emit_changed()

    def _update_record_label(self) -> None:
        if self.builtin_radio.isChecked():
            self.record_label.setText(
                self._builtin_motion.name if self._builtin_motion is not None else "(no record selected)"
            )
        else:
            self.record_label.setText(
                self._imported_path.name if self._imported_path is not None else "(no file selected)"
            )

    # -- resolved state --------------------------------------------------

    def active_motion(self) -> GroundMotion | None:
        return self._builtin_motion if self.builtin_radio.isChecked() else self._imported_motion

    def active_path(self) -> Path | None:
        if self.builtin_radio.isChecked():
            return self._builtin_record.path if self._builtin_record is not None else None
        return self._imported_path

    def set_length_unit(self, length_unit: str) -> None:
        self._length_unit = length_unit
        self._refresh_readouts()

    def scaling_summary(self) -> GroundMotionScaling | None:
        motion = self.active_motion()
        if motion is None:
            return None
        return compute_ground_motion_scaling(
            original_pga_raw=motion.pga,
            unit=self.unit_combo.currentData(),
            length_unit=self._length_unit,
            scaling_method="target_pga" if self.target_pga_radio.isChecked() else "factor",
            scale_factor=self.scale_factor_spin.value(),
            target_pga=self.target_pga_spin.value(),
        )

    def _refresh_readouts(self) -> None:
        motion = self.active_motion()
        if motion is None:
            for label in self.readout_values.values():
                label.setText("—")
            self.preview.set_series((), (), y_label="")
            return
        self.readout_values["Record dt"].setText(f"{motion.dt:g} s")
        self.readout_values["NPTS"].setText(str(motion.npts))
        self.readout_values["Duration"].setText(f"{motion.duration:.3g} s")
        try:
            scaling = self.scaling_summary()
        except (ZeroDivisionError, ValueError):
            scaling = None
        if scaling is None:
            self.readout_values["Original PGA"].setText("—")
            self.readout_values["Effective Scale"].setText("—")
            self.preview.set_series((), (), y_label="")
            return
        self.readout_values["Original PGA"].setText(f"{scaling.original_pga_model_units:.4g}")
        self.readout_values["Effective Scale"].setText(f"{scaling.effective_scale:.4g}")

        # The applied (unit-converted + scaled) waveform - what actually
        # reaches ops.timeSeries("Path", ..., "-factor", total_factor) -
        # not the record's raw values, so the preview matches what the
        # solver will really run.
        times = tuple(index * motion.dt for index in range(motion.npts))
        values = tuple(value * scaling.total_factor for value in motion.accelerations)
        self.preview.set_series(times, values, y_label=f"Accel [{self._length_unit}/s²]")

    def _emit_changed(self) -> None:
        self._refresh_readouts()
        self.changed.emit()

    # -- options -----------------------------------------------------------

    def is_enabled_row(self) -> bool:
        return self.enabled_checkbox.isChecked()

    def has_valid_motion(self) -> bool:
        return self.active_motion() is not None and self.active_path() is not None

    def to_options(self) -> dict[str, object] | None:
        """``None`` when this row is disabled or has no motion selected -
        callers (build_options()) simply omit such a row from ``directions``."""
        if not self.is_enabled_row() or not self.has_valid_motion():
            return None
        path = self.active_path()
        return {
            "dof": self.dof,
            "path": str(path),
            "unit": self.unit_combo.currentData(),
            "scaling_method": "target_pga" if self.target_pga_radio.isChecked() else "factor",
            "scale_factor": self.scale_factor_spin.value(),
            "target_pga": self.target_pga_spin.value(),
        }
