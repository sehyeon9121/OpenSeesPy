"""3D canvas's Analysis tab - picking a method other than Linear Static
swaps the run button for a 설정... button that opens that kind's own small
dialog (see analysis_settings_dialogs.py), instead of trying to fit a
nonlinear/time-history-sized settings form into the fixed 320px left panel.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1280, 800)
    page.show()
    page._show_category("analysis")
    return page


def test_linear_static_keeps_the_run_button_enabled_and_hides_settings() -> None:
    page = _page()

    assert page.analysis_run_button.isEnabled() is True
    assert page.analysis_settings_button.isVisible() is False


def test_picking_a_nonlinear_method_disables_run_and_reveals_settings() -> None:
    page = _page()
    index = page.analysis_method_selector.findData(AnalysisKind.NONLINEAR_STATIC.value)

    page.analysis_method_selector.setCurrentIndex(index)

    assert page.analysis_run_button.isEnabled() is False
    assert page.analysis_settings_button.isVisible() is True
    assert "아직 설정하지 않았습니다" in page.analysis_settings_summary.text()


def test_saving_settings_updates_the_summary_and_persists_across_method_switches() -> None:
    from openframe.features.model.presentation.analysis_settings_dialogs import (
        ModalSettingsDialog,
    )

    page = _page()
    index = page.analysis_method_selector.findData(AnalysisKind.MODAL.value)
    page.analysis_method_selector.setCurrentIndex(index)

    dialog = ModalSettingsDialog(page._analysis_settings.get(AnalysisKind.MODAL.value), page)
    dialog.num_modes.setValue(12)
    page._analysis_settings[AnalysisKind.MODAL.value] = dialog.result_options()
    page._on_analysis_method_changed()

    assert "저장했습니다" in page.analysis_settings_summary.text()

    linear_index = page.analysis_method_selector.findData(AnalysisKind.LINEAR_STATIC.value)
    page.analysis_method_selector.setCurrentIndex(linear_index)
    page.analysis_method_selector.setCurrentIndex(index)

    assert page._analysis_settings[AnalysisKind.MODAL.value]["num_modes"] == 12
    assert "저장했습니다" in page.analysis_settings_summary.text()


def test_every_non_linear_method_has_a_settings_dialog_class() -> None:
    page = _page()
    for label, kind, dialog_cls in page._ANALYSIS_METHOD_OPTIONS:
        if kind is AnalysisKind.LINEAR_STATIC:
            assert dialog_cls is None, label
        else:
            assert dialog_cls is not None, label
