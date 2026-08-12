"""Regression coverage for MODEL's Analysis Type selector staying in sync with
what is actually implemented.

``AnalysisTypeSelector`` used to ship with a stale ``_UNIMPLEMENTED_KINDS`` set
(left over from before Time History was wired up end-to-end) and a
``_KIND_LABELS`` mapping missing ``AnalysisKind.MODAL`` entirely - so MODEL's
"ANALYSIS PREPARATION" panel offered only 2 of the 4 fully working analysis
kinds, even though SETUP's own dropdown (and the backend's
``RunAnalysisService``) already supported all four. These tests pin the fixed
state: all four kinds selectable from MODEL, and picking one there is
immediately visible in SETUP through the shared ``AnalysisConfigStore``."""

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
    _UNIMPLEMENTED_KINDS,
    AnalysisTypeSelector,
)

ALL_KINDS = {
    AnalysisKind.LINEAR_STATIC,
    AnalysisKind.NONLINEAR_STATIC,
    AnalysisKind.MODAL,
    AnalysisKind.TIME_HISTORY,
}


def test_all_four_analysis_kinds_have_a_label_and_none_are_marked_unimplemented() -> None:
    """Pins the stale-state bug fixed: every AnalysisKind the backend actually
    supports (see RunAnalysisService's module registration in bootstrap.py)
    must have a MODEL-page label and must not be disabled as unimplemented."""
    assert set(_KIND_LABELS.keys()) == ALL_KINDS
    assert _UNIMPLEMENTED_KINDS == frozenset()


def test_model_screen_offers_all_four_analysis_kinds_as_enabled_buttons() -> None:
    application = QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    selector = AnalysisTypeSelector(store)

    assert set(selector._option_buttons.keys()) == ALL_KINDS
    for kind, button in selector._option_buttons.items():
        assert button.isEnabled(), f"{kind} should be selectable from MODEL"

    application.processEvents()
    selector.close()


def test_selecting_modal_on_model_screen_updates_the_shared_store() -> None:
    application = QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    selector = AnalysisTypeSelector(store)

    selector._option_buttons[AnalysisKind.MODAL].click()

    assert store.kind == AnalysisKind.MODAL
    application.processEvents()
    selector.close()


def test_selecting_time_history_on_model_screen_updates_the_shared_store() -> None:
    application = QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    selector = AnalysisTypeSelector(store)

    selector._option_buttons[AnalysisKind.TIME_HISTORY].click()

    assert store.kind == AnalysisKind.TIME_HISTORY
    application.processEvents()
    selector.close()


def test_analysis_type_chosen_on_model_screen_is_immediately_reflected_in_setup() -> None:
    """MODEL's selector and SETUP's dropdown share one AnalysisConfigStore - a
    kind picked on one must show up on the other without any extra action."""
    application = QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    selector = AnalysisTypeSelector(store)
    setup = SetupWorkspace(store)

    selector._option_buttons[AnalysisKind.MODAL].click()
    application.processEvents()
    assert setup.settings_panel.analysis_type.currentData() == AnalysisKind.MODAL

    selector._option_buttons[AnalysisKind.TIME_HISTORY].click()
    application.processEvents()
    assert setup.settings_panel.analysis_type.currentData() == AnalysisKind.TIME_HISTORY

    selector.close()
    setup.close()
