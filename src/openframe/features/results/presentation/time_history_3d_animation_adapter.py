"""Adapter between Time History animation and the 3D viewport bridge.

All calls to ``Quick3DSceneBridge.set_result()`` for time-history playback
live here so Lane B can swap in an incremental update API later without
touching the animation panel's transport controls.
"""

from __future__ import annotations

from openframe.core.domain import AnalysisResult, AnalysisStatus, StructuralModel
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport


class TimeHistory3DAnimationAdapter:
    """Drive one time-history step through the existing static 3D result overlay."""

    def __init__(self, viewport: Quick3DViewport | None = None) -> None:
        self._viewport = viewport or Quick3DViewport()
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._step_index = 0
        self._translation_scale = 1.0
        self._show_original = True
        self._show_deformed = True

    @property
    def viewport(self) -> Quick3DViewport:
        return self._viewport

    def set_model(self, model: StructuralModel) -> None:
        self._model = model
        self._viewport.set_model(model, reset_camera=True)

    def set_result(self, result: AnalysisResult) -> None:
        self._result = result
        self._step_index = 0

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
        self._viewport.clear_result()

    def current_step_index(self) -> int:
        return self._step_index

    @staticmethod
    def synthetic_result_for_step(result: AnalysisResult, step_index: int) -> AnalysisResult:
        """Build a single-step ``AnalysisResult`` the static bridge already understands."""
        step = result.time_history[step_index]
        return AnalysisResult(
            status=result.status or AnalysisStatus.COMPLETED,
            node_results=step.node_results,
        )

    def _refresh(self) -> None:
        if self._model is None or self._result is None or not self._result.time_history:
            return
        if not self._show_deformed:
            self._viewport.clear_result()
            return
        synthetic = self.synthetic_result_for_step(self._result, self._step_index)
        self._viewport.show_result(
            self._model,
            synthetic,
            self._translation_scale,
            show_undeformed=self._show_original,
        )
