"""The 3D free-form canvas's Analysis tab settings dialog (see
``modeling_interface_page.py``'s ``_build_analysis_category``).

Used to be four separate small dialogs (Modal/Buckling/Nonlinear Static/Time
History), each hand-built with a handful of fields "narrower than SETUP's own
``AnalysisSettingsPanel`` (~3000 lines, ~55-70 controls for Time History
alone)" - deliberately so, back when nothing on this side read most of a
real solve's settings and building every field first would have been
speculative UI.

That reasoning stopped holding once the settings genuinely diverged from
what a student configuring the same analysis through "OpenSeesPy 파일
불러오기" -> SETUP would see: 7 controls total across all four dialogs versus
86 in ``AnalysisSettingsPanel``, and English labels ("Ready for Analysis")
next to this canvas's own Korean UI. This module now just hosts that same
panel - the one MODEL's ``AnalysisTypeSelector`` and SETUP already share via
``AnalysisConfigStore`` - in a wide dialog instead of reimplementing a
second, smaller settings surface. ``AnalysisSettingsPanel.set_model()``
already branches correctly on ``model.ndm == 3`` (3D coordinate labels,
6-DOF control-DOF choices, X/Y/Z direction rows), so nothing here needs to
know this is the 3D canvas calling it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QScrollArea, QVBoxLayout, QWidget

from openframe.features.analysis.presentation.analysis_settings_panel import AnalysisSettingsPanel


class AnalysisSettingsDialog(QDialog):
    """Wraps a shared ``AnalysisSettingsPanel`` instance for one settings
    round-trip, then hands it back untouched.

    The panel is a *caller-owned* widget, not created here: its field values
    are how settings persist across dialog re-opens (the panel's own combo
    keeps every kind's widgets live and unreset when switching between
    them - see ``modeling_interface_page._shared_analysis_settings_panel``),
    so a fresh panel per dialog would silently forget everything a student
    entered the moment they closed the window. ``detach()`` must be called
    once this dialog is done with it (accepted or not) so the panel survives
    this dialog's own destruction instead of being deleted along with its
    Qt widget tree.
    """

    def __init__(self, panel: AnalysisSettingsPanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("해석 설정")
        # Wide enough for the panel's own 896px settings surface plus margins
        # and a scrollbar, tall enough that Time History's ground-motion rows
        # do not force the dialog itself off-screen - matches this codebase's
        # other big precision-analysis surfaces rather than staying pinned to
        # the canvas's own 320px panel budget.
        self.resize(1040, 780)
        self._panel = panel
        # This dialog only ever opens after the 3D tab's own 해석 방법 combo
        # already picked a kind (see ModelingInterfacePage._open_analysis_
        # settings_dialog) - showing the panel's own ANALYSIS TYPE row on top
        # of that gave a student two different controls that both claimed to
        # answer the same question. Restored on detach() so the panel goes
        # back to its default, combo-visible state for whatever comes next.
        panel.analysis_type_row.setVisible(False)

        layout = QVBoxLayout(self)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(panel)
        layout.addWidget(self._scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def detach(self) -> None:
        """Reclaim the shared panel before this dialog is garbage-collected.

        ``QScrollArea.takeWidget()`` un-parents it without deleting it, the
        same lifetime hazard ``_CurrentPageOnlyStack`` and other reused-widget
        spots in this codebase already have to account for - a widget stays
        alive only as long as something outside the closing dialog is holding
        a reference to it.
        """
        self._panel.analysis_type_row.setVisible(True)
        self._scroll.takeWidget()

    def result_options(self) -> dict[str, float | int | str | bool]:
        return self._panel.build_options()
