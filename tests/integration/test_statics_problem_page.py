import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.app.shell.direct_model_workspace import DirectModelWorkspace
from openframe.core.domain import AnalysisStatus


def test_default_direct_workflow_solves_a_material_free_beam_problem() -> None:
    application = QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()

    assert application is QApplication.instance()
    workspace.setup_page.continue_button.click()
    page = workspace.geometry_page
    page.span.setValue(4.0)
    page.load.setValue(10.0)
    page.load_type.setCurrentIndex(page.load_type.findData("uniform"))
    page.solve_button.click()

    assert page._result.status == AnalysisStatus.COMPLETED
    assert page._result.node_results[1].reaction[1] == pytest.approx(20.0)
    assert page._result.node_results[2].reaction[1] == pytest.approx(20.0)
    assert "Fy=20" in page.reaction_summary.text()


def test_setup_units_are_used_by_the_statics_problem_inputs() -> None:
    application = QApplication.instance() or QApplication([])
    workspace = DirectModelWorkspace()

    assert application is QApplication.instance()
    workspace.setup_page.force_unit.setCurrentText("N")
    workspace.setup_page.length_unit.setCurrentText("mm")
    page = workspace.geometry_page
    page.load_type.setCurrentIndex(page.load_type.findData("uniform"))

    assert "mm" in page.span_name.text()
    assert "N/mm" in page.load_name.text()
