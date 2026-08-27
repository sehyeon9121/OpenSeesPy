"""``AnalysisSettingsDialog`` - the 3D canvas's Analysis tab settings window,
now a thin wrapper hosting the same ``AnalysisSettingsPanel`` SETUP uses
rather than four separate narrow per-kind dialogs. What is actually this
wrapper's own responsibility (not ``AnalysisSettingsPanel``'s, which already
has its own extensive test coverage - see test_analysis_settings_panel.py
and friends): embedding the given panel, returning its ``build_options()``
on accept, and - the one real lifetime hazard a reused, caller-owned widget
introduces - surviving the dialog's own destruction via ``detach()``."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisKind
from openframe.features.analysis.presentation.analysis_settings_panel import AnalysisSettingsPanel
from openframe.features.model.presentation.analysis_settings_dialogs import AnalysisSettingsDialog


def _app() -> None:
    QApplication.instance() or QApplication([])


def test_result_options_delegates_to_the_hosted_panels_build_options() -> None:
    _app()
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.MODAL))
    panel.num_modes.setValue(12)
    dialog = AnalysisSettingsDialog(panel)

    assert dialog.result_options() == panel.build_options()
    assert dialog.result_options()["num_modes"] == 12
    dialog.detach()


def test_detach_reclaims_the_panel_so_it_survives_the_dialogs_own_destruction() -> None:
    """The panel is caller-owned and reused across dialog re-opens (see
    ``ModelingInterfacePage._shared_analysis_settings_panel``) - without
    ``detach()``, the dialog's Qt widget tree would take the panel down with
    it the moment the dialog itself is garbage-collected, silently
    discarding every field the student had entered."""
    _app()
    panel = AnalysisSettingsPanel()
    dialog = AnalysisSettingsDialog(panel)
    assert panel.parent() is not None  # the dialog's QScrollArea owns it while open

    dialog.detach()

    assert panel.parent() is None
    # Still a live, usable widget - not a dangling/deleted C++ object.
    panel.num_modes.setValue(7)
    assert panel.num_modes.value() == 7


def test_dialog_shows_whichever_kind_the_panel_was_set_to_before_opening() -> None:
    """The tab decides which kind to open on (via ``analysis_type.
    setCurrentIndex`` before constructing the dialog, see
    ``_open_analysis_settings_dialog``) - this dialog itself does not
    second-guess that choice."""
    _app()
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.BUCKLING))
    dialog = AnalysisSettingsDialog(panel)

    assert panel.selected_analysis_kind() == AnalysisKind.BUCKLING
    dialog.detach()


def test_hides_the_panels_own_kind_selector_and_restores_it_on_detach() -> None:
    """Regression test: the panel's own ANALYSIS TYPE combo used to stay
    visible inside this dialog, giving a student two different controls
    that both claimed to answer "which analysis is this" - the outer 3D
    tab's 해석 방법 combo already decided that before this dialog ever
    opens. ``isHidden()`` (the widget's own explicit flag), not
    ``isVisible()`` (which also depends on the ancestor chain and reports
    False for any un-parented widget - exactly what this panel is right
    after ``detach()``)."""
    _app()
    panel = AnalysisSettingsPanel()
    assert not panel.analysis_type_row.isHidden()

    dialog = AnalysisSettingsDialog(panel)
    assert panel.analysis_type_row.isHidden()

    dialog.detach()
    assert not panel.analysis_type_row.isHidden()
