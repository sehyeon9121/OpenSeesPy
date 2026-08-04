"""Structural result canvas with deformation overlay controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
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
from openframe.features.results.deformation import (
    largest_displacement,
    member_deflection,
    nodal_displacements,
)
from openframe.features.results.diagrams import DiagramKind
from openframe.features.results.magnitudes import magnitude_range, member_magnitudes
from openframe.features.results.presentation.frame_diagram_renderer import (
    FrameDiagramRenderer,
)
from openframe.features.results.presentation.node_displacement_item import (
    NodeDisplacementItem,
)
from openframe.features.results.presentation.result_color_scale import (
    color_for_ratio,
    ratio_of,
)
from openframe.features.results.presentation.support_reaction_item import (
    SupportReactionItem,
)
from openframe.features.results.reactions import support_reactions
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

    def clear_result(self) -> None:
        """Drop the drawn result so a new model never shows the previous one."""
        self._result = None
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
        magnitudes = self._member_magnitudes()
        _, peak = magnitude_range(magnitudes)
        for item in self.scene.items():
            identity = item.data(0)
            if not isinstance(identity, tuple) or not identity:
                continue
            if identity[0] in {"load", "node_label"}:
                item.setVisible(False)
            elif identity[0] in {"node", "element"}:
                item.setVisible(self.show_undeformed.isChecked())
                if identity[0] == "element" and magnitudes:
                    # Colour the member by how large the active quantity is on it, so the
                    # legend beside the viewport reads as a real scale.
                    ratio = ratio_of(magnitudes.get(identity[1], 0.0), peak)
                    member_pen = QPen(color_for_ratio(ratio), 2.7)
                    member_pen.setCosmetic(True)
                    item.setPen(member_pen)
                elif identity[0] == "element" and force_diagram:
                    base_pen = QPen(QColor("#26364a"), 2.7)
                    base_pen.setCosmetic(True)
                    item.setPen(base_pen)

        self._draw_deformed_shape()
        self._draw_nodal_displacements()
        self._draw_support_reactions()
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

    def _member_magnitudes(self) -> dict[int, float]:
        if self._model is None or self._result is None:
            return {}
        return member_magnitudes(self._model, self._result, self._result_type)

    def _draw_deformed_shape(self) -> None:
        if self._model is None or self._result is None:
            return
        if self._result_type not in {"overview", "deformation", "displacement"}:
            return

        scale = float(self.deformation_scale.value())
        pen = QPen(QColor("#e5484d"), 2.4)
        pen.setCosmetic(True)
        for element_tag in self._model.elements:
            stations = member_deflection(self._model, self._result, element_tag)
            if len(stations) < 2:
                continue
            # A curve through the rebuilt stations, so a member that sags between two
            # fixed nodes is drawn sagging instead of straight.
            path = QPainterPath()
            path.moveTo(
                stations[0].x + stations[0].ux * scale,
                -(stations[0].y + stations[0].uy * scale),
            )
            for station in stations[1:]:
                path.lineTo(
                    station.x + station.ux * scale,
                    -(station.y + station.uy * scale),
                )
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(8.0)
            item.setData(0, ("result_deformation", element_tag))
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self.scene.addItem(item)

    #: Above this many moving nodes every label would overlap, so only the largest
    #: displacement is named and the rest are read from the table or a tooltip.
    _LABEL_ALL_LIMIT = 20

    def _draw_nodal_displacements(self) -> None:
        if self._model is None or self._result is None:
            return
        if self._result_type != "displacement":
            return

        displacements = nodal_displacements(self._model, self._result)
        moving = [item for item in displacements if item.moves]
        if not moving:
            return
        peak = largest_displacement(displacements)
        label_all = len(moving) <= self._LABEL_ALL_LIMIT

        scale = float(self.deformation_scale.value())
        connector_pen = QPen(QColor("#b4530a"), 1.2, Qt.PenStyle.DashLine)
        connector_pen.setCosmetic(True)

        for item in moving:
            displaced_x = item.x + item.ux * scale
            displaced_y = -(item.y + item.uy * scale)
            connector = QGraphicsLineItem(item.x, -item.y, displaced_x, displaced_y)
            connector.setPen(connector_pen)
            connector.setZValue(8.5)
            connector.setData(0, ("result_displacement_vector", item.node_tag))
            self.scene.addItem(connector)

            is_peak = peak is not None and item.node_tag == peak.node_tag
            marker = NodeDisplacementItem(
                item,
                is_peak=is_peak,
                show_label=label_all or is_peak,
                unit_system=self._unit_system,
            )
            marker.setPos(displaced_x, displaced_y)
            self.scene.addItem(marker)

    def _draw_support_reactions(self) -> None:
        if self._model is None or self._result is None:
            return
        if self._result_type not in {"overview", "reaction"}:
            return

        for reaction in support_reactions(self._model, self._result):
            if not (reaction.has_force or reaction.has_moment):
                continue
            item = SupportReactionItem(reaction, self._unit_system)
            item.setPos(reaction.x, -reaction.y)
            self.scene.addItem(item)

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
