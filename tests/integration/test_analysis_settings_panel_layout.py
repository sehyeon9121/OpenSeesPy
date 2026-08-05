"""Regression coverage for the nonlinear settings dialog split.

The AnalysisSettingsPanel used to inline all seven nonlinear fields directly into
AnalysisResultsSidebar's layout, which overlapped or got squeezed to nothing in a
short sidebar. They now live in a separate QDialog opened on demand, so the sidebar
only ever needs to fit a button and a one-line summary - this test checks that split
holds: the sidebar stays short and uncompressed, and the dialog itself lays its
fields out without overlap regardless of the sidebar's size."""

import os
from itertools import pairwise
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.analysis_results_sidebar import AnalysisResultsSidebar
from openframe.core.domain import AnalysisKind
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "nonlinear_spring_pushover_1d.py"


def test_nonlinear_settings_move_to_a_dialog_and_keep_the_sidebar_short() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    # Deliberately shorter than the settings panel used to need before the dialog split.
    sidebar = AnalysisResultsSidebar()
    sidebar.resize(300, 480)
    sidebar.show()

    settings = sidebar.settings
    settings.set_model(model)
    settings.analysis_type.setCurrentIndex(
        settings.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    application.processEvents()
    application.processEvents()

    assert settings.open_nonlinear_settings_button.isVisible()
    assert "Node" in settings.nonlinear_summary.text() or "not set" in settings.nonlinear_summary.text()
    # None of the seven fields live in the sidebar's layout any more, so the panel
    # only has to fit a combo, a button and a one-line summary - nowhere near the
    # ~230px floor the old scroll-area workaround needed - and the model inspector
    # below it keeps real space instead of getting squeezed to nothing.
    assert settings.height() < 260
    assert sidebar.inspector.height() > 0

    fields = [settings.analysis_type, settings.solver, settings.open_nonlinear_settings_button]
    ranges = [
        (
            widget.mapTo(sidebar, widget.rect().topLeft()).y(),
            widget.mapTo(sidebar, widget.rect().bottomRight()).y(),
        )
        for widget in fields
    ]
    overlaps = [
        (earlier, later) for earlier, later in pairwise(ranges) if later[0] < earlier[1]
    ]
    assert overlaps == []

    sidebar.close()


def test_nonlinear_dialog_fields_do_not_overlap() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    sidebar = AnalysisResultsSidebar()
    settings = sidebar.settings
    settings.set_model(model)
    settings.analysis_type.setCurrentIndex(
        settings.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )

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
    sidebar.close()
