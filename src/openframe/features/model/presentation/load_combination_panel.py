"""Editable list of load combinations - layout only, not wired to the canvas
or solver yet.

Building the UI ahead of the wiring on purpose: the underlying engine work
(see ``core.domain.load_combination.LoadCombination``, still just a plain
data holder) and this panel can each be reviewed on their own before the
third piece - actually running one combination through the solver and
showing its own result set - gets built on top of both. ``LoadCombinationPanel``
is a self-contained ``QWidget`` so it can be dropped into whichever page ends
up hosting it (a 하중 category tab, its own workbench tab, ...) without that
decision being made here.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import LoadCaseKind, LoadCombination
from openframe.features.model.presentation.model_sidebar import LOAD_CASE_PRESENTATION

#: UNCLASSIFIED is deliberately excluded - see LoadCombination.factor_for's
#: own docstring for why a load nobody tagged with a case should never be
#: swept into a combination by omission.
_COMBINABLE_CASES: tuple[LoadCaseKind, ...] = (
    LoadCaseKind.DEAD,
    LoadCaseKind.LIVE,
    LoadCaseKind.SEISMIC,
    LoadCaseKind.WIND,
    LoadCaseKind.OTHER,
)


class LoadCombinationRow(QFrame):
    """One editable combination: a name field plus a factor spinbox per
    combinable load case. Reads out as a ``LoadCombination`` on demand
    (``to_combination``) rather than emitting one on every keystroke - the
    eventual wiring step decides when a live combination list actually needs
    to be recomputed, not this row.
    """

    removed = Signal(QFrame)

    def __init__(
        self,
        name: str = "",
        factors: dict[LoadCaseKind, float] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("loadCombinationRow")
        factors = factors or {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self.name_edit = QLineEdit(name)
        self.name_edit.setObjectName("loadCombinationNameEdit")
        self.name_edit.setPlaceholderText("조합 이름 (예: 1.2DL+1.6LL)")
        self.name_edit.setMinimumWidth(140)
        layout.addWidget(self.name_edit)

        self.factor_spinboxes: dict[LoadCaseKind, QDoubleSpinBox] = {}
        for case in _COMBINABLE_CASES:
            label_text, _color = LOAD_CASE_PRESENTATION[case]
            column = QVBoxLayout()
            column.setSpacing(2)
            case_label = QLabel(label_text)
            case_label.setObjectName("loadCombinationCaseLabel")
            column.addWidget(case_label)
            spin = QDoubleSpinBox()
            spin.setObjectName("loadCombinationFactorSpin")
            spin.setRange(-100.0, 100.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setValue(factors.get(case, 0.0))
            column.addWidget(spin)
            self.factor_spinboxes[case] = spin
            layout.addLayout(column)

        layout.addStretch(1)
        self.remove_button = QPushButton("삭제")
        self.remove_button.setObjectName("loadCombinationRemoveButton")
        self.remove_button.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.remove_button)

    def to_combination(self) -> LoadCombination:
        factors = {
            case: spin.value()
            for case, spin in self.factor_spinboxes.items()
            if spin.value() != 0.0
        }
        return LoadCombination(name=self.name_edit.text().strip() or "조합", factors=factors)


class LoadCombinationPanel(QWidget):
    """Add/remove/edit any number of ``LoadCombinationRow``s.

    ``combinations()``/``set_combinations()`` are the only two entry points a
    future wiring step needs - everything else here is presentation.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("loadCombinationPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("하중조합")
        title.setObjectName("taskPanelTitle")
        root.addWidget(title)

        hint = QLabel(
            "고정하중·활하중 등 서로 다른 하중 케이스를 계수와 함께 더해 하나의 "
            "해석 케이스로 만듭니다 (예: 1.2×고정하중 + 1.6×활하중). 계수를 "
            "0으로 두면 해당 케이스는 이 조합에서 빠집니다."
        )
        hint.setObjectName("setupSectionHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch(1)
        self._rows: list[LoadCombinationRow] = []

        scroll = QScrollArea()
        scroll.setObjectName("loadCombinationScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._rows_container)
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        root.addWidget(scroll, 1)

        self.empty_hint = QLabel("아직 만든 하중조합이 없습니다. 아래에서 추가하세요.")
        self.empty_hint.setObjectName("setupSectionHint")
        self.empty_hint.setWordWrap(True)
        root.addWidget(self.empty_hint)

        add_button = QPushButton("+ 조합 추가")
        add_button.setObjectName("loadCombinationAddButton")
        add_button.clicked.connect(lambda: self.add_row())
        root.addWidget(add_button)

        self._sync_empty_hint()

    def add_row(
        self, name: str = "", factors: dict[LoadCaseKind, float] | None = None
    ) -> LoadCombinationRow:
        row = LoadCombinationRow(name, factors)
        row.removed.connect(self._remove_row)
        self._rows.append(row)
        # Insert before the trailing stretch, which must always stay last so
        # the rows themselves stack from the top instead of centering/
        # spreading across the scroll area's full height.
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._sync_empty_hint()
        return row

    def _remove_row(self, row: LoadCombinationRow) -> None:
        if row not in self._rows:
            return
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._sync_empty_hint()

    def _sync_empty_hint(self) -> None:
        self.empty_hint.setVisible(not self._rows)

    def combinations(self) -> list[LoadCombination]:
        return [row.to_combination() for row in self._rows]

    def set_combinations(self, combinations: list[LoadCombination]) -> None:
        for row in list(self._rows):
            self._remove_row(row)
        for combination in combinations:
            self.add_row(combination.name, dict(combination.factors))
