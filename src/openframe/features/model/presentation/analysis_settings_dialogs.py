"""Small per-kind analysis settings dialogs for the 3D free-form canvas's
Analysis tab (see ``modeling_interface_page.py``'s ``_build_analysis_category``).

Picking a method other than Linear Static there used to just show a hint
saying "not supported here, export to a script and use the precision
analysis screen instead" - this is the first step of the user's requested
fix: the settings a student would need to configure Nonlinear Static/Modal/
Buckling/Time History get their own small window instead of being crammed
into the canvas's fixed 320px left panel (or, worse, not existing at all).

Deliberately narrower than ``SetupWorkspace``'s own ``AnalysisSettingsPanel``
(~3000 lines, ~55-70 controls for Time History alone) - **none of these
dialogs is wired to actually running anything yet**. Execution still only
ever happens through Linear Static (this canvas's own solver) or by
exporting to a script and opening the precision analysis screen. Building a
field for every option that screen has, before anything on this side reads
it, would be exactly the kind of speculative UI this codebase avoids - so
each dialog only asks for the handful of settings that capture *what kind of
run this is meant to be*, using the exact keyword names
``infrastructure/opensees``'s own ``run_*_analysis`` functions already use,
so a future execution bridge can consume ``result_options()`` directly with
no translation.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from openframe.features.analysis.presentation.time_history_direction_row import (
    TimeHistoryDirectionRow,
)
from openframe.features.model.presentation.safe_spinbox import SafeDoubleSpinBox, SafeSpinBox
from openframe.infrastructure.ground_motions import BuiltInGroundMotionCatalog


def _float_field(
    value: float, minimum: float = -1.0e9, maximum: float = 1.0e9, decimals: int = 6
) -> SafeDoubleSpinBox:
    field = SafeDoubleSpinBox()
    field.setRange(minimum, maximum)
    field.setDecimals(decimals)
    field.setValue(value)
    return field


def _int_field(value: int, minimum: int = 1, maximum: int = 100_000) -> SafeSpinBox:
    field = SafeSpinBox()
    field.setRange(minimum, maximum)
    field.setValue(value)
    return field


class ModalSettingsDialog(QDialog):
    """Mirrors ``run_modal_analysis``'s own two extraction modes exactly."""

    def __init__(self, options: dict[str, object] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Modal Analysis Settings")
        options = options or {}
        layout = QVBoxLayout(self)

        self.fixed_radio = QRadioButton("고정 모드 수")
        self.target_radio = QRadioButton("목표 참여율까지")
        (self.target_radio if options.get("extraction_method") == "target" else self.fixed_radio).setChecked(True)
        layout.addWidget(self.fixed_radio)
        layout.addWidget(self.target_radio)

        form = QFormLayout()
        self.num_modes = _int_field(int(options.get("num_modes", 10)), minimum=1, maximum=500)
        form.addRow("모드 수", self.num_modes)
        self.target_participation = _float_field(
            float(options.get("target_participation", 90.0)), minimum=0.0, maximum=100.0
        )
        form.addRow("목표 질량참여율 (%)", self.target_participation)
        self.max_modes = _int_field(int(options.get("max_modes", 50)), minimum=1, maximum=1000)
        form.addRow("최대 모드 수 (목표 참여율 모드)", self.max_modes)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_options(self) -> dict[str, object]:
        return {
            "extraction_method": "target" if self.target_radio.isChecked() else "fixed",
            "num_modes": self.num_modes.value(),
            "target_participation": self.target_participation.value(),
            "max_modes": self.max_modes.value(),
        }


class BucklingSettingsDialog(QDialog):
    """Mirrors ``run_buckling_analysis``'s own signature - only its two most
    commonly-changed keywords (the rest keep that function's own defaults:
    every load pattern combined, PDelta transform, no eigenvalue tolerance
    override)."""

    def __init__(self, options: dict[str, object] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Buckling Analysis Settings")
        options = options or {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.num_modes = _int_field(int(options.get("num_modes", 5)), minimum=1, maximum=100)
        form.addRow("좌굴 모드 수", self.num_modes)
        self.reference_load_scale = _float_field(float(options.get("reference_load_scale", 1.0)))
        form.addRow("기준하중 배율", self.reference_load_scale)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_options(self) -> dict[str, object]:
        return {
            "num_modes": self.num_modes.value(),
            "reference_load_scale": self.reference_load_scale.value(),
        }


class NonlinearStaticSettingsDialog(QDialog):
    """The handful of ``run_nonlinear_static_analysis`` keywords that define
    *what kind of pushover this is* - control DOF, which integrator
    (LoadControl/DisplacementControl/Arc-Length - Arc-Length is one of this
    function's own integrator choices, not a separate analysis kind), step
    count and convergence. Everything else (algorithm/test/system/numberer/
    constraints, gravity-vs-lateral pattern split) keeps that function's own
    defaults."""

    _DOF_LABELS = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")

    def __init__(self, options: dict[str, object] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nonlinear Static Analysis Settings")
        options = options or {}
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.control_node = _int_field(int(options.get("control_node", 1)), minimum=1)
        form.addRow("제어 절점 번호", self.control_node)
        self.control_dof = QComboBox()
        for index, label in enumerate(self._DOF_LABELS, start=1):
            self.control_dof.addItem(label, index)
        dof_index = self.control_dof.findData(int(options.get("control_dof", 1)))
        self.control_dof.setCurrentIndex(max(dof_index, 0))
        form.addRow("제어 자유도", self.control_dof)
        layout.addLayout(form)

        integrator_box = QGroupBox("적분법 (Integrator)")
        integrator_layout = QVBoxLayout(integrator_box)
        self.load_control_radio = QRadioButton("Load Control")
        self.displacement_control_radio = QRadioButton("Displacement Control")
        self.arc_length_radio = QRadioButton("Arc-Length")
        integrator_layout.addWidget(self.load_control_radio)
        integrator_layout.addWidget(self.displacement_control_radio)
        integrator_layout.addWidget(self.arc_length_radio)
        current_integrator = options.get("integrator_type", "LoadControl")
        {
            "LoadControl": self.load_control_radio,
            "DisplacementControl": self.displacement_control_radio,
            "ArcLength": self.arc_length_radio,
        }.get(current_integrator, self.load_control_radio).setChecked(True)
        layout.addWidget(integrator_box)

        form2 = QFormLayout()
        self.num_steps = _int_field(int(options.get("num_steps", 10)), minimum=1, maximum=100_000)
        form2.addRow("스텝 수", self.num_steps)
        self.tolerance = _float_field(
            float(options.get("tolerance", 1.0e-6)), minimum=1.0e-12, maximum=1.0, decimals=12
        )
        form2.addRow("허용오차", self.tolerance)
        self.max_iterations = _int_field(int(options.get("max_iterations", 25)), minimum=1, maximum=1000)
        form2.addRow("최대 반복 횟수", self.max_iterations)
        layout.addLayout(form2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_options(self) -> dict[str, object]:
        if self.load_control_radio.isChecked():
            integrator_type = "LoadControl"
        elif self.displacement_control_radio.isChecked():
            integrator_type = "DisplacementControl"
        else:
            integrator_type = "ArcLength"
        return {
            "control_node": self.control_node.value(),
            "control_dof": self.control_dof.currentData(),
            "integrator_type": integrator_type,
            "num_steps": self.num_steps.value(),
            "tolerance": self.tolerance.value(),
            "max_iterations": self.max_iterations.value(),
        }


class TimeHistorySettingsDialog(QDialog):
    """Time History intent plus the same ground-motion workflow as SETUP.

    Each 3D direction reuses :class:`TimeHistoryDirectionRow`, so the compact
    canvas dialog and the imported-OpenSeesPy workflow share the bundled
    record library, custom-file parser, PGA/unit readouts, scaling and the
    acceleration-time preview instead of drifting into two different tools.
    Integration/solver recovery controls remain on the precision SETUP page.
    """

    _DIRECTIONS = ("X", "Y", "Z")

    def __init__(self, options: dict[str, object] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Time History Analysis Settings")
        self.resize(980, 780)
        options = options or {}
        directions = options.get("directions", {}) if isinstance(options.get("directions"), dict) else {}
        layout = QVBoxLayout(self)

        note = QLabel(
            "방향을 활성화한 뒤 Built-in 내장 지진파 또는 Imported File을 선택하세요. "
            "선택한 기록의 시간 간격, 지속시간, PGA와 실제 적용 파형을 바로 확인할 수 있습니다."
        )
        note.setObjectName("secondaryText")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._catalog = BuiltInGroundMotionCatalog()
        unit_system = getattr(parent, "_unit_system", None)
        length_unit = getattr(unit_system, "length", "m")

        scroll = QScrollArea()
        scroll.setObjectName("timeHistoryGroundMotionScroll")
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        direction_layout = QVBoxLayout(scroll_content)
        direction_layout.setContentsMargins(4, 4, 4, 4)
        direction_layout.setSpacing(8)

        self.ground_motion_rows: dict[str, TimeHistoryDirectionRow] = {}
        self.direction_rows: dict[str, dict[str, QWidget]] = {}
        for dof, direction in enumerate(self._DIRECTIONS, start=1):
            row_options = directions.get(direction, {}) if isinstance(directions.get(direction), dict) else {}
            row = TimeHistoryDirectionRow(dof, direction, self._catalog, scroll_content)
            row.set_length_unit(length_unit)
            self._restore_direction_row(row, row_options)
            direction_layout.addWidget(row)
            self.ground_motion_rows[direction] = row
            # Keep the old lightweight-dialog handles available for callers
            # that only checked group/path/scale while exposing the richer row.
            self.direction_rows[direction] = {
                "group": row.enabled_checkbox,
                "path": row.record_label,
                "scale": row.scale_factor_spin,
                "row": row,
            }
        direction_layout.addStretch(1)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        form = QFormLayout()
        self.duration = _float_field(float(options.get("duration", 10.0)), minimum=0.0)
        form.addRow("해석 시간 (s)", self.duration)
        self.dt = _float_field(float(options.get("dt", 0.01)), minimum=1.0e-6)
        form.addRow("시간 간격 dt (s)", self.dt)
        self.damping_ratio = _float_field(
            float(options.get("damping_ratio", 0.05)), minimum=0.0, maximum=1.0
        )
        form.addRow("감쇠비 (Rayleigh, 대표값)", self.damping_ratio)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _restore_direction_row(
        self, row: TimeHistoryDirectionRow, options: dict[str, object]
    ) -> None:
        unit_index = row.unit_combo.findData(str(options.get("unit", "g")))
        if unit_index >= 0:
            row.unit_combo.setCurrentIndex(unit_index)

        record_id = str(options.get("record_id", ""))
        source = str(options.get("source", ""))
        path_text = str(options.get("path", ""))
        if record_id:
            row.set_builtin_record(record_id)
        elif path_text:
            saved_path = Path(path_text)
            built_in = next(
                (
                    record
                    for record in self._catalog.list_records()
                    if record.path == saved_path
                    or (source == "built_in" and record.path.name == saved_path.name)
                ),
                None,
            )
            if built_in is not None:
                row.set_builtin_record(built_in.record_id)
            elif saved_path.is_file():
                row.set_imported_file(saved_path)

        row.scale_factor_spin.setValue(float(options.get("scale_factor", 1.0)))
        row.target_pga_spin.setValue(float(options.get("target_pga", 0.0)))
        if options.get("scaling_method") == "target_pga":
            row.target_pga_radio.setChecked(True)
        else:
            row.factor_radio.setChecked(True)
        row.enabled_checkbox.setChecked(bool(options.get("active", False)))

    def result_options(self) -> dict[str, object]:
        directions = {}
        for direction, row in self.ground_motion_rows.items():
            path = row.active_path()
            directions[direction] = {
                "active": row.is_enabled_row(),
                "path": str(path) if path is not None else "",
                "scale_factor": row.scale_factor_spin.value(),
                "source": row.active_source(),
                "record_id": row.active_record_id(),
                "unit": row.unit_combo.currentData(),
                "scaling_method": (
                    "target_pga" if row.target_pga_radio.isChecked() else "factor"
                ),
                "target_pga": row.target_pga_spin.value(),
            }
        return {
            "directions": directions,
            "duration": self.duration.value(),
            "dt": self.dt.value(),
            "damping_ratio": self.damping_ratio.value(),
        }
