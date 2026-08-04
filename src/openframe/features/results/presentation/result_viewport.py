"""Structural result canvas with deformation overlay controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    NodeResult,
    StructuralModel,
    UnitSystem,
)
from openframe.features.results.diagrams import DiagramKind
from openframe.features.results.presentation.frame_diagram_renderer import (
    FrameDiagramRenderer,
)
from openframe.features.viewport.scene import StructuralScene

RESULT_TYPE_NAMES = {
    "overview": "RESULT OVERVIEW",
    "deformation": "DEFORMED SHAPE",
    "displacement": "NODAL DISPLACEMENTS",
    "reaction": "SUPPORT REACTIONS",
    "axial": "AXIAL FORCE (N)",
    "shear": "SHEAR FORCE (V)",
    "moment": "BENDING MOMENT (M)",
    "tables": "RESULT TABLES",
}


class ResultViewport(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultViewport")
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._result_type = "overview"
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._diagram_renderer = FrameDiagramRenderer()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        canvas_header = QFrame()
        canvas_header.setObjectName("resultCanvasHeader")
        header_layout = QHBoxLayout(canvas_header)
        header_layout.setContentsMargins(10, 6, 8, 6)
        self.mode_badge = QLabel(RESULT_TYPE_NAMES[self._result_type])
        self.mode_badge.setObjectName("resultModeBadge")
        header_layout.addWidget(self.mode_badge)
        header_layout.addStretch(1)
        zoom_out = self._tool_button("−")
        zoom_in = self._tool_button("+")
        fit = self._tool_button("FIT")
        header_layout.addWidget(zoom_out)
        header_layout.addWidget(zoom_in)
        header_layout.addWidget(fit)
        layout.addWidget(canvas_header)

        self.scene = StructuralScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setObjectName("resultGraphicsView")
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        layout.addWidget(self.view, 1)

        controls = QFrame()
        controls.setObjectName("resultViewportControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 5, 10, 5)
        self.show_undeformed = QCheckBox("UNDEFORMED SHAPE")
        self.show_undeformed.setChecked(True)
        self.show_undeformed.toggled.connect(self._redraw)
        controls_layout.addWidget(self.show_undeformed)
        controls_layout.addStretch(1)
        self.scale_caption = QLabel("DEFORMATION SCALE")
        controls_layout.addWidget(self.scale_caption)
        self.deformation_scale = QSlider(Qt.Orientation.Horizontal)
        self.deformation_scale.setRange(1, 200)
        self.deformation_scale.setValue(30)
        self.deformation_scale.setMaximumWidth(130)
        self.deformation_scale.valueChanged.connect(self._redraw)
        controls_layout.addWidget(self.deformation_scale)
        self.scale_value = QLabel("x30")
        self.scale_value.setObjectName("resultScaleValue")
        controls_layout.addWidget(self.scale_value)
        layout.addWidget(controls)

        zoom_in.clicked.connect(lambda: self.view.scale(1.2, 1.2))
        zoom_out.clicked.connect(lambda: self.view.scale(1 / 1.2, 1 / 1.2))
        fit.clicked.connect(self.fit_model)

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self._redraw()
        self.fit_model()

    def show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._redraw()
        self.fit_model()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self.scene.set_unit_system(unit_system)
        self._redraw()

    def set_result_type(self, result_type: str) -> None:
        self._result_type = result_type
        self.mode_badge.setText(RESULT_TYPE_NAMES.get(result_type, result_type.upper()))
        self._redraw()
        self.fit_model()

    def fit_model(self) -> None:
        if not self.scene.items():
            return
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _redraw(self) -> None:
        force_diagram = self._result_type in {"axial", "shear", "moment"}
        self.scale_caption.setText("DIAGRAM SCALE" if force_diagram else "DEFORMATION SCALE")
        self.scale_value.setText(
            f"{self.deformation_scale.value()}%"
            if force_diagram
            else f"x{self.deformation_scale.value()}"
        )
        if self._model is None:
            self.scene.clear()
            self.scene.setSceneRect(-8.0, -5.0, 16.0, 9.0)
            return

        self.scene.set_model(self._model)
        for item in self.scene.items():
            identity = item.data(0)
            if not isinstance(identity, tuple) or not identity:
                continue
            if identity[0] in {"load", "node_label"}:
                item.setVisible(False)
            elif identity[0] in {"node", "element"}:
                item.setVisible(self.show_undeformed.isChecked())
                if force_diagram and identity[0] == "element":
                    base_pen = QPen(QColor("#26364a"), 2.7)
                    base_pen.setCosmetic(True)
                    item.setPen(base_pen)

        self._draw_deformed_shape()
        diagram_offset = self._draw_force_diagram()
        x_values = [node.x for node in self._model.nodes.values()]
        y_values = [-node.y for node in self._model.nodes.values()]
        if x_values and y_values:
            span = max(max(x_values) - min(x_values), max(y_values) - min(y_values), 1.0)
            margin = max(span * 0.2, diagram_offset * 1.35)
            self.scene.setSceneRect(
                min(x_values) - margin,
                min(y_values) - margin,
                max(x_values) - min(x_values) + 2 * margin,
                max(y_values) - min(y_values) + 2 * margin,
            )

    def _draw_deformed_shape(self) -> None:
        if self._model is None or self._result is None:
            return
        if self._result_type not in {"overview", "deformation", "displacement"}:
            return

        scale = float(self.deformation_scale.value())
        pen = QPen(QColor("#e5484d"), 2.4)
        pen.setCosmetic(True)
        for element in self._model.elements.values():
            node_i = self._model.nodes[element.node_i]
            node_j = self._model.nodes[element.node_j]
            result_i = self._result.node_results.get(node_i.tag)
            result_j = self._result.node_results.get(node_j.tag)
            ux_i, uy_i = self._translation(result_i)
            ux_j, uy_j = self._translation(result_j)
            line = QGraphicsLineItem(
                node_i.x + ux_i * scale,
                -(node_i.y + uy_i * scale),
                node_j.x + ux_j * scale,
                -(node_j.y + uy_j * scale),
            )
            line.setPen(pen)
            line.setZValue(8.0)
            line.setData(0, ("result_deformation", element.tag))
            line.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self.scene.addItem(line)

    def _draw_force_diagram(self) -> float:
        if self._model is None or self._result is None:
            return 0.0
        kinds = {
            "axial": DiagramKind.AXIAL,
            "shear": DiagramKind.SHEAR,
            "moment": DiagramKind.MOMENT,
        }
        kind = kinds.get(self._result_type)
        if kind is None:
            return 0.0
        unit = (
            self._unit_system.moment
            if kind == DiagramKind.MOMENT
            else self._unit_system.force
        )
        return self._diagram_renderer.render(
            self.scene,
            self._model,
            self._result,
            kind,
            self.deformation_scale.value(),
            unit,
        )

    @staticmethod
    def _translation(node_result: NodeResult | None) -> tuple[float, float]:
        if node_result is None:
            return 0.0, 0.0
        displacement = node_result.displacement
        ux = displacement[0] if len(displacement) > 0 else 0.0
        uy = displacement[1] if len(displacement) > 1 else 0.0
        return ux, uy

    @staticmethod
    def _tool_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("resultCanvasButton")
        return button
