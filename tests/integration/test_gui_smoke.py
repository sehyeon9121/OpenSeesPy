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
    assert window.header.run_button.isHidden()
    assert window.start_workspace.resume_button.isHidden()
    assert window.start_workspace.import_button.text() == "IMPORT"

    window.start_workspace.import_button.click()
    assert window.workspace_stack.currentWidget() is window.model_workspace_page
    assert window._current_model_source is None
    assert not window.navigation.isHidden()
    assert not window.header.run_button.isHidden()
    assert not window.header.upload_button.isHidden()

    window.header.brand_label.click()
    assert window.workspace_stack.currentWidget() is window.start_workspace
    assert window.navigation.isHidden()
    assert window.header.run_button.isHidden()
    assert not window.start_workspace.resume_button.isHidden()
    window.start_workspace.resume_button.click()
    assert window.workspace_stack.currentWidget() is window.model_workspace_page

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
        "pushover",
        "tables",
        "mode_shapes",
        "time_history",
    }
    assert window.analysis_settings.analysis_type.currentText() == "Linear Static"
    assert window.header.run_button.text() == "▶  RUN ANALYSIS"

    window.close()


def test_new_2d_model_skips_the_wizard_straight_to_its_own_canvas() -> None:
    """2D structural-mechanics problems are usually determinate textbook
    statics needing no material/section input, so the wizard would just be
    friction — New 2D Model must land directly on the 2D canvas."""
    application = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert application is QApplication.instance()
    window.start_workspace.new_model_button.click()

    direct = window.direct_model_workspace
    assert window.workspace_stack.currentWidget() is direct
    assert direct.stage_stack.currentWidget() is direct.geometry_page
    assert direct.workflow.isHidden()
    assert direct.command_bar.isHidden()
    assert window.navigation.isHidden()
    assert not window.header.isHidden()
    assert not window.header.direct_open_button.isHidden()
    assert window.header.save_button.text() == "저장"
    assert window.header.run_button.isHidden()
    assert window.header.home_button.isHidden()
    assert window.header.home_button.parentWidget() is None
    assert window.header.brand_label.toolTip() == ""
    assert window._current_model_source is None

    window.close()


def test_new_3d_model_opens_the_wizard_and_ends_on_the_3d_canvas() -> None:
    """3D models generally do need real materials/sections to mean anything,
    the reverse of 2D — New 3D Model must open at basic setup, pre-set to
    3D, and land on the 3D canvas (not the 2D one) once continued through."""
    _application = QApplication.instance() or QApplication([])
    window = MainWindow()

    window.start_workspace.new_3d_model_button.click()

    direct = window.direct_model_workspace
    assert window.workspace_stack.currentWidget() is direct
    assert direct.workflow.current_step() == "setup"
    assert direct.stage_stack.currentWidget() is direct.setup_page
    assert direct.setup_page.dimension.currentIndex() == 1
    assert "'-ndm', 3" in direct.setup_page.command_preview.text()
    assert "'-ndf', 6" in direct.setup_page.command_preview.text()
    assert window.navigation.isHidden()
    assert not window.header.isHidden()
    assert not window.header.direct_open_button.isHidden()

    direct.setup_page.continue_button.click()
    assert direct.stage_stack.currentWidget() is direct.geometry_page_3d
    assert direct.geometry_page.canvas.nodes == {}

    direct.set_current_step("setup")
    direct.setup_page.analysis_kind.setCurrentIndex(1)
    direct.setup_page.continue_button.click()
    assert direct.workflow.current_step() == "materials"
    assert direct.stage_stack.currentWidget() is direct.materials_page

    window.close()
