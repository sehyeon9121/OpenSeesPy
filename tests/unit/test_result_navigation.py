import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind
from openframe.features.results.presentation.result_type_sidebar import (
    ResultTypeSidebar,
)
from openframe.features.results.presentation.results_workspace import ResultsWorkspace


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_linear_static_navigation_shows_only_relevant_result_families() -> None:
    _application()
    sidebar = ResultTypeSidebar()

    assert sidebar.context_label.text() == "LINEAR STATIC"
    assert sidebar.visible_section_keys() == (
        "overview",
        "visualization",
        "forces",
        "stress",
        "data",
    )
    assert not sidebar.buttons["stress"].isHidden()
    assert sidebar.sections["modal"].isHidden()


def test_stress_is_an_explicit_result_mode_with_its_own_inspector_context() -> None:
    _application()
    workspace = ResultsWorkspace()

    workspace.set_result_type("stress")

    assert workspace.result_types.buttons["stress"].isChecked()
    assert workspace.viewport.mode_badge.text() == "NORMAL STRESS (σ)"
    assert not workspace.summary.metric_rows["stress"].isHidden()
    assert workspace.summary.metric_rows["moment"].isHidden()


def test_analysis_kind_switches_the_navigation_context_and_default_view() -> None:
    _application()
    sidebar = ResultTypeSidebar()

    sidebar.set_analysis_kind(AnalysisKind.MODAL)

    assert sidebar.context_label.text() == "MODAL"
    assert sidebar.visible_section_keys() == ("modal", "data")
    assert sidebar.buttons["mode_shapes"].isChecked()


def test_member_forces_share_one_sidebar_entry_and_switch_in_the_canvas_header() -> None:
    _application()
    workspace = ResultsWorkspace()

    assert workspace.result_types.buttons["axial"] is workspace.result_types.buttons["shear"]
    assert workspace.result_types.buttons["shear"] is workspace.result_types.buttons["moment"]

    workspace.set_result_type("axial")
    assert not workspace.viewport.force_selector.isHidden()
    assert workspace.viewport.force_buttons["axial"].isChecked()

    workspace.viewport.force_buttons["shear"].click()
    assert workspace.viewport.mode_badge.text() == "SHEAR FORCE (V)"
    assert workspace.viewport.force_buttons["shear"].isChecked()
    assert not workspace.summary.metric_rows["shear"].isHidden()
    assert workspace.summary.metric_rows["axial"].isHidden()


def test_time_history_navigation_does_not_mix_static_and_dynamic_results() -> None:
    _application()
    sidebar = ResultTypeSidebar()

    sidebar.set_analysis_kind(AnalysisKind.TIME_HISTORY)

    assert sidebar.context_label.text() == "TIME HISTORY"
    assert sidebar.visible_section_keys() == ("time_history", "data")
    assert sidebar.buttons["time_history"].isChecked()
