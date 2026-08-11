"""Functional coverage for AnalysisSettingsPanel beyond layout: the CONTROL DOF combo
must only ever offer DOFs the loaded model actually has.

A truss-only model (ops.model('basic', '-ndm', 2, '-ndf', 2)) has 2 DOFs per node
(UX, UY) - no RZ. The combo used to always offer UX/UY/RZ for any 2D model, so
picking RZ on a model like this crashed the solver with a raw IndexError instead of
a validation message (see test_nonlinear_static_solver.py for the solver-side fix)."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind
from openframe.features.analysis.presentation.analysis_settings_panel import (
    AnalysisSettingsPanel,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

TRUSS_MODEL = Path(__file__).parents[2] / "examples" / "nonlinear_truss_pushover.py"
SPRING_MODEL = Path(__file__).parents[2] / "examples" / "nonlinear_spring_pushover_1d.py"


def test_control_dof_options_are_limited_to_the_model_ndf() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    assert model.ndf == 2

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    labels = [panel.control_dof.itemText(index) for index in range(panel.control_dof.count())]
    assert labels == ["UX", "UY"]
    application.processEvents()


def test_control_dof_options_still_cover_full_ndf_for_a_frame_style_model() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(SPRING_MODEL)

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    assert panel.control_dof.count() == model.ndf
    application.processEvents()


def test_control_node_defaults_to_the_loaded_node_not_the_first_by_tag() -> None:
    """Node 1 (the combo's natural first entry, sorted by tag) is a support in this
    model - the old plain "leave it at index 0" default silently produced a pushover
    curve that was a flat vertical line at zero displacement forever. The default
    must land on node 4, where the load (and all the movement) actually is."""
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    assert panel.control_node.currentData() == 4
    application.processEvents()


def test_control_node_default_is_the_free_node_for_the_spring_model_too() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(SPRING_MODEL)

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    assert panel.control_node.currentData() == 2
    application.processEvents()


def test_gravity_pattern_combo_lists_patterns_found_in_the_model() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    labels = [
        panel.gravity_pattern.itemText(index) for index in range(panel.gravity_pattern.count())
    ]
    assert labels == ["NONE", "Pattern 1"]
    assert panel.gravity_pattern.currentData() is None
    application.processEvents()


def test_lateral_pattern_combo_lists_patterns_and_builds_explicit_selection() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    labels = [
        panel.lateral_pattern.itemText(index)
        for index in range(panel.lateral_pattern.count())
    ]
    assert labels == ["ALL NON-GRAVITY PATTERNS", "Pattern 1"]
    panel.lateral_pattern.setCurrentIndex(panel.lateral_pattern.findData(1))
    assert panel.build_options()["lateral_pattern"] == 1
    application.processEvents()


def test_gravity_steps_hidden_until_a_gravity_pattern_is_chosen() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel._nonlinear_dialog.show()
    application.processEvents()

    assert panel.gravity_steps_group.isVisible() is False
    panel.gravity_pattern.setCurrentIndex(panel.gravity_pattern.findData(1))
    assert panel.gravity_steps_group.isVisible() is True
    panel._nonlinear_dialog.close()


def test_target_displacement_hidden_until_displacement_control_is_chosen() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel._nonlinear_dialog.show()
    application.processEvents()

    assert panel.target_displacement_group.isVisible() is False
    panel.integrator_type.setCurrentIndex(
        panel.integrator_type.findData("DisplacementControl")
    )
    assert panel.target_displacement_group.isVisible() is True
    panel._nonlinear_dialog.close()


def test_build_options_omits_gravity_and_target_displacement_by_default() -> None:
    panel = AnalysisSettingsPanel()

    options = panel.build_options()

    assert options["integrator_type"] == "LoadControl"
    assert "gravity_pattern" not in options
    assert "gravity_steps" not in options
    assert "target_displacement" not in options
    assert "lateral_pattern" not in options
    assert options["max_bisections"] == 4
    assert options["execution_timeout_seconds"] == 600
    assert options["constraints_type"] == "Plain"
    assert options["numberer"] == "RCM"


def test_build_options_includes_gravity_and_target_displacement_when_selected() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.gravity_pattern.setCurrentIndex(panel.gravity_pattern.findData(1))
    panel.gravity_steps.setValue(7)
    panel.integrator_type.setCurrentIndex(
        panel.integrator_type.findData("DisplacementControl")
    )
    panel.target_displacement.setValue(0.5)

    options = panel.build_options()

    assert options["gravity_pattern"] == 1
    assert options["gravity_steps"] == 7
    assert options["integrator_type"] == "DisplacementControl"
    assert options["target_displacement"] == 0.5
    application.processEvents()


def test_selecting_modal_shows_its_own_settings_and_hides_nonlinear() -> None:
    # isVisible() is always False for a widget that was never shown - offscreen or
    # not - regardless of its own visibility flag, so the panel must be shown first
    # to tell "hidden because never shown" apart from "hidden because not selected".
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.show()

    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.MODAL))

    assert panel.modal_group.isVisible()
    assert not panel.nonlinear_group.isVisible()
    application.processEvents()


def test_modal_build_options_is_just_the_mode_count() -> None:
    """The modal solver's own kwargs (run_modal_analysis) are only num_modes - handing
    it the nonlinear-shaped dict (system/num_steps/tolerance/...) would raise a
    TypeError on the unexpected keyword arguments, so this must be a clean, separate
    shape rather than the nonlinear dict with modal fields merged in."""
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.MODAL))
    panel.num_modes.setValue(6)

    assert panel.build_options() == {"num_modes": 6}


def test_selecting_time_history_shows_its_own_settings_and_hides_the_others() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.show()

    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))

    assert panel.time_history_group.isVisible()
    assert not panel.modal_group.isVisible()
    assert not panel.nonlinear_group.isVisible()
    application.processEvents()


def test_time_history_build_options_matches_the_solvers_own_keyword_arguments() -> None:
    """run_time_history_analysis's kwargs are ground_motion_path/direction/
    damping_ratio/scale_factor - a different shape from both nonlinear's and
    modal's, so this needs its own early return too."""
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))
    panel._ground_motion_path = Path("C:/motions/el_centro.AT2")
    panel.time_history_direction.addItem("UY", 2)
    panel.time_history_direction.setCurrentIndex(
        panel.time_history_direction.findData(2)
    )
    panel.damping_ratio.setValue(0.02)
    panel.ground_motion_scale.setValue(9.81)

    options = panel.build_options()

    assert options == {
        "ground_motion_path": "C:\\motions\\el_centro.AT2",
        "direction": 2,
        "damping_ratio": 0.02,
        "scale_factor": 9.81,
    }
    application.processEvents()


def test_time_history_build_options_defaults_to_direction_1_with_no_model_loaded() -> None:
    """set_model() is what normally populates time_history_direction - a panel
    used before any model is loaded must not crash build_options()."""
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))

    options = panel.build_options()

    assert options["ground_motion_path"] == ""
    assert options["direction"] == 1
    application.processEvents()
    application.processEvents()
