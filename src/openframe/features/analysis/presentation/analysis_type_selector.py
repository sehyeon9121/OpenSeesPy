"""Lightweight MODEL-page widget: pick an analysis type, then jump to SETUP.

Deliberately thin - no solver/nonlinear fields live here. It shares an
``AnalysisConfigStore`` with the full ``AnalysisSettingsPanel`` inside SETUP,
so picking a kind here and reviewing/editing it there can never disagree.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisKind
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)

_KIND_LABELS = {
    AnalysisKind.LINEAR_STATIC: "Linear Static",
    AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
    AnalysisKind.TIME_HISTORY: "Time History",
}

#: Kinds without a working AnalysisModule.run() yet - offered so the option is
#: visible (it is a real enum member with a SETUP page), but disabled with an
#: honest tooltip instead of silently letting RUN fail later.
_UNIMPLEMENTED_KINDS = frozenset({AnalysisKind.TIME_HISTORY})


class AnalysisTypeSelector(QFrame):
    open_setup_requested = Signal()

    def __init__(self, config_store: AnalysisConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisTypeSelector")
        self.config_store = config_store
        self._option_buttons: dict[AnalysisKind, QToolButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header("ANALYSIS PREPARATION"))

        body = QFrame()
        body.setObjectName("rightSection")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 14)
        body_layout.setSpacing(6)

        self._option_group = QButtonGroup(self)
        self._option_group.setExclusive(True)
        for kind, label in _KIND_LABELS.items():
            button = QToolButton()
            button.setObjectName("analysisTypeOption")
            button.setText(label)
            button.setCheckable(True)
            button.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            if kind in _UNIMPLEMENTED_KINDS:
                button.setEnabled(False)
                button.setToolTip(f"{label} is not implemented yet.")
            else:
                button.clicked.connect(lambda checked=False, k=kind: self._option_clicked(k))
            self._option_group.addButton(button)
            self._option_buttons[kind] = button
            body_layout.addWidget(button)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("secondaryText")
        self.summary_label.setWordWrap(True)
        body_layout.addSpacing(4)
        body_layout.addWidget(self.summary_label)

        self.open_setup_button = QPushButton("OPEN SETUP PAGE  →")
        self.open_setup_button.setObjectName("openSetupButton")
        self.open_setup_button.clicked.connect(self.open_setup_requested)
        body_layout.addWidget(self.open_setup_button)
        body_layout.addStretch(1)
        layout.addWidget(body)

        self.config_store.kind_changed.connect(self._on_store_kind_changed)
        self.config_store.options_changed.connect(self._update_summary)
        self._select_button(self.config_store.kind)
        self._update_summary()

    def _option_clicked(self, kind: AnalysisKind) -> None:
        self.config_store.set_kind(kind)
        self._update_summary()

    def _on_store_kind_changed(self, kind: AnalysisKind) -> None:
        self._select_button(kind)
        self._update_summary()

    def _select_button(self, kind: AnalysisKind) -> None:
        button = self._option_buttons.get(kind)
        if button is not None:
            button.setChecked(True)

    def _update_summary(self) -> None:
        kind_label = _KIND_LABELS.get(self.config_store.kind, str(self.config_store.kind))
        solver = self.config_store.options.get("system", "BandGeneral")
        self.summary_label.setText(f"Selected: {kind_label}\nSolver: {solver}")

    def _header(self, text: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panelHeader")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.addWidget(QLabel(text))
        return frame
