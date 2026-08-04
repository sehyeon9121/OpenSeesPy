"""Analysis type and solver settings panel."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from openframe.core.domain import AnalysisKind


class AnalysisSettingsPanel(QFrame):
    analysis_kind_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisSettingsPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header("ANALYSIS SETTINGS"))

        settings = QFrame()
        settings.setObjectName("rightSection")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(14, 12, 14, 14)
        settings_layout.setSpacing(7)

        settings_layout.addWidget(self._field_label("ANALYSIS TYPE"))
        self.analysis_type = QComboBox()
        self.analysis_type.addItem("Linear Static", AnalysisKind.LINEAR_STATIC)
        self.analysis_type.addItem("Nonlinear Static", AnalysisKind.NONLINEAR_STATIC)
        self.analysis_type.addItem("Time History", AnalysisKind.TIME_HISTORY)
        self.analysis_type.currentIndexChanged.connect(self._emit_analysis_kind)
        settings_layout.addWidget(self.analysis_type)

        settings_layout.addWidget(self._field_label("SOLVER"))
        self.solver = QComboBox()
        self.solver.addItems(("BandGeneral", "UmfPack", "ProfileSPD"))
        settings_layout.addWidget(self.solver)
        layout.addWidget(settings)

    def selected_analysis_kind(self) -> AnalysisKind:
        return AnalysisKind(self.analysis_type.currentData())

    def _emit_analysis_kind(self) -> None:
        self.analysis_kind_changed.emit(self.selected_analysis_kind())

    def _header(self, text: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panelHeader")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.addWidget(QLabel(text))
        return frame

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

