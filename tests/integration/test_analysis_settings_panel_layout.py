"""Regression coverage for the MODEL/SETUP split and the nonlinear dialog.

MODEL's AnalysisResultsSidebar used to hold the full AnalysisSettingsPanel
(solver, nonlinear dialog button, summary) stacked above the model inspector -
short on space, since the panel's fields could grow. The full panel now lives
in SETUP's SetupWorkspace instead; MODEL's sidebar only holds the lightweight
AnalysisTypeSelector, so it stays short by construction and the inspector
keeps real space. The nonlinear dialog itself is unchanged - these fields
still must not overlap regardless of which page hosts the panel."""

import os
from itertools import pairwise
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.analysis_results_sidebar import AnalysisResultsSidebar
from openframe.app.shell.setup_workspace import SetupWorkspace
from openframe.core.domain import AnalysisKind
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "nonlinear_spring_pushover_1d.py"


def test_model_sidebar_only_holds_the_type_selector_and_stays_short() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    store = AnalysisConfigStore()
    sidebar = AnalysisResultsSidebar(store)
    sidebar.resize(300, 480)
    sidebar.show()

    sidebar.inspector.set_model(model)
    store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()
    application.processEvents()

    # Three option buttons + summary + button is taller than the old combo box, but
    # still nowhere near the 400px+ the nonlinear fields needed inline before they
    # moved to a dialog - the height floor here is just "no deep fields leaked back in".
    assert sidebar.type_selector.height() < 260
    assert sidebar.inspector.height() > 0

    sidebar.close()


def test_nonlinear_settings_button_and_summary_live_in_the_setup_panel() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    store = AnalysisConfigStore()
    setup = SetupWorkspace(store)
    setup.show()
    settings = setup.settings_panel
    settings.set_model(model)
    store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()
    application.processEvents()

    assert settings.open_nonlinear_settings_button.isVisible()
    assert "Node" in settings.nonlinear_summary.text() or "not set" in settings.nonlinear_summary.text()

    fields = [settings.analysis_type, settings.solver, settings.open_nonlinear_settings_button]
    ranges = [
        (
            widget.mapTo(settings, widget.rect().topLeft()).y(),
            widget.mapTo(settings, widget.rect().bottomRight()).y(),
        )
        for widget in fields
    ]
    overlaps = [
        (earlier, later)
        for earlier, later in pairwise(sorted(ranges))
        if later[0] < earlier[1]
    ]
    assert overlaps == []
    setup.close()


def test_nonlinear_dialog_fields_do_not_overlap() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    store = AnalysisConfigStore()
    setup = SetupWorkspace(store)
    settings = setup.settings_panel
    settings.set_model(model)
    store.set_kind(AnalysisKind.NONLINEAR_STATIC)

    dialog = settings._nonlinear_dialog
    dialog.show()
    application.processEvents()
    application.processEvents()

    fields = [
        settings.control_node,
        settings.control_dof,
        settings.num_steps,
        settings.tolerance,
        settings.max_iterations,
        settings.algorithm,
        settings.test_type,
    ]
    ranges = [
        (
            widget.mapTo(dialog, widget.rect().topLeft()).y(),
            widget.mapTo(dialog, widget.rect().bottomRight()).y(),
        )
        for widget in fields
    ]
    overlaps = [
        (earlier, later) for earlier, later in pairwise(ranges) if later[0] < earlier[1]
    ]
    assert overlaps == []

    dialog.close()
