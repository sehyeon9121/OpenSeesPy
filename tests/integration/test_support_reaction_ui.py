"""The SUPPORT REACTIONS result type must show the reactions the solver produced."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisRequest, AnalysisStatus
from openframe.features.results.presentation.results_workspace import ResultsWorkspace
from openframe.features.results.reactions import support_reactions
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


def _reaction_items(workspace: ResultsWorkspace) -> list:
    return [
        item
        for item in workspace.viewport.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "result_reaction"
    ]


def test_pin_and_roller_supports_show_no_moment_reaction() -> None:
    """Regression: neither support here restrains rotation, so the true Mz is zero
    everywhere; solver noise on the order of 1e-12 used to be reported and drawn."""
    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=SOURCE))
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    reactions = support_reactions(model, result)

    assert len(reactions) == 2
    assert all(not reaction.has_moment for reaction in reactions)


def test_reaction_arrows_are_drawn_at_both_supports() -> None:
    workspace = _workspace()
    workspace.result_types.select_result_type("reaction")

    items = _reaction_items(workspace)
    assert {item.data(0)[1] for item in items} == {1, 6}
    assert workspace.viewport.mode_badge.text() == "SUPPORT REACTIONS"


def test_reaction_arrows_disappear_on_a_member_force_view() -> None:
    workspace = _workspace()
    workspace.result_types.select_result_type("moment")

    assert _reaction_items(workspace) == []


def test_reaction_table_lists_hand_calculated_values() -> None:
    workspace = _workspace()
    workspace.result_types.select_result_type("reaction")

    table = workspace.tables_panel.reaction_table
    headers = [table.horizontalHeaderItem(column).text() for column in range(4)]
    assert headers[0] == "NODE"
    assert headers[1].startswith("RX")
    assert headers[2].startswith("RY")
    assert headers[3].startswith("MZ")

    rows = {
        table.item(row, 0).text(): (
            float(table.item(row, 1).text()),
            float(table.item(row, 2).text()),
        )
        for row in range(table.rowCount())
    }
    # Reference figure: A = 35 kN left + 30 kN up, B = 50 kN up.
    assert rows["1"][0] == pytest.approx(-35.0, abs=1e-6)
    assert rows["1"][1] == pytest.approx(30.0, abs=1e-6)
    assert rows["6"][0] == pytest.approx(0.0, abs=1e-6)
    assert rows["6"][1] == pytest.approx(50.0, abs=1e-6)
