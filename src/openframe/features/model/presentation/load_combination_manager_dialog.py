"""Load Combination Manager - the first real host for
``LoadCombinationPanel`` (its own module docstring: "layout only, not wired
to the canvas or solver yet"). Combinations here are keyed by
``LoadCaseKind`` (Dead/Live/Wind/...), not by an individual named
``LoadCase`` - that is the panel's existing, already-built shape and this
dialog does not change it; only "Add" combinations are supported (Envelope/
code-based auto-generation are out of scope, matching the panel's own
docstring and this feature's own exclusions).

Unlike ``LoadCaseManagerDialog``, edits here are staged until "저장" -
matching ``LoadCombinationPanel``'s own design (``combinations()``/
``set_combinations()`` as its only two entry points, built before any
wiring existed), rather than retrofitting it into a live-apply-per-row model.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from openframe.features.model.presentation.load_combination_panel import LoadCombinationPanel


class LoadCombinationManagerDialog(QDialog):
    def __init__(self, canvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self.setWindowTitle("Load Combination Manager")
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        self.panel = LoadCombinationPanel()
        self.panel.set_combinations(list(canvas.load_combinations.values()))
        layout.addWidget(self.panel, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        self._canvas.replace_load_combinations(self.panel.combinations())
        self.accept()
