"""3D canvas's Analysis tab - picking a method other than Linear Static
swaps the run button for a 설정... button that opens the same wide,
``AnalysisSettingsPanel``-hosting dialog SETUP's OpenSeesPy-import flow uses
(see analysis_settings_dialogs.py), instead of trying to fit a
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


def test_picking_modal_disables_run_and_reveals_settings() -> None:
    """Modal/Buckling/Time History still only stage settings - see
    ``_on_analysis_method_changed``'s ``can_run`` gate. Nonlinear Static is
    the one exception (below): it has a real solve wired up now."""
    page = _page()
    index = page.analysis_method_selector.findData(AnalysisKind.MODAL.value)

    page.analysis_method_selector.setCurrentIndex(index)

    assert page.analysis_run_button.isEnabled() is False
    assert page.analysis_settings_button.isVisible() is True
    assert "아직 설정하지 않았습니다" in page.analysis_settings_summary.text()


def test_picking_nonlinear_static_keeps_run_enabled_since_it_actually_solves() -> None:
    page = _page()
    index = page.analysis_method_selector.findData(AnalysisKind.NONLINEAR_STATIC.value)

    page.analysis_method_selector.setCurrentIndex(index)

    assert page.analysis_run_button.isEnabled() is True
    assert page.analysis_settings_button.isVisible() is True
    assert "아직 설정하지 않았습니다" in page.analysis_settings_summary.text()


def test_saving_settings_updates_the_summary_and_persists_across_method_switches() -> None:
    """Same flow a real 설정... click drives, minus the modal ``exec()`` loop:
    stage a value through the shared panel exactly the way
    ``_open_analysis_settings_dialog`` does, and confirm it is still there
    after the tab's own method combo is switched away and back."""
    page = _page()
    index = page.analysis_method_selector.findData(AnalysisKind.MODAL.value)
    page.analysis_method_selector.setCurrentIndex(index)

    panel = page._shared_analysis_settings_panel()
    panel.set_model(page.canvas.build_model())
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.MODAL))
    panel.num_modes.setValue(12)
    page._analysis_settings[AnalysisKind.MODAL.value] = panel.build_options()
    page._on_analysis_method_changed()

    assert "저장했습니다" in page.analysis_settings_summary.text()

    linear_index = page.analysis_method_selector.findData(AnalysisKind.LINEAR_STATIC.value)
    page.analysis_method_selector.setCurrentIndex(linear_index)
    page.analysis_method_selector.setCurrentIndex(index)

    assert page._analysis_settings[AnalysisKind.MODAL.value]["num_modes"] == 12
    assert "저장했습니다" in page.analysis_settings_summary.text()


def test_response_spectrum_is_reachable_from_the_tabs_own_method_combo() -> None:
    """Regression test: AnalysisSettingsPanel's own ANALYSIS TYPE combo has
    always offered Response Spectrum, but the 3D tab's ``해석 방법`` combo
    (``_ANALYSIS_METHOD_OPTIONS``) did not - so it was reachable only by
    picking it from *inside* the settings dialog, which is exactly the
    two-controls-for-one-choice confusion that combo is now hidden for (see
    ``test_hides_the_panels_own_kind_selector_and_restores_it_on_detach`` in
    the unit tests). Every kind the panel offers must have a matching row
    here or it becomes unreachable outright."""
    page = _page()

    index = page.analysis_method_selector.findData(AnalysisKind.RESPONSE_SPECTRUM.value)

    assert index >= 0
    page.analysis_method_selector.setCurrentIndex(index)
    assert page.analysis_settings_button.isVisible() is True
    assert page.analysis_run_button.isEnabled() is False  # not wired to execution yet


def test_settings_dialog_hosts_the_same_wide_panel_setup_uses() -> None:
    """Regression test: the 3D tab used to open one of four small dialogs
    (7 controls total) instead of the ~86-control panel SETUP's own
    OpenSeesPy-import flow shows for the same analysis kinds - see
    analysis_settings_dialogs.py's module docstring."""
    from openframe.features.analysis.presentation.analysis_settings_panel import (
        AnalysisSettingsPanel,
    )

    page = _page()
    index = page.analysis_method_selector.findData(AnalysisKind.MODAL.value)
    page.analysis_method_selector.setCurrentIndex(index)

    panel = page._shared_analysis_settings_panel()
    assert isinstance(panel, AnalysisSettingsPanel)
    # Reused, not rebuilt, on a second 설정... click - see its own docstring.
    assert page._shared_analysis_settings_panel() is panel


def test_every_non_linear_method_has_a_settings_dialog_class() -> None:
    page = _page()
    for label, kind, dialog_cls in page._ANALYSIS_METHOD_OPTIONS:
        if kind is AnalysisKind.LINEAR_STATIC:
            assert dialog_cls is None, label
        else:
            assert dialog_cls is not None, label
