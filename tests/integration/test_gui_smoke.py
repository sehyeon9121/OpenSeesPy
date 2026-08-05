"""Verify that the main Qt window can be constructed without showing it."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow


def test_main_window_can_be_constructed() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert application is QApplication.instance()
    assert window.windowTitle() == "OpenFrame Studio"
    assert window.view is window.viewport.view
    assert window.navigation.current_section() == "model"
    assert window.workspace_stack.currentWidget() is window.start_workspace
    assert window.navigation.isHidden()
    assert window.header.home_button.isHidden()
    assert window.start_workspace.resume_button.isHidden()
    assert window.start_workspace.import_button.text() == "START"

    window.start_workspace.import_button.click()
    assert window.workspace_stack.currentWidget() is window.workspace
    assert window._current_model_source is None
    assert not window.header.upload_button.isHidden()
    assert tuple(window.modeling_workflow._buttons) == (
        "setup",
        "materials",
        "sections",
        "geometry",
        "supports",
        "loads",
        "analysis",
    )
    assert window.modeling_workflow.current_step() == "geometry"

    window.modeling_workflow._buttons["materials"].click()
    assert window.modeling_workflow.current_step() == "materials"
    assert window.navigation.current_section() == "model"

    window.navigation._buttons["code"].click()
    assert not window.viewport.code_preview.isHidden()
    assert window.viewport.code_editor.isReadOnly()

    window.header.home_button.click()
    assert window.workspace_stack.currentWidget() is window.start_workspace
    assert not window.start_workspace.resume_button.isHidden()
    window.start_workspace.resume_button.click()
    assert window.workspace_stack.currentWidget() is window.workspace

    window.navigation._buttons["results"].click()
    assert window.navigation.current_section() == "results"
    assert window.workspace_stack.currentWidget() is window.results_workspace
    assert set(window.results_workspace.result_types.buttons) == {
        "overview",
        "deformation",
        "displacement",
        "reaction",
        "axial",
        "shear",
        "moment",
        "tables",
    }
    assert window.analysis_settings.analysis_type.currentText() == "Linear Static"
    assert window.header.run_button.text() == "▶  RUN ANALYSIS"

    window.close()


def test_new_model_opens_at_basic_setup_step() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert application is QApplication.instance()
    window.start_workspace.new_model_button.click()

    assert window.workspace_stack.currentWidget() is window.workspace
    assert window.modeling_workflow.current_step() == "setup"
    assert window.header.project_label.text() == "새 구조 모델"
    assert window._current_model_source is None

    window.close()
