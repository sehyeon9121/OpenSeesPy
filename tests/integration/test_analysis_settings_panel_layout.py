"""Regression test: the nonlinear fields must not overlap or get squeezed to
nothing in a cramped sidebar (the AnalysisSettingsPanel used to be added to
AnalysisResultsSidebar's layout with no stretch and no scroll area, so once the
nonlinear field group made it tall, the sidebar's fixed height forced Qt to shrink
rows below their minimum size and labels/fields started drawing on top of each
other - and the model inspector panel below it got compressed too)."""

import os
from itertools import pairwise
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.analysis_results_sidebar import AnalysisResultsSidebar
from openframe.core.domain import AnalysisKind
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "nonlinear_spring_pushover_1d.py"


def test_nonlinear_fields_stay_visible_and_non_overlapping_in_a_short_sidebar() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    # Deliberately shorter than the nonlinear group's full natural height.
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

    # The settings panel must keep enough room to actually be usable, not get
    # squeezed down to just its header.
    assert settings.height() >= 200
    # The model inspector below it must still get real, positive space.
    assert sidebar.inspector.height() > 0

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
