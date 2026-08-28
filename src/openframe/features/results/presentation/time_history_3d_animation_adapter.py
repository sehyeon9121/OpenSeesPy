"""Adapter between Time History animation and the 3D viewport bridge.

Incremental deformation updates go through
``Quick3DViewport.update_deformed_node_positions`` so step playback never
rebuilds the whole scene via ``set_result()``.
"""

from __future__ import annotations

import math

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.results.deformation.deformed_3d_state import build_deformed_3d_state
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport


class TimeHistory3DAnimationAdapter:
    """Drive one time-history step through the bridge's incremental deformation API."""

    def __init__(self, viewport: Quick3DViewport | None = None) -> None:
        self._viewport = viewport or Quick3DViewport()
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._step_index = 0
        self._translation_scale = 1.0
        self._show_original = True
        self._show_deformed = True
        self._deformation_active = False

    @property
    def viewport(self) -> Quick3DViewport:
        return self._viewport

    def set_model(self, model: StructuralModel) -> None:
        self._viewport.end_time_history_deformation()
        self._model = model
        self._deformation_active = False
        self._viewport.set_model(model, reset_camera=True)

    def set_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._step_index = 0
        self._deformation_active = False

    def set_step(self, index: int) -> None:
        if self._result is None or not self._result.time_history:
            return
        self._step_index = max(0, min(index, len(self._result.time_history) - 1))
        self._refresh()

    def set_translation_scale(self, scale: float) -> None:
        self._translation_scale = scale
        self._refresh()

    def set_show_original(self, enabled: bool) -> None:
        self._show_original = enabled
        self._refresh()

    def set_show_deformed(self, enabled: bool) -> None:
        self._show_deformed = enabled
        self._refresh()

    def clear(self) -> None:
        self._result = None
        self._step_index = 0
        self._deformation_active = False
        self._viewport.end_time_history_deformation()

    def current_step_index(self) -> int:
        return self._step_index

    def _ensure_deformation_mode(self) -> None:
        if self._model is None:
            return
        if not self._deformation_active:
            self._viewport.begin_time_history_deformation(
                self._model,
                show_original=self._show_original,
                show_deformed=self._show_deformed,
            )
            self._deformation_active = True

    def _refresh(self) -> None:
        if self._model is None or self._result is None or not self._result.time_history:
            return
        if not self._show_deformed and not self._show_original:
            if self._deformation_active:
                self._viewport.end_time_history_deformation()
                self._deformation_active = False
            return
        if not self._show_deformed:
            self._ensure_deformation_mode()
            self._viewport.update_deformed_node_positions(
                {},
                show_original=self._show_original,
                show_deformed=False,
            )
            return

        state = build_deformed_3d_state(
            self._model,
            self._result,
            self._step_index,
            self._translation_scale,
        )
        if state is None:
            return

        deformed_points: dict[int, tuple[float, float, float]] = {}
        magnitudes: dict[int, float] = {}
        for node in state.nodes:
            if node.valid:
                deformed_points[node.node_tag] = Quick3DSceneBridge._view_coordinates(
                    node.deformed_x,
                    node.deformed_y,
                    node.deformed_z,
                )
                step_node = self._result.time_history[state.step_index].node_results.get(
                    node.node_tag
                )
                if step_node is not None:
                    displacement = step_node.displacement
                    padded = (*displacement, 0.0, 0.0, 0.0)
                    ux, uy, uz = padded[0], padded[1], padded[2]
                    magnitudes[node.node_tag] = math.sqrt(ux * ux + uy * uy + uz * uz)
            else:
                base = self._viewport.bridge._points.get(node.node_tag)
                if base is not None:
                    deformed_points[node.node_tag] = base

        peak = max(magnitudes.values(), default=0.0)
        node_ratios = (
            {
                tag: 0.0 if peak <= 1.0e-12 else magnitude / peak
                for tag, magnitude in magnitudes.items()
            }
            if magnitudes
            else None
        )

        self._ensure_deformation_mode()
        self._viewport.update_deformed_node_positions(
            deformed_points,
            show_original=self._show_original,
            show_deformed=self._show_deformed,
            node_ratios=node_ratios,
        )
