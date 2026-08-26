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

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from openframe.features.model.presentation.safe_spinbox import SafeDoubleSpinBox, SafeSpinBox


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
        self.control_dof.setCurrentIndex(dof_index if dof_index >= 0 else 0)
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
    """Cut down hard from SETUP's own 7-card Time History editor (Ground
    Motion/Analysis Time/Damping/Time Integration/Solution Strategy/Adaptive
    Recovery/Pre-check) to the fields that capture the run's actual intent -
    which directions, what record, how strong, how long, how damped. The
    rest (integration scheme details, solver strategy, adaptive recovery)
    stays at that function's own sensible defaults until a real execution
    bridge exists to justify exposing them here too.
    """

    _DIRECTIONS = ("X", "Y", "Z")

    def __init__(self, options: dict[str, object] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Time History Analysis Settings")
        options = options or {}
        directions = options.get("directions", {}) if isinstance(options.get("directions"), dict) else {}
        layout = QVBoxLayout(self)

        self.direction_rows: dict[str, dict[str, QWidget]] = {}
        for direction in self._DIRECTIONS:
            row_options = directions.get(direction, {}) if isinstance(directions.get(direction), dict) else {}
            group = QGroupBox(f"{direction} 방향")
            group.setCheckable(True)
            group.setChecked(bool(row_options.get("active", False)))
            form = QFormLayout(group)
            path_field = QLineEdit(str(row_options.get("path", "")))
            path_field.setPlaceholderText("지반운동 기록 파일 경로")
            browse_button = QPushButton("찾아보기...")
            browse_button.clicked.connect(lambda _checked=False, field=path_field: self._browse(field))
            path_row = QVBoxLayout()
            path_row.addWidget(path_field)
            path_row.addWidget(browse_button)
            form.addRow("기록 파일", path_row)
            scale_field = _float_field(float(row_options.get("scale_factor", 1.0)), minimum=0.0)
            form.addRow("배율", scale_field)
            layout.addWidget(group)
            self.direction_rows[direction] = {
                "group": group, "path": path_field, "scale": scale_field
            }

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

    def _browse(self, field: QLineEdit) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "지반운동 기록 파일 선택")
        if path:
            field.setText(path)

    def result_options(self) -> dict[str, object]:
        directions = {
            direction: {
                "active": widgets["group"].isChecked(),
                "path": widgets["path"].text(),
                "scale_factor": widgets["scale"].value(),
            }
            for direction, widgets in self.direction_rows.items()
        }
        return {
            "directions": directions,
            "duration": self.duration.value(),
            "dt": self.dt.value(),
            "damping_ratio": self.damping_ratio.value(),
        }
