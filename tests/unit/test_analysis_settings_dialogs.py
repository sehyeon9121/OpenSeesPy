"""The four per-kind analysis settings dialogs for the 3D canvas's Analysis
tab - each just needs to load an options dict back into its fields and read
it back out unchanged (round-trip), and default sensibly when given none."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.analysis_settings_dialogs import (
    BucklingSettingsDialog,
    ModalSettingsDialog,
    NonlinearStaticSettingsDialog,
    TimeHistorySettingsDialog,
)


def _app() -> None:
    QApplication.instance() or QApplication([])


def test_modal_dialog_defaults_to_fixed_mode_count() -> None:
    _app()
    dialog = ModalSettingsDialog()
    options = dialog.result_options()
    assert options["extraction_method"] == "fixed"
    assert options["num_modes"] == 10


def test_modal_dialog_round_trips_target_participation_mode() -> None:
    _app()
    dialog = ModalSettingsDialog(
        {"extraction_method": "target", "num_modes": 6, "target_participation": 95.0, "max_modes": 40}
    )
    assert dialog.target_radio.isChecked()
    options = dialog.result_options()
    assert options == {
        "extraction_method": "target",
        "num_modes": 6,
        "target_participation": 95.0,
        "max_modes": 40,
    }


def test_buckling_dialog_round_trips() -> None:
    _app()
    dialog = BucklingSettingsDialog({"num_modes": 3, "reference_load_scale": 1.5})
    assert dialog.result_options() == {"num_modes": 3, "reference_load_scale": 1.5}


def test_nonlinear_dialog_round_trips_arc_length_integrator() -> None:
    _app()
    dialog = NonlinearStaticSettingsDialog(
        {
            "control_node": 42,
            "control_dof": 3,
            "integrator_type": "ArcLength",
            "num_steps": 50,
            "tolerance": 1.0e-8,
            "max_iterations": 100,
        }
    )
    assert dialog.arc_length_radio.isChecked()
    assert dialog.result_options() == {
        "control_node": 42,
        "control_dof": 3,
        "integrator_type": "ArcLength",
        "num_steps": 50,
        "tolerance": 1.0e-8,
        "max_iterations": 100,
    }


def test_nonlinear_dialog_defaults_to_load_control() -> None:
    _app()
    dialog = NonlinearStaticSettingsDialog()
    assert dialog.load_control_radio.isChecked()
    assert dialog.result_options()["integrator_type"] == "LoadControl"


def test_time_history_dialog_round_trips_one_active_direction() -> None:
    _app()
    dialog = TimeHistorySettingsDialog(
        {
            "directions": {"X": {"active": True, "path": "elcentro.txt", "scale_factor": 1.2}},
            "duration": 20.0,
            "dt": 0.005,
            "damping_ratio": 0.03,
        }
    )
    assert dialog.direction_rows["X"]["group"].isChecked()
    assert not dialog.direction_rows["Y"]["group"].isChecked()

    options = dialog.result_options()

    assert options["directions"]["X"] == {"active": True, "path": "elcentro.txt", "scale_factor": 1.2}
    assert options["directions"]["Y"]["active"] is False
    assert options["duration"] == 20.0
    assert options["dt"] == 0.005
    assert options["damping_ratio"] == 0.03


def test_time_history_dialog_defaults_to_no_active_direction() -> None:
    _app()
    dialog = TimeHistorySettingsDialog()
    options = dialog.result_options()
    assert all(not row["active"] for row in options["directions"].values())
