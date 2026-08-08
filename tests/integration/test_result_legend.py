"""The legend must describe the colours actually painted on the members."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisRequest, AnalysisStatus
from openframe.features.results.presentation.results_workspace import ResultsWorkspace
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

SOURCE = Path(__file__).parents[2] / "examples" / "portal_frame_textbook_2d.py"


def _workspace() -> ResultsWorkspace:
    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=SOURCE))
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    workspace = ResultsWorkspace()
    workspace.set_model(model)
    workspace.show_result(result)
    return workspace


def _member_colors(workspace: ResultsWorkspace) -> dict[int, str]:
    return {
        item.data(0)[1]: item.pen().color().name()
        for item in workspace.viewport.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "element"
    }


def test_legend_shows_the_moment_range_with_units() -> None:
    workspace = _workspace()
    workspace.result_types.select_result_type("moment")

    # The frame peaks at 175 kN.m at midspan and the right column carries none.
    assert "175" in workspace.summary.legend_maximum.text()
    assert "kN" in workspace.summary.legend_maximum.text()
    assert "0" in workspace.summary.legend_minimum.text()
    assert "bending moment" in workspace.summary.legend_caption.text().lower()


def test_legend_switches_to_length_units_for_displacements() -> None:
    workspace = _workspace()
    workspace.result_types.select_result_type("displacement")

    assert workspace.summary.legend_maximum.text().endswith("m")
    assert "displacement" in workspace.summary.legend_caption.text().lower()


def test_members_are_coloured_by_their_own_magnitude() -> None:
    workspace = _workspace()
    workspace.result_types.select_result_type("moment")

    colors = _member_colors(workspace)
    # Element 4 reaches the 175 kN.m peak; element 5 (right column) carries no moment.
    assert colors[4] == "#e5484d"  # top of the scale
    assert colors[5] == "#2563eb"  # bottom of the scale
    assert colors[4] != colors[1]


def test_result_types_without_a_scale_explain_the_blank_legend() -> None:
    workspace = _workspace()
    workspace.result_types.select_result_type("reaction")

    assert workspace.summary.legend_maximum.text() == "MAX"
    assert "colour" in workspace.summary.legend_caption.text().lower()
