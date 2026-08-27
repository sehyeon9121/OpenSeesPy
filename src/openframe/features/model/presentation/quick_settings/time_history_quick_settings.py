"""Time History's Quick Settings page - the first of the 5 per-method pages
the Analysis Case sidebar's placeholder stack is meant to be replaced with
one at a time (see the approved plan). Everything here is a frequently-
adjusted scalar per the spec: direction activation, per-direction Scale
Factor, a single representative damping ratio, and the time-stepping
window. Ground motion *selection* (file/catalog picking, waveform preview)
and full Rayleigh damping configuration are detail-dialog-owned and not
built yet - each active direction's ``GroundMotionSummaryCard`` therefore
always shows "선택 안 됨" for now; ``analysis_precheck.py`` already flags
that honestly as a blocking error rather than letting an unset ground
motion look fine.

``load_settings``/``settings_changed`` deliberately do not touch
``AnalysisCaseStore`` directly - this widget has no idea a store exists. The
sidebar owns writing the emitted dict back into the active case's
``settings`` and re-running PRE-CHECK, exactly like every other Quick
Settings page will.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from openframe.features.model.presentation.quick_settings.ground_motion_summary_card import (
    GroundMotionSummaryCard,
)
from openframe.features.model.presentation.safe_spinbox import SafeDoubleSpinBox

#: Every key this page reads/writes in ``AnalysisCase.settings`` for a
#: Time History case, with its default value - merged under whatever the
#: case already has so a freshly-created case (settings == {}) still shows
#: sensible values instead of blanks/zeros everywhere.
DEFAULT_TIME_HISTORY_SETTINGS: dict[str, object] = {
    "active_x": False,
    "active_y": False,
    "active_z": False,
    "ground_motion_x": None,
    "ground_motion_y": None,
    "ground_motion_z": None,
    "scale_factor_x": 1.0,
    "scale_factor_y": 1.0,
    "scale_factor_z": 1.0,
    "damping_ratio": 0.05,
    "start_time": 0.0,
    "end_time": 10.0,
    "output_dt": 0.01,
    "analysis_dt": 0.005,
    "expert_mode": False,
}

_DIRECTIONS = ("x", "y", "z")


class TimeHistoryQuickSettings(QWidget):
    settings_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._direction_groups: dict[str, QGroupBox] = {}
        self._summary_cards: dict[str, GroundMotionSummaryCard] = {}
        self._scale_fields: dict[str, SafeDoubleSpinBox] = {}
        for direction in _DIRECTIONS:
            group = QGroupBox(f"{direction.upper()} 방향")
            group.setCheckable(True)
            group.toggled.connect(self._on_field_changed)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(6, 4, 6, 4)
            group_layout.setSpacing(4)

            card = GroundMotionSummaryCard()
            group_layout.addWidget(card)
            self._summary_cards[direction] = card

            scale_form = QFormLayout()
            scale_field = SafeDoubleSpinBox()
            scale_field.setRange(-100.0, 100.0)
            scale_field.setDecimals(4)
            scale_field.setValue(1.0)
            scale_field.valueChanged.connect(self._on_field_changed)
            scale_form.addRow("배율", scale_field)
            group_layout.addLayout(scale_form)

            self._direction_groups[direction] = group
            self._scale_fields[direction] = scale_field
            root.addWidget(group)

        common_form = QFormLayout()
        self.damping_ratio_field = SafeDoubleSpinBox()
        self.damping_ratio_field.setRange(0.0, 1.0)
        self.damping_ratio_field.setDecimals(4)
        self.damping_ratio_field.setToolTip(
            "단순 감쇠비 - Rayleigh 감쇠 등 세부 설정은 별도 상세창(다음 단계)에서 다룹니다."
        )
        self.damping_ratio_field.valueChanged.connect(self._on_field_changed)
        common_form.addRow("감쇠비", self.damping_ratio_field)

        self.start_time_field = SafeDoubleSpinBox()
        self.start_time_field.setRange(0.0, 1.0e6)
        self.start_time_field.setDecimals(4)
        self.start_time_field.valueChanged.connect(self._on_field_changed)
        common_form.addRow("시작(s)", self.start_time_field)

        self.end_time_field = SafeDoubleSpinBox()
        self.end_time_field.setRange(0.0, 1.0e6)
        self.end_time_field.setDecimals(4)
        self.end_time_field.valueChanged.connect(self._on_field_changed)
        common_form.addRow("종료(s)", self.end_time_field)

        self.output_dt_field = SafeDoubleSpinBox()
        self.output_dt_field.setRange(0.0, 1.0e6)
        self.output_dt_field.setDecimals(6)
        self.output_dt_field.setToolTip("출력 간격 dt")
        self.output_dt_field.valueChanged.connect(self._on_field_changed)
        common_form.addRow("출력 dt", self.output_dt_field)

        self.analysis_dt_field = SafeDoubleSpinBox()
        self.analysis_dt_field.setRange(0.0, 1.0e6)
        self.analysis_dt_field.setDecimals(6)
        self.analysis_dt_field.setToolTip("해석 적분 간격 dt")
        self.analysis_dt_field.valueChanged.connect(self._on_field_changed)
        common_form.addRow("해석 dt", self.analysis_dt_field)

        self.duration_label = QLabel()
        self.duration_label.setObjectName("setupSectionHint")
        common_form.addRow("해석시간(s)", self.duration_label)
        root.addLayout(common_form)

        self.expert_mode_checkbox = QCheckBox("전문가 모드")
        self.expert_mode_checkbox.setToolTip(
            "전문가 모드에서는 다음 단계에서 추가될 Solution Strategy 상세 설정이 노출됩니다."
        )
        self.expert_mode_checkbox.toggled.connect(self._on_field_changed)
        root.addWidget(self.expert_mode_checkbox)

    def load_settings(self, settings: dict[str, object]) -> None:
        merged = {**DEFAULT_TIME_HISTORY_SETTINGS, **settings}
        self._loading = True
        try:
            for direction in _DIRECTIONS:
                self._direction_groups[direction].setChecked(bool(merged[f"active_{direction}"]))
                self._summary_cards[direction].set_selection(merged[f"ground_motion_{direction}"])
                self._scale_fields[direction].setValue(float(merged[f"scale_factor_{direction}"]))
            self.damping_ratio_field.setValue(float(merged["damping_ratio"]))
            self.start_time_field.setValue(float(merged["start_time"]))
            self.end_time_field.setValue(float(merged["end_time"]))
            self.output_dt_field.setValue(float(merged["output_dt"]))
            self.analysis_dt_field.setValue(float(merged["analysis_dt"]))
            self.expert_mode_checkbox.setChecked(bool(merged["expert_mode"]))
        finally:
            self._loading = False
        self._refresh_duration_label()

    def _on_field_changed(self, *_args: object) -> None:
        self._refresh_duration_label()
        if self._loading:
            return
        self.settings_changed.emit(self._collect_settings())

    def _refresh_duration_label(self) -> None:
        duration = self.end_time_field.value() - self.start_time_field.value()
        self.duration_label.setText(f"{duration:.4g}")

    def _collect_settings(self) -> dict[str, object]:
        settings: dict[str, object] = {
            "damping_ratio": self.damping_ratio_field.value(),
            "start_time": self.start_time_field.value(),
            "end_time": self.end_time_field.value(),
            "output_dt": self.output_dt_field.value(),
            "analysis_dt": self.analysis_dt_field.value(),
            "expert_mode": self.expert_mode_checkbox.isChecked(),
        }
        for direction in _DIRECTIONS:
            settings[f"active_{direction}"] = self._direction_groups[direction].isChecked()
            settings[f"scale_factor_{direction}"] = self._scale_fields[direction].value()
            # Ground motion selection is detail-dialog-owned and not editable
            # from this page - preserved as whatever was last loaded rather
            # than read from any widget here, since there is no widget for it.
            settings[f"ground_motion_{direction}"] = self._summary_cards[direction].current_selection
        return settings
