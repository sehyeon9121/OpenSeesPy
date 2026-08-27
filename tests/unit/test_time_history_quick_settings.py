"""TimeHistoryQuickSettings - load/collect round trip, and that editing one
field emits the *full* settings dict (not just the changed key) so the
sidebar can write it straight back into AnalysisCase.settings."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.quick_settings.time_history_quick_settings import (
    DEFAULT_TIME_HISTORY_SETTINGS,
    TimeHistoryQuickSettings,
)


def _widget() -> TimeHistoryQuickSettings:
    QApplication.instance() or QApplication([])
    widget = TimeHistoryQuickSettings()
    widget.show()
    return widget


def test_a_fresh_case_with_no_settings_loads_the_documented_defaults() -> None:
    widget = _widget()

    widget.load_settings({})

    assert widget._direction_groups["x"].isChecked() is False
    assert widget.damping_ratio_field.value() == DEFAULT_TIME_HISTORY_SETTINGS["damping_ratio"]
    assert widget.duration_label.text() == "10"


def test_load_settings_then_collect_round_trips_exactly() -> None:
    widget = _widget()
    settings = {
        **DEFAULT_TIME_HISTORY_SETTINGS,
        "active_x": True,
        "scale_factor_x": 1.5,
        "ground_motion_x": {"name": "Kobe", "pga": 0.834, "dt": 0.01, "duration": 40.0, "unit": "g", "final_scale": 1.5},
        "damping_ratio": 0.03,
        "start_time": 1.0,
        "end_time": 21.0,
    }

    widget.load_settings(settings)

    assert widget._collect_settings() == settings


def test_checking_a_direction_emits_the_full_settings_dict() -> None:
    widget = _widget()
    widget.load_settings({})
    emitted: list[dict] = []
    widget.settings_changed.connect(emitted.append)

    widget._direction_groups["y"].setChecked(True)

    assert len(emitted) == 1
    assert emitted[0]["active_y"] is True
    assert emitted[0]["active_x"] is False  # untouched fields are still present, not dropped


def test_loading_settings_does_not_itself_emit_settings_changed() -> None:
    """Programmatically setting every widget's value while loading a case
    must not look like the user editing it - otherwise switching to a case
    would immediately overwrite it with its own (identical) settings, and
    switching *away* mid-edit could bleed into the wrong case."""
    widget = _widget()
    emitted: list[dict] = []
    widget.settings_changed.connect(emitted.append)

    widget.load_settings({"active_x": True, "damping_ratio": 0.1})

    assert emitted == []


def test_duration_label_reflects_end_minus_start() -> None:
    widget = _widget()
    widget.load_settings({"start_time": 2.0, "end_time": 12.5})

    assert widget.duration_label.text() == "10.5"


def test_ground_motion_summary_card_shows_placeholder_when_unset() -> None:
    widget = _widget()
    widget.load_settings({})

    assert widget._summary_cards["x"]._empty_label.isVisible() is True


def test_ground_motion_summary_card_shows_fields_when_set() -> None:
    widget = _widget()
    selection = {"name": "Kobe", "pga": 0.834, "dt": 0.01, "duration": 40.0, "unit": "g", "final_scale": 1.0}
    widget.load_settings({"ground_motion_x": selection})

    card = widget._summary_cards["x"]
    assert card._empty_label.isVisible() is False
    assert "Kobe" in card._rows["name"].text()
