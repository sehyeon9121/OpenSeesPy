"""Regression coverage for MODEL's Analysis Type panel staying a read-only
mirror of what SETUP actually has selected.

``AnalysisTypeSelector`` used to offer its own four analysis-kind buttons,
duplicating the exact same choice ``AnalysisSettingsPanel`` asks on SETUP one
click later. It now only shows a summary of the shared ``AnalysisConfigStore``
and a shortcut to SETUP - the kind is chosen there, not here."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.setup_workspace import SetupWorkspace
from openframe.core.domain import AnalysisKind
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)
from openframe.features.analysis.presentation.analysis_type_selector import (
    _KIND_LABELS,
    AnalysisTypeSelector,
)

ALL_KINDS = {
    AnalysisKind.LINEAR_STATIC,
    AnalysisKind.NONLINEAR_STATIC,
    AnalysisKind.MODAL,
    AnalysisKind.TIME_HISTORY,
    AnalysisKind.BUCKLING,
}


def test_every_analysis_kind_has_a_label_for_the_summary_text() -> None:
    """Pins the fixed state a stale-label bug once broke: every AnalysisKind the
    backend actually supports (see RunAnalysisService's module registration in
    bootstrap.py) must be nameable in MODEL's summary, or picking it in SETUP
    would show up here as a raw enum repr instead of a readable label."""
    assert set(_KIND_LABELS.keys()) == ALL_KINDS


def test_model_screen_shows_no_interactive_kind_picker() -> None:
    """The four analysis-kind buttons are gone - SETUP is now the only place
    that changes the kind, so this panel has nothing to click for that."""
    application = QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    selector = AnalysisTypeSelector(store)

    assert not hasattr(selector, "_option_buttons")
    assert selector.open_setup_button is not None

    application.processEvents()
    selector.close()


def test_model_summary_reflects_the_kind_chosen_on_setup() -> None:
    """MODEL's summary and SETUP's dropdown share one AnalysisConfigStore - a
    kind picked on SETUP must show up in MODEL's summary without any extra
    action, since MODEL can no longer set it directly."""
    application = QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    selector = AnalysisTypeSelector(store)
    setup = SetupWorkspace(store)

    index = setup.settings_panel.analysis_type.findData(AnalysisKind.MODAL)
    setup.settings_panel.analysis_type.setCurrentIndex(index)
    application.processEvents()
    assert "Modal (Eigenvalue)" in selector.summary_label.text()

    index = setup.settings_panel.analysis_type.findData(AnalysisKind.TIME_HISTORY)
    setup.settings_panel.analysis_type.setCurrentIndex(index)
    application.processEvents()
    assert "Time History" in selector.summary_label.text()

    selector.close()
    setup.close()


def test_open_setup_button_emits_the_navigation_signal() -> None:
    application = QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    selector = AnalysisTypeSelector(store)
    received = []
    selector.open_setup_requested.connect(lambda: received.append(True))

    selector.open_setup_button.click()

    assert received == [True]
    application.processEvents()
    selector.close()
