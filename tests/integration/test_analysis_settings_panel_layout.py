"""Regression coverage for the MODEL/SETUP split and the nonlinear dialog.

MODEL's AnalysisResultsSidebar used to hold the full AnalysisSettingsPanel
(solver, nonlinear dialog button, summary) stacked above the model inspector -
short on space, since the panel's fields could grow. The full panel now lives
in SETUP's SetupWorkspace instead; MODEL's sidebar only holds the lightweight
AnalysisTypeSelector, so it stays short by construction and the inspector
keeps real space. The nonlinear dialog itself is unchanged - these fields
still must not overlap regardless of which page hosts the panel."""

import os
from itertools import combinations
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

    # Just a summary label and a shortcut button now (the four kind buttons moved
    # to being SETUP's job entirely) - nowhere near the 400px+ the nonlinear
    # fields needed inline before they moved to a dialog.
    assert sidebar.type_selector.height() < 260
    assert sidebar.inspector.height() > 0

    sidebar.close()


def test_nonlinear_settings_are_edited_inline_without_a_dialog() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    store = AnalysisConfigStore()
    setup = SetupWorkspace(store)
    setup.show()
    settings = setup.settings_panel
    settings.set_model(model)
    store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()

    assert settings.num_steps.maximum() >= 3_240
    application.processEvents()

    assert settings.integrator_type.isVisible()
    assert settings.lateral_pattern.isVisible()
    assert settings.num_steps.isVisible()
    assert not hasattr(settings, "_nonlinear_dialog")
    assert not hasattr(settings, "open_nonlinear_settings_button")

    fields = [settings.analysis_type, settings.lateral_pattern, settings.integrator_type]
    rects = [
        (
            widget.mapTo(settings, widget.rect().topLeft()).x(),
            widget.mapTo(settings, widget.rect().topLeft()).y(),
            widget.mapTo(settings, widget.rect().bottomRight()).x(),
            widget.mapTo(settings, widget.rect().bottomRight()).y(),
        )
        for widget in fields
    ]
    overlaps = []
    for earlier, later in combinations(rects, 2):
        ax1, ay1, ax2, ay2 = earlier
        bx1, by1, bx2, by2 = later
        if ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2:
            overlaps.append((earlier, later))
    assert overlaps == []
    setup.close()


def test_nonlinear_inline_advanced_fields_do_not_overlap() -> None:
    """Expanded advanced fields remain readable in the two-column inline grid."""
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    store = AnalysisConfigStore()
    setup = SetupWorkspace(store)
    settings = setup.settings_panel
    settings.set_model(model)
    store.set_kind(AnalysisKind.NONLINEAR_STATIC)

    setup.resize(1200, 900)
    setup.show()
    settings.integrator_type.setCurrentIndex(
        settings.integrator_type.findData("DisplacementControl")
    )
    settings.nonlinear_advanced_toggle.setChecked(True)
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
    rects = [
        (
            widget.mapTo(settings, widget.rect().topLeft()).x(),
            widget.mapTo(settings, widget.rect().topLeft()).y(),
            widget.mapTo(settings, widget.rect().bottomRight()).x(),
            widget.mapTo(settings, widget.rect().bottomRight()).y(),
        )
        for widget in fields
    ]

    def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        return ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2

    overlaps = [
        (i, j) for i, j in combinations(range(len(rects)), 2) if _overlaps(rects[i], rects[j])
    ]
    assert overlaps == []

    setup.close()
