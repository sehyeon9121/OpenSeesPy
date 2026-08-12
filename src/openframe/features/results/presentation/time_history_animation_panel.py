"""Time-history displacement animation, replayed from AnalysisResult.time_history.

No new result storage: every frame reads straight from the same
``time_history`` tuple Phase 3-H already produces (``time`` + per-node
``NodeResult.displacement``). This panel only ever *computes a temporary
screen position* from ``original coordinate + displacement * deformation
scale`` - it never writes back into ``StructuralModel`` or ``AnalysisResult``.

Reuses the existing 2D structural renderer (``StructuralScene``/
``StructuralGraphicsView`` - the same pan/zoom/fit and coordinate projection
Linear Static's Deformed Shape already relies on) for the undeformed layer
and the coordinate transform. The deformed overlay is a small set of
QGraphicsLineItem/QGraphicsEllipseItem created once per model and repositioned
in place every frame (no scene.clear()/item rebuild), which is what keeps a
4096-step Kobe result smooth - a frame update only touches O(nodes+elements),
never the whole time_history array.
"""

from __future__ import annotations

import bisect
import logging
import math

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
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
from openframe.features.viewport.presentation.structural_graphics_view import (
    StructuralGraphicsView,
)
from openframe.features.viewport.scene import StructuralScene

_logger = logging.getLogger(__name__)

#: ~30fps - fast enough to look smooth, far below what would make 4096 steps
#: of dict lookups+repaints a burden (see module docstring).
_TICK_INTERVAL_MS = 33

_SPEED_OPTIONS: tuple[tuple[str, float], ...] = (
    ("0.25×", 0.25),
    ("0.5×", 0.5),
    ("1×", 1.0),
    ("2×", 2.0),
    ("4×", 4.0),
)

#: "Auto" (None) computes a multiplier from the result's own peak displacement;
#: the rest are fixed multipliers, same vocabulary as ResultViewport's own
#: deformation control so this doesn't invent a second convention.
_SCALE_OPTIONS: tuple[tuple[str, float | None], ...] = (
    ("Auto", None),
    ("1×", 1.0),
    ("5×", 5.0),
    ("10×", 10.0),
    ("20×", 20.0),
    ("50×", 50.0),
    ("100×", 100.0),
)

_AUTO_SCALE_TARGET_FRACTION = 0.08


def _xy(node_result: NodeResult | None) -> tuple[float, float]:
    if node_result is None:
        return 0.0, 0.0
    displacement = node_result.displacement
    ux = displacement[0] if len(displacement) > 0 else 0.0
    uy = displacement[1] if len(displacement) > 1 else 0.0
    return ux, uy


class TimeHistoryAnimationPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timeHistoryAnimationPanel")
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._times: tuple[float, ...] = ()
        self._current_step_index = 0
        self._playing = False
        self._playback_speed = 1.0
        #: Virtual position along the result's own time axis - advances by
        #: (tick interval * playback_speed) each tick, independent of the
        #: analysis's real dt so a 0.01s-dt Kobe run does not need a 10ms timer.
        self._playback_time = 0.0
        self._auto_scale_multiplier: float | None = None
        self._element_items: dict[int, QGraphicsLineItem] = {}
        self._node_items: dict[int, QGraphicsEllipseItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(14, 10, 14, 4)
        title = QLabel("TIME HISTORY ANIMATION")
        title.setObjectName("resultSectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.consistency_warning = QLabel("")
        self.consistency_warning.setObjectName("secondaryText")
        self.consistency_warning.setVisible(False)
        header.addWidget(self.consistency_warning)
        layout.addLayout(header)

        self.scene = StructuralScene(self)
        self.view = StructuralGraphicsView(self.scene)
        self.view.setObjectName("resultGraphicsView")
        self.view.setDragMode(self.view.DragMode.ScrollHandDrag)
        layout.addWidget(self.view, 1)

        self.empty_label = QLabel("Run a Time History Analysis to view the animation.")
        self.empty_label.setObjectName("secondaryText")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        controls = QFrame()
        controls.setObjectName("resultViewportControls")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(10, 6, 10, 8)
        controls_layout.setSpacing(6)

        transport_row = QHBoxLayout()
        self.first_button = self._tool_button("|◀")
        self.play_pause_button = self._tool_button("▶")
        self.last_button = self._tool_button("▶|")
        transport_row.addWidget(self.first_button)
        transport_row.addWidget(self.play_pause_button)
        transport_row.addWidget(self.last_button)
        transport_row.addSpacing(10)
        self.time_step_label = QLabel("—")
        self.time_step_label.setObjectName("resultScaleValue")
        transport_row.addWidget(self.time_step_label)
        transport_row.addStretch(1)
        self.max_displacement_label = QLabel("")
        self.max_displacement_label.setObjectName("secondaryText")
        transport_row.addWidget(self.max_displacement_label)
        controls_layout.addLayout(transport_row)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        controls_layout.addWidget(self.slider)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Speed"))
        self.speed_selector = QComboBox()
        for label, value in _SPEED_OPTIONS:
            self.speed_selector.addItem(label, value)
        self.speed_selector.setCurrentIndex(2)  # 1x
        options_row.addWidget(self.speed_selector)
        options_row.addSpacing(14)
        options_row.addWidget(QLabel("Deformation Scale"))
        self.scale_selector = QComboBox()
        for label, value in _SCALE_OPTIONS:
            self.scale_selector.addItem(label, value)
        options_row.addWidget(self.scale_selector)
        options_row.addSpacing(14)
        self.show_undeformed_checkbox = QCheckBox("Show Undeformed Shape")
        self.show_undeformed_checkbox.setChecked(True)
        options_row.addWidget(self.show_undeformed_checkbox)
        options_row.addStretch(1)
        controls_layout.addLayout(options_row)

        layout.addWidget(controls)

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

        self.first_button.clicked.connect(self._go_to_first)
        self.play_pause_button.clicked.connect(self._toggle_play)
        self.last_button.clicked.connect(self._go_to_last)
        self.slider.sliderPressed.connect(lambda: self._set_playing(False))
        self.slider.valueChanged.connect(self._on_slider_changed_by_user)
        self.speed_selector.currentIndexChanged.connect(self._on_speed_changed)
        self.scale_selector.currentIndexChanged.connect(self._on_scale_changed)
        self.show_undeformed_checkbox.toggled.connect(self._on_show_undeformed_toggled)

        self._show_empty_state()

    # -- lifecycle -----------------------------------------------------

    def pause_animation(self) -> None:
        self._set_playing(False)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self._update_step_labels()

    def set_model(self, model: StructuralModel) -> None:
        self._set_playing(False)
        self._model = model
        self._element_items = {}
        self._node_items = {}
        if model.ndm != 3:
            self.scene.set_model(model)
            self._build_deformed_overlay(model)
            self._fit_view()
        self._apply_undeformed_visibility()

    def show_result(self, result: AnalysisResult) -> None:
        self._set_playing(False)
        self._result = result
        self._times = tuple(step.time for step in result.time_history)
        self._current_step_index = 0
        self._playback_time = self._times[0] if self._times else 0.0
        self._auto_scale_multiplier = None
        self._check_node_consistency()
        if self._has_playable_result():
            self.empty_label.setVisible(False)
            self.view.setVisible(True)
            self.slider.setEnabled(True)
            self.slider.setMaximum(max(len(self._times) - 1, 0))
            self._apply_step(0)
            # The view may not have had a real size yet when set_model() first
            # fit it (e.g. this tab was never shown) - re-fit now that a
            # result exists and the widget is about to become visible.
            self._fit_view()
        else:
            self._show_empty_state()

    def clear_result(self) -> None:
        self._set_playing(False)
        self._result = None
        self._times = ()
        self._current_step_index = 0
        self._playback_time = 0.0
        self._show_empty_state()

    # -- geometry --------------------------------------------------------

    def _fit_view(self) -> None:
        """Frame the model once (on load), with enough margin that a
        moderate deformation multiplier still stays on screen - matching
        ResultViewport's own "fit on load, not on every redraw" convention
        rather than moving the camera every animation frame."""
        if self._model is None or not self._model.nodes:
            return
        points = [
            self.scene.project_coordinates(node.x, node.y, node.z)
            for node in self._model.nodes.values()
        ]
        x_values = [point.x() for point in points]
        y_values = [point.y() for point in points]
        span = max(max(x_values) - min(x_values), max(y_values) - min(y_values), 1.0)
        margin = span * 0.4
        self.view.set_content_scene_rect(
            QRectF(
                min(x_values) - margin,
                min(y_values) - margin,
                max(x_values) - min(x_values) + 2 * margin,
                max(y_values) - min(y_values) + 2 * margin,
            )
        )
        self.view.fit_content()

    def _build_deformed_overlay(self, model: StructuralModel) -> None:
        pen = QPen(QColor("#e5484d"), 2.4)
        pen.setCosmetic(True)
        for element in model.elements.values():
            item = QGraphicsLineItem(0.0, 0.0, 0.0, 0.0)
            item.setPen(pen)
            item.setZValue(9.0)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            self.scene.addItem(item)
            self._element_items[element.tag] = item

        node_pen = QPen(QColor("#e5484d"), 1.6)
        node_pen.setCosmetic(True)
        for node_tag in model.nodes:
            item = QGraphicsEllipseItem(-4.0, -4.0, 8.0, 8.0)
            item.setPen(node_pen)
            item.setBrush(QColor("#e5484d"))
            item.setZValue(9.5)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            self.scene.addItem(item)
            self._node_items[node_tag] = item

    def _check_node_consistency(self) -> None:
        """Model/result node-ID mismatches must not fail silently (Phase
        3-I spec item 16) - logged always, and surfaced in the UI when it
        would otherwise look like the animation is simply missing nodes."""
        self.consistency_warning.setVisible(False)
        if self._model is None or not self._result or not self._result.time_history:
            return
        model_nodes = set(self._model.nodes)
        result_nodes = set(self._result.time_history[0].node_results)
        missing = model_nodes - result_nodes
        if missing:
            message = (
                f"{len(missing)}개 절점의 시간이력 결과가 없어 원위치로 표시됩니다: "
                f"{sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}"
            )
            _logger.warning("Time history animation: %s", message)
            self.consistency_warning.setText(message)
            self.consistency_warning.setVisible(True)

    def _has_playable_result(self) -> bool:
        return (
            self._model is not None
            and self._model.ndm != 3
            and self._result is not None
            and bool(self._result.time_history)
        )

    def _show_empty_state(self) -> None:
        self.view.setVisible(False)
        self.empty_label.setVisible(True)
        if self._model is not None and self._model.ndm == 3:
            self.empty_label.setText("3D 모델의 Time History 애니메이션은 이번 버전에서 지원하지 않습니다.")
        else:
            self.empty_label.setText("Run a Time History Analysis to view the animation.")
        self.slider.setEnabled(False)
        self.slider.setMaximum(0)
        self.time_step_label.setText("—")
        self.max_displacement_label.setText("")

    def _active_deformation_multiplier(self) -> float:
        selected = self.scale_selector.currentData()
        if selected is not None:
            return float(selected)
        if self._auto_scale_multiplier is None:
            self._auto_scale_multiplier = self._compute_auto_scale()
        return self._auto_scale_multiplier

    def _compute_auto_scale(self) -> float:
        """Scans the whole time_history once (not per-frame) for the largest
        displacement magnitude, same rule of thumb as ResultViewport's own
        AUTO button: draw the peak at ~8% of the model's own span."""
        if self._model is None or not self._model.nodes or self._result is None:
            return 1.0
        max_displacement = 0.0
        for step in self._result.time_history:
            for node_result in step.node_results.values():
                ux, uy = _xy(node_result)
                max_displacement = max(max_displacement, math.hypot(ux, uy))
        if max_displacement <= 0.0:
            return 1.0
        xs = [node.x for node in self._model.nodes.values()]
        ys = [node.y for node in self._model.nodes.values()]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        return max(1.0, (span * _AUTO_SCALE_TARGET_FRACTION) / max_displacement)

    def _apply_step(self, index: int) -> None:
        if not self._has_playable_result():
            return
        step = self._result.time_history[index]
        scale = self._active_deformation_multiplier()
        max_magnitude = 0.0
        for node_tag, item in self._node_items.items():
            node = self._model.nodes.get(node_tag)
            if node is None:
                continue
            ux, uy = _xy(step.node_results.get(node_tag))
            point = self.scene.project_coordinates(node.x + ux * scale, node.y + uy * scale, node.z)
            item.setPos(point)
            max_magnitude = max(max_magnitude, math.hypot(ux, uy))
        for element_tag, item in self._element_items.items():
            element = self._model.elements.get(element_tag)
            if element is None:
                continue
            node_i = self._model.nodes.get(element.node_i)
            node_j = self._model.nodes.get(element.node_j)
            if node_i is None or node_j is None:
                continue
            ux_i, uy_i = _xy(step.node_results.get(element.node_i))
            ux_j, uy_j = _xy(step.node_results.get(element.node_j))
            start = self.scene.project_coordinates(
                node_i.x + ux_i * scale, node_i.y + uy_i * scale, node_i.z
            )
            end = self.scene.project_coordinates(
                node_j.x + ux_j * scale, node_j.y + uy_j * scale, node_j.z
            )
            item.setLine(start.x(), start.y(), end.x(), end.y())

        self._current_step_index = index
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)
        self._update_step_labels(max_magnitude)

    def _update_step_labels(self, max_magnitude: float | None = None) -> None:
        if not self._has_playable_result():
            return
        step = self._result.time_history[self._current_step_index]
        total_time = self._times[-1] if self._times else 0.0
        self.time_step_label.setText(
            f"{step.time:.3f} / {total_time:.3f} s   ·   Step "
            f"{self._current_step_index} / {len(self._times) - 1}"
        )
        if max_magnitude is not None:
            unit = self._unit_system.length
            self.max_displacement_label.setText(
                f"Deformation Scale: {self._active_deformation_multiplier():g}×   "
                f"Max |U| at current step: {max_magnitude:.4g} {unit}"
            )

    def _apply_undeformed_visibility(self) -> None:
        visible = self.show_undeformed_checkbox.isChecked()
        for item in self.scene.items():
            identity = item.data(0)
            if isinstance(identity, tuple) and identity and identity[0] in {"node", "element"}:
                item.setVisible(visible)

    # -- playback ----------------------------------------------------------

    def _set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        self.play_pause_button.setText("❚❚" if playing else "▶")
        if playing:
            self._timer.start()
        else:
            self._timer.stop()

    def _toggle_play(self) -> None:
        if self._playing:
            self._set_playing(False)
            return
        if not self._has_playable_result():
            return
        if self._current_step_index >= len(self._times) - 1:
            self._playback_time = self._times[0]
            self._apply_step(0)
        else:
            self._playback_time = self._times[self._current_step_index]
        self._set_playing(True)

    def _on_tick(self) -> None:
        if not self._playing or not self._has_playable_result():
            return
        self._playback_time += (_TICK_INTERVAL_MS / 1000.0) * self._playback_speed
        index = bisect.bisect_right(self._times, self._playback_time) - 1
        index = max(0, min(index, len(self._times) - 1))
        if index != self._current_step_index:
            self._apply_step(index)
        if index >= len(self._times) - 1:
            self._set_playing(False)

    def set_current_step(self, index: int) -> None:
        """Jump to a specific step from outside this panel - Phase 3-J's "Go
        to Peak"/graph-click entry point, routed through
        TimeHistoryResultsPanel rather than called directly by
        TimeHistoryPanel. Always pauses first and only moves the position -
        deformation scale and the undeformed-shape toggle are left exactly as
        the user set them."""
        self._set_playing(False)
        if not self._has_playable_result():
            return
        clamped = max(0, min(index, len(self._times) - 1))
        self._playback_time = self._times[clamped]
        self._apply_step(clamped)

    def _go_to_first(self) -> None:
        self._set_playing(False)
        if not self._has_playable_result():
            return
        self._playback_time = self._times[0]
        self._apply_step(0)

    def _go_to_last(self) -> None:
        self._set_playing(False)
        if not self._has_playable_result():
            return
        last = len(self._times) - 1
        self._playback_time = self._times[last]
        self._apply_step(last)

    def _on_slider_changed_by_user(self, value: int) -> None:
        # Only fires for a real user interaction - every programmatic update
        # (from _apply_step, driven by the timer) is wrapped in blockSignals.
        if not self._has_playable_result():
            return
        self._set_playing(False)
        index = max(0, min(value, len(self._times) - 1))
        self._playback_time = self._times[index]
        self._apply_step(index)

    def _on_speed_changed(self) -> None:
        speed = self.speed_selector.currentData()
        self._playback_speed = float(speed) if speed is not None else 1.0

    def _on_scale_changed(self) -> None:
        if self._has_playable_result():
            self._apply_step(self._current_step_index)

    def _on_show_undeformed_toggled(self) -> None:
        self._apply_undeformed_visibility()

    @staticmethod
    def _tool_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("resultCanvasButton")
        return button
