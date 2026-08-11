"""Force-diagram graph for the active result quantity.

The full numeric table lives in ``ResultTablesPanel`` (the "Result Tables"
result type) instead of here — this panel only ever showed one force
diagram's i-end at a time, squeezed into the bottom splitter.
"""

from collections.abc import Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.diagrams import member_diagrams
from openframe.features.results.presentation.diagram_plot import DiagramPlot


class ResultDataPanel(QFrame):
    member_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultDataPanel")
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._result_type = "overview"
        self._unit_system = DEFAULT_UNIT_SYSTEM

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        panel_header = QFrame()
        panel_header.setObjectName("resultDataHeader")
        header_layout = QHBoxLayout(panel_header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        self.quantity_label = QLabel("BENDING MOMENT (M)")
        self.quantity_label.setObjectName("resultDataTitle")
        header_layout.addWidget(self.quantity_label)
        header_layout.addStretch(1)
        self.graph_zoom_out = self._graph_tool_button("-", "그래프 축소")
        self.graph_zoom_in = self._graph_tool_button("+", "그래프 확대")
        self.graph_fit = self._graph_tool_button("FIT", "그래프 전체 맞춤")
        header_layout.addWidget(self.graph_zoom_out)
        header_layout.addWidget(self.graph_zoom_in)
        header_layout.addWidget(self.graph_fit)
        header_layout.addWidget(QLabel("ELEMENT"))
        self.member_selector = QComboBox()
        self.member_selector.setObjectName("resultDataMemberSelector")
        self.member_selector.setMaximumWidth(135)
        self.member_selector.currentIndexChanged.connect(self._member_selected)
        header_layout.addWidget(self.member_selector)
        layout.addWidget(panel_header)

        graph_page = QFrame()
        graph_layout = QVBoxLayout(graph_page)
        graph_layout.setContentsMargins(8, 4, 8, 6)
        self.diagram_plot = DiagramPlot()
        self.graph_zoom_out.clicked.connect(self.diagram_plot.zoom_out)
        self.graph_zoom_in.clicked.connect(self.diagram_plot.zoom_in)
        self.graph_fit.clicked.connect(self.diagram_plot.fit_to_view)
        graph_layout.addWidget(self.diagram_plot)
        layout.addWidget(graph_page, 1)

        self._refresh()

    @staticmethod
    def _graph_tool_button(text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("resultGraphToolButton")
        button.setText(text)
        button.setToolTip(tooltip)
        return button

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self._refresh()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self._refresh()

    def show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._fill_member_selector(sorted(result.element_results))
        self._refresh()

    def clear_result(self) -> None:
        """Drop the tabulated result so a new model never shows the previous one."""
        self._result = None
        self._fill_member_selector(())
        self._refresh()

    def _fill_member_selector(self, element_tags: Sequence[int]) -> None:
        self.member_selector.blockSignals(True)
        self.member_selector.clear()
        for element_tag in element_tags:
            self.member_selector.addItem(f"Element {element_tag}", element_tag)
        self.member_selector.blockSignals(False)

    def set_result_type(self, result_type: str) -> None:
        self._result_type = result_type
        self._refresh()

    def select_member(self, element_tag: int) -> None:
        index = self.member_selector.findData(element_tag)
        if index >= 0 and index != self.member_selector.currentIndex():
            self.member_selector.blockSignals(True)
            self.member_selector.setCurrentIndex(index)
            self.member_selector.blockSignals(False)
            self._refresh()

    def _member_selected(self) -> None:
        self._refresh()
        element_tag = self.member_selector.currentData()
        if element_tag is not None:
            self.member_changed.emit(int(element_tag))

    def _refresh(self) -> None:
        force_keys = {"axial": 0, "shear": 1, "moment": 2}
        diagram_key = self._result_type if self._result_type in force_keys else "moment"
        names = {
            "axial": "AXIAL FORCE (N)",
            "shear": "SHEAR FORCE (V)",
            "moment": "BENDING MOMENT (M)",
        }
        # The graph always plots a member force, but the header names what the table shows.
        self.quantity_label.setText(
            "SUPPORT REACTIONS" if self._result_type == "reaction" else names[diagram_key]
        )

        diagram = None
        element_tag = self.member_selector.currentData()
        if (
            self._result is not None
            and element_tag is not None
            and (self._model is None or self._model.ndm == 2)
        ):
            element = self._result.element_results.get(element_tag)
            if element is not None:
                try:
                    diagram = member_diagrams(element)[force_keys[diagram_key]]
                except ValueError:
                    diagram = None
        unit = (
            self._unit_system.moment
            if diagram_key == "moment"
            else self._unit_system.force
        )
        self.diagram_plot.set_diagram(diagram, unit)

