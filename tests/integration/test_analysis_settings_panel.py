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
