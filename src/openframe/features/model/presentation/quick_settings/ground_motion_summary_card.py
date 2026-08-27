"""Small read-only summary card for one direction's selected ground motion -
Record 이름/PGA/dt/Duration/Unit/Final Scale, per the Time History Quick
Settings spec. Ground motion *selection* itself happens in the (not yet
built) Ground Motion Manager detail dialog; this card only ever displays
whatever ``set_selection`` is given - it has no picker, no file dialog, no
catalog access of its own.

``selection`` is a plain JSON-safe dict (not a dataclass) so it round-trips
through ``AnalysisCase.settings`` (still a plain dict in this pass - see
``analysis_case.py``'s own docstring) without any extra serialization code:
``{"name": str, "pga": float, "dt": float, "duration": float, "unit": str,
"final_scale": float}``, or ``None`` for "nothing selected yet".
"""

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class GroundMotionSummaryCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("groundMotionSummaryCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)
        self._empty_label = QLabel("지진파: 선택 안 됨")
        self._empty_label.setObjectName("setupSectionHint")
        layout.addWidget(self._empty_label)

        self._rows: dict[str, QLabel] = {}
        for key, label in (
            ("name", "Record"),
            ("pga", "PGA"),
            ("dt", "dt"),
            ("duration", "Duration"),
            ("unit", "Unit"),
            ("final_scale", "Final Scale"),
        ):
            row = QLabel()
            row.setObjectName("setupSectionHint")
            row.setVisible(False)
            layout.addWidget(row)
            self._rows[key] = row
        self._row_prefixes = {
            "name": "Record",
            "pga": "PGA",
            "dt": "dt",
            "duration": "Duration",
            "unit": "Unit",
            "final_scale": "Final Scale",
        }
        self._current_selection: dict[str, object] | None = None
        self.set_selection(None)

    def set_selection(self, selection: dict[str, object] | None) -> None:
        self._current_selection = selection
        self._empty_label.setVisible(selection is None)
        for key, row in self._rows.items():
            if selection is None or key not in selection:
                row.setVisible(False)
                continue
            row.setVisible(True)
            row.setText(f"{self._row_prefixes[key]}: {selection[key]}")

    @property
    def current_selection(self) -> dict[str, object] | None:
        return self._current_selection
