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
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)
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


def test_panel_without_an_explicit_store_still_defaults_to_linear_static() -> None:
    panel = AnalysisSettingsPanel()

    assert panel.config_store.kind == AnalysisKind.LINEAR_STATIC
    assert panel.selected_analysis_kind() == AnalysisKind.LINEAR_STATIC


def test_changing_the_combo_pushes_the_new_kind_into_the_shared_store() -> None:
    store = AnalysisConfigStore()
    panel = AnalysisSettingsPanel(store=store)

    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )

    assert store.kind == AnalysisKind.NONLINEAR_STATIC


def test_changing_the_store_from_outside_updates_the_combo() -> None:
    store = AnalysisConfigStore()
    panel = AnalysisSettingsPanel(store=store)

    store.set_kind(AnalysisKind.TIME_HISTORY)

    assert panel.analysis_type.currentData() == AnalysisKind.TIME_HISTORY


def test_two_panels_sharing_a_store_stay_in_sync() -> None:
    store = AnalysisConfigStore()
    first = AnalysisSettingsPanel(store=store)
    second = AnalysisSettingsPanel(store=store)

    first.analysis_type.setCurrentIndex(
        first.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )

    assert second.analysis_type.currentData() == AnalysisKind.NONLINEAR_STATIC


def test_solver_change_is_reflected_in_the_store_options() -> None:
    store = AnalysisConfigStore()
    panel = AnalysisSettingsPanel(store=store)

    panel.solver.setCurrentText("UmfPack")

    assert store.options["system"] == "UmfPack"
