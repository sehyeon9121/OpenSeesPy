"""Structural result canvas with deformation overlay controls."""

import math

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    AnalysisStatus,
    LoadDisplacementPoint,
    ModeShape,
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
from openframe.features.results.presentation.load_displacement_curve_view import (
    LoadDisplacementCurveView,
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
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport
from openframe.features.viewport.presentation.structural_graphics_view import (
    StructuralGraphicsView,
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
    "pushover": "PUSHOVER CURVE",
    "tables": "RESULT TABLES",
    "mode_shapes": "MODE SHAPES",
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
        self.view_selector = QComboBox()
        self.view_selector.addItem("ISO", "iso")
        self.view_selector.addItem("XY", "xy")
        self.view_selector.addItem("XZ", "xz")
        self.view_selector.addItem("YZ", "yz")
        self.view_selector.addItem("FREE", "free")
        self.view_selector.setMaximumWidth(72)
        self.view_selector.setToolTip(
            "Middle-drag: orbit · Shift+middle-drag: pan · Wheel: zoom"
        )
        self.view_selector.currentIndexChanged.connect(self._projection_changed)
        self.view_selector.hide()
        header_layout.addWidget(self.view_selector)
        self.mode_shape_label = QLabel("MODE")
        header_layout.addWidget(self.mode_shape_label)
        self.mode_shape_selector = QComboBox()
        self.mode_shape_selector.setObjectName("resultModeShapeSelector")
        self.mode_shape_selector.setMaximumWidth(160)
        self.mode_shape_selector.currentIndexChanged.connect(self._redraw)
        header_layout.addWidget(self.mode_shape_selector)
        self.mode_shape_label.hide()
        self.mode_shape_selector.hide()
        zoom_out = self._tool_button("−")
        zoom_in = self._tool_button("+")
        fit = self._tool_button("FIT")
        header_layout.addWidget(zoom_out)
        header_layout.addWidget(zoom_in)
        header_layout.addWidget(fit)
        layout.addWidget(canvas_header)

        self.scene = StructuralScene(self)
        self.view = StructuralGraphicsView(self.scene)
        self.view.setObjectName("resultGraphicsView")
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.quick3d_view = Quick3DViewport(self)
        self.curve_view = LoadDisplacementCurveView(self)
        self.canvas_stack = QStackedWidget()
        self.canvas_stack.addWidget(self.view)
        self.canvas_stack.addWidget(self.quick3d_view)
        self.canvas_stack.addWidget(self.curve_view)
        layout.addWidget(self.canvas_stack, 1)

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

        # A deformation-scale slider and "undeformed shape" toggle mean nothing for an
        # XY curve, so the pushover result type swaps this bar for one summarising the
        # run instead (steps completed, peak base shear/displacement, convergence).
        pushover_stats = QFrame()
        pushover_stats.setObjectName("resultViewportControls")
        pushover_stats_layout = QHBoxLayout(pushover_stats)
        pushover_stats_layout.setContentsMargins(10, 5, 10, 5)
        self.pushover_steps_label = self._stat_label()
        self.pushover_max_shear_label = self._stat_label()
        self.pushover_max_disp_label = self._stat_label()
        self.pushover_status_label = self._stat_label()
        for label in (
            self.pushover_steps_label,
            self.pushover_max_shear_label,
            self.pushover_max_disp_label,
        ):
            pushover_stats_layout.addWidget(label)
            pushover_stats_layout.addSpacing(18)
        pushover_stats_layout.addStretch(1)
        pushover_stats_layout.addWidget(self.pushover_status_label)

        self.controls_stack = QStackedWidget()
        self.controls_stack.addWidget(controls)
        self.controls_stack.addWidget(pushover_stats)
        layout.addWidget(self.controls_stack)

        zoom_in.clicked.connect(lambda: self._zoom(1.2))
        zoom_out.clicked.connect(lambda: self._zoom(1 / 1.2))
        fit.clicked.connect(self.fit_model)
        self.view.orbit_dragged.connect(self._orbit_view)
        self.quick3d_view.node_picked.connect(self._show_node_displacement)

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        projection = "iso" if model.ndm == 3 else "xy"
        self.view_selector.blockSignals(True)
        self.view_selector.setCurrentIndex(self.view_selector.findData(projection))
        self.view_selector.setVisible(model.ndm == 3)
        self.view.set_orbit_enabled(model.ndm == 3)
        self.view_selector.blockSignals(False)
        self.scene.set_projection(projection)
        if model.ndm == 3:
            self.quick3d_view.set_model(model)
            self.canvas_stack.setCurrentWidget(self.quick3d_view)
        else:
            self.canvas_stack.setCurrentWidget(self.view)
        self._update_picking_mode()
        self._redraw()
        self.fit_model()

    def show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._fill_mode_shape_selector(result.mode_shapes)
        self._redraw()
        self.fit_model()

    def clear_result(self) -> None:
        """Drop the drawn result so a new model never shows the previous one."""
        self._result = None
        self._fill_mode_shape_selector(())
        self._redraw()
        self.fit_model()

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self.scene.set_unit_system(unit_system)
        self._redraw()

    def set_result_type(self, result_type: str) -> None:
        self._result_type = result_type
        self.mode_badge.setText(RESULT_TYPE_NAMES.get(result_type, result_type.upper()))
        is_mode_shapes = result_type == "mode_shapes"
        self.mode_shape_label.setVisible(is_mode_shapes)
        self.mode_shape_selector.setVisible(is_mode_shapes)
        self._update_picking_mode()
        self._redraw()
        self.fit_model()

    def _fill_mode_shape_selector(self, mode_shapes: tuple[ModeShape, ...]) -> None:
        self.mode_shape_selector.blockSignals(True)
        self.mode_shape_selector.clear()
        for index, mode in enumerate(mode_shapes):
            self.mode_shape_selector.addItem(
                f"Mode {mode.mode_number}  (T={mode.period:.4g}s)", index
            )
        self.mode_shape_selector.blockSignals(False)

    def _current_mode_shape(self) -> ModeShape | None:
        if self._result is None:
            return None
        index = self.mode_shape_selector.currentData()
        if index is None or not (0 <= index < len(self._result.mode_shapes)):
            return None
        return self._result.mode_shapes[index]

    def _update_picking_mode(self) -> None:
        enabled = (
            self._result_type == "displacement"
            and self._model is not None
            and self._model.ndm == 3
        )
        self.quick3d_view.set_picking_mode(enabled)
        if not enabled:
            self.quick3d_view.set_selected_node(None)

    def _node_displacement_text(self, tag: int) -> str | None:
        if self._model is None or self._result is None:
            return None
        node_result = self._result.node_results.get(tag)
        if node_result is None:
            return None
        displacement = (*node_result.displacement, 0.0, 0.0, 0.0)
        ux, uy, uz = displacement[0], displacement[1], displacement[2]
        magnitude = math.sqrt(ux * ux + uy * uy + uz * uz)
        unit = self._unit_system.length
        return (
            f"Node {tag} | UX={ux:.6g} {unit} | UY={uy:.6g} {unit} | "
            f"UZ={uz:.6g} {unit} | |U|={magnitude:.6g} {unit}"
        )

    def _show_node_displacement(self, tag: int, global_x: int, global_y: int) -> None:
        text = self._node_displacement_text(tag)
        if text is None:
            return
        self.quick3d_view.set_selected_node(tag)
        QToolTip.showText(QPoint(global_x, global_y), text, self.quick3d_view)

    def fit_model(self) -> None:
        if self.canvas_stack.currentWidget() is self.curve_view:
            return
        if self.canvas_stack.currentWidget() is self.quick3d_view:
            preset = self.view_selector.currentData()
            if preset not in {"iso", "xy", "xz", "yz"}:
                preset = "iso"
                self.view_selector.blockSignals(True)
                self.view_selector.setCurrentIndex(self.view_selector.findData(preset))
                self.view_selector.blockSignals(False)
            self.quick3d_view.set_camera_preset(str(preset))
            return
        if not self.scene.items():
            return
        self.view.fit_content()

    def _zoom(self, factor: float) -> None:
        if self.canvas_stack.currentWidget() is self.curve_view:
            return
        if self.canvas_stack.currentWidget() is self.quick3d_view:
            self.quick3d_view.zoom(1.0 / factor)
        else:
            self.view.scale(factor, factor)

    def _projection_changed(self, index: int) -> None:
        del index
        projection = self.view_selector.currentData()
        if projection is not None and projection != "free":
            if self.canvas_stack.currentWidget() is self.quick3d_view:
                self.quick3d_view.set_camera_preset(str(projection))
            self.scene.set_projection(str(projection))
            self._redraw()
            self.fit_model()

    def _orbit_view(self, delta_x: float, delta_y: float) -> None:
        if self._model is None or self._model.ndm != 3:
            return
        self.scene.orbit(delta_x, delta_y, redraw=False)
        self.view_selector.blockSignals(True)
        self.view_selector.setCurrentIndex(self.view_selector.findData("free"))
        self.view_selector.blockSignals(False)
        self._redraw()

    def _redraw(self) -> None:
        if self._result_type == "pushover":
            self._redraw_pushover()
            return
        if self._result_type == "mode_shapes":
            self._redraw_mode_shape()
            return

        self.controls_stack.setCurrentIndex(0)
        if self._model is not None:
            self.canvas_stack.setCurrentWidget(
                self.quick3d_view if self._model.ndm == 3 else self.view
            )
            self.view_selector.setVisible(self._model.ndm == 3)

        force_diagram = self._result_type in {"axial", "shear", "moment"}
        self.scale_caption.setText("DIAGRAM SCALE" if force_diagram else "DEFORMATION SCALE")
        self.scale_value.setText(
            f"{self.deformation_scale.value()}%"
            if force_diagram
            else f"x{self.deformation_scale.value()}"
        )
        if self._model is None:
            self.scene.clear()
            self.view.set_content_scene_rect(QRectF(-8.0, -5.0, 16.0, 9.0))
            return

        if self._model.ndm == 3:
            self._redraw_3d()
            return

        self.scene.set_model(self._model)
        magnitudes = self._member_magnitudes()
        _, peak = magnitude_range(magnitudes)
        is_truss = self._is_truss_model()
        for item in self.scene.items():
            identity = item.data(0)
            if not isinstance(identity, tuple) or not identity:
                continue
            if identity[0] in {"node_label", "element_label"}:
                # A truss result has no diagram to read the member number off
                # of, and reactions/forces are only meaningful joint-by-joint
                # and member-by-member — so both stay on there, the same way
                # a frame result keeps them off to avoid cluttering the
                # diagrams it does have.
                item.setVisible(is_truss)
            elif identity[0] in {"load", "element_load"}:
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
        points = [
            self.scene.project_coordinates(node.x, node.y, node.z)
            for node in self._model.nodes.values()
        ]
        x_values = [point.x() for point in points]
        y_values = [point.y() for point in points]
        if x_values and y_values:
            span = max(max(x_values) - min(x_values), max(y_values) - min(y_values), 1.0)
            margin = max(span * 0.2, diagram_offset * 1.35)
            self.view.set_content_scene_rect(
                QRectF(
                    min(x_values) - margin,
                    min(y_values) - margin,
                    max(x_values) - min(x_values) + 2 * margin,
                    max(y_values) - min(y_values) + 2 * margin,
                )
            )

    def _redraw_3d(self) -> None:
        if self._model is None:
            return
        if self._result is not None:
            self.quick3d_view.show_result(
                self._model,
                self._result,
                float(self.deformation_scale.value()),
                self.show_undeformed.isChecked(),
            )
        else:
            self.quick3d_view.clear_result()

    def _redraw_pushover(self) -> None:
        self.canvas_stack.setCurrentWidget(self.curve_view)
        self.controls_stack.setCurrentIndex(1)
        self.view_selector.setVisible(False)
        curve = self._result.load_displacement_curve if self._result is not None else ()
        # The curve is only ever non-empty for a nonlinear run, so any message on that
        # result is almost certainly the "stopped converging at step N" note - good
        # enough to flag the plot as a partial pushover without re-deriving it here.
        incomplete = bool(self._result and self._result.messages)
        self.curve_view.set_curve(curve, unit_system=self._unit_system, incomplete=incomplete)
        self._update_pushover_stats(curve, incomplete)

    def _update_pushover_stats(
        self, curve: tuple[LoadDisplacementPoint, ...], incomplete: bool
    ) -> None:
        if not curve:
            self.pushover_steps_label.setText("STEPS —")
            self.pushover_max_shear_label.setText("MAX BASE SHEAR —")
            self.pushover_max_disp_label.setText("MAX DISPLACEMENT —")
            self.pushover_status_label.setText("")
            return
        force_unit = self._unit_system.force
        length_unit = self._unit_system.length
        max_shear = max(abs(point.base_shear) for point in curve)
        max_disp = max(abs(point.control_displacement) for point in curve)
        self.pushover_steps_label.setText(f"STEPS {curve[-1].step}")
        self.pushover_max_shear_label.setText(f"MAX BASE SHEAR {max_shear:.4g} {force_unit}")
        self.pushover_max_disp_label.setText(f"MAX DISPLACEMENT {max_disp:.4g} {length_unit}")
        self.pushover_status_label.setText("STOPPED (수렴 실패)" if incomplete else "CONVERGED")
        self.pushover_status_label.setProperty("status", "warning" if incomplete else "ok")
        self.pushover_status_label.style().unpolish(self.pushover_status_label)
        self.pushover_status_label.style().polish(self.pushover_status_label)

    def _redraw_mode_shape(self) -> None:
        """A mode shape has displacements but no forces/reactions - it is drawn
        with exactly the ordinary "nodal displacements" pipeline (2D coloured
        members + deflection curve, or the 3D quick view), just fed the picked
        mode's own eigenvector instead of a real analysis result. Swapping
        ``self._result``/``self._result_type`` for the duration of one
        synchronous ``_redraw()`` call is simpler and less risky than threading
        a second result source through every drawing helper in this class."""
        mode = self._current_mode_shape()
        if self._model is None or mode is None:
            self.controls_stack.setCurrentIndex(0)
            self.scale_caption.setText("MODE SHAPE SCALE")
            self.scale_value.setText(f"x{self.deformation_scale.value()}")
            if self._model is None:
                self.scene.clear()
                self.view.set_content_scene_rect(QRectF(-8.0, -5.0, 16.0, 9.0))
                return
            self.canvas_stack.setCurrentWidget(
                self.quick3d_view if self._model.ndm == 3 else self.view
            )
            self.view_selector.setVisible(self._model.ndm == 3)
            if self._model.ndm == 3:
                self.quick3d_view.clear_result()
            else:
                self.scene.set_model(self._model)
            return

        synthetic_result = AnalysisResult(
            status=AnalysisStatus.COMPLETED, node_results=mode.node_results
        )
        saved_result, saved_type = self._result, self._result_type
        self._result, self._result_type = synthetic_result, "displacement"
        try:
            self._redraw()
        finally:
            self._result, self._result_type = saved_result, saved_type
        self.scale_caption.setText("MODE SHAPE SCALE")

    def _is_truss_model(self) -> bool:
        """Whole-model, matching how ``check_determinacy``/the solver already
        decide truss vs frame — this app has no mixed truss/frame model."""
        if self._model is None or not self._model.elements:
            return False
        return all(
            "truss" in element.element_type.lower()
            for element in self._model.elements.values()
        )

    def _member_magnitudes(self) -> dict[int, float]:
        if self._model is None or self._result is None:
            return {}
        if self._model.ndm == 3 and self._result_type in {"axial", "shear", "moment"}:
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
        if self._model.ndm == 3:
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
        if self._model.ndm == 3:
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
        if self._model.ndm == 3:
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

    @staticmethod
    def _stat_label() -> QLabel:
        label = QLabel("")
        label.setObjectName("resultPushoverStat")
        return label
