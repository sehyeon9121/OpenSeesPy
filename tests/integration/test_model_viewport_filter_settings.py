"""The DISPLAY FILTERS bar used to pack eight controls into one row (five
visibility checkboxes, two load filters, a deformation slider that was never even
wired to anything) and started clipping. Nodes/Node IDs/Elements and the unit
selectors - what nearly every session touches - stay in the bar; Supports, Loads,
LOAD VIEW and LOAD CASE move into a "FILTER SETTINGS..." dialog opened on demand,
with the same Save/Cancel-reverts-changes pattern as the nonlinear settings dialog."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from openframe.features.viewport.presentation.model_viewport import ModelViewport


def test_bar_keeps_only_the_frequently_used_controls() -> None:
    application = QApplication.instance() or QApplication([])
    viewport = ModelViewport()
    viewport.show()
    application.processEvents()

    assert {"node", "node_label", "element"} <= viewport.filter_options.keys()
    for kind in ("node", "node_label", "element"):
        assert viewport.filter_options[kind].parent() is not None
        assert viewport.filter_options[kind].parentWidget().window() is viewport
    assert viewport.open_filter_settings_button.isVisible()
    assert viewport.force_unit_selector.isVisible()
    assert viewport.length_unit_selector.isVisible()
    application.processEvents()


def test_dialog_holds_the_less_common_filters() -> None:
    application = QApplication.instance() or QApplication([])
    viewport = ModelViewport()

    dialog = viewport._filter_settings_dialog
    assert viewport.filter_options["support"].parentWidget().window() is dialog
    assert viewport.filter_options["load"].parentWidget().window() is dialog
    assert viewport.load_view_selector.parentWidget().window() is dialog
    assert viewport.load_case_selector.parentWidget().window() is dialog
    application.processEvents()


def test_cancel_reverts_changes_made_while_the_dialog_was_open() -> None:
    application = QApplication.instance() or QApplication([])
    viewport = ModelViewport()

    viewport.filter_options["load"].setChecked(True)
    viewport.load_view_selector.setCurrentIndex(0)

    def _edit_then_cancel() -> None:
        viewport.filter_options["load"].setChecked(False)
        viewport.load_view_selector.setCurrentIndex(2)
        viewport._filter_settings_dialog.reject()

    QTimer.singleShot(0, _edit_then_cancel)
    viewport._open_filter_settings()

    assert viewport.filter_options["load"].isChecked() is True
    assert viewport.load_view_selector.currentIndex() == 0
    application.processEvents()


def test_save_keeps_changes_made_while_the_dialog_was_open() -> None:
    application = QApplication.instance() or QApplication([])
    viewport = ModelViewport()

    viewport.filter_options["load"].setChecked(True)

    def _edit_then_save() -> None:
        viewport.filter_options["load"].setChecked(False)
        viewport._filter_settings_dialog.accept()

    QTimer.singleShot(0, _edit_then_save)
    viewport._open_filter_settings()

    assert viewport.filter_options["load"].isChecked() is False
    application.processEvents()
