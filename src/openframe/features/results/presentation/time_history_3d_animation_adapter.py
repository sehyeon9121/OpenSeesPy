"""Adapter between Time History animation and the 3D viewport bridge.

Incremental deformation updates go through
``Quick3DViewport.update_deformed_node_positions`` so step playback never
rebuilds the whole scene via ``set_result()``. Torsion markers use the
parallel incremental API on ``Quick3DSceneBridge``.
"""

from __future__ import annotations

import math

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.results.deformation.deformed_3d_state import build_deformed_3d_state
from openframe.features.results.deformation.member_torsion_state import (
    build_member_torsion_state,
)
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport

DEFAULT_MARKER_COUNT = 5
_TRUSS_TYPES = frozenset({"truss", "corottruss"})
_MAX_TORSION_STATIONS = 500
_MAX_ROTATION_SCALE = 100.0


def sanitize_rotation_scale(scale: float) -> float:
    """Clamp programmatic rotation multipliers to a finite, display-safe range."""
    value = float(scale)
    if not math.isfinite(value):
        return 1.0
    return max(-_MAX_ROTATION_SCALE, min(_MAX_ROTATION_SCALE, value))


def compute_effective_marker_count(
    model: StructuralModel | None,
    requested: int,
) -> int:
    """Return the station count actually used after the 500-station global cap."""
    count = max(1, requested)
    if model is None:
        return count
    beam_count = sum(
        1
        for element in model.elements.values()
        if element.element_type.lower() not in _TRUSS_TYPES
    )
    if beam_count <= 0:
        return count
    station_cap = max(1, _MAX_TORSION_STATIONS // beam_count)
    return max(1, min(count, station_cap))


class TimeHistory3DAnimationAdapter:
    """Drive one time-history step through the bridge's incremental deformation API."""

    def __init__(self, viewport: Quick3DViewport | None = None) -> None:
        self._viewport = viewport or Quick3DViewport()
        self._model: StructuralModel | None = None
        self._result: AnalysisResult | None = None
        self._step_index = 0
        self._translation_scale = 1.0
        self._rotation_scale = 1.0
        self._marker_count = DEFAULT_MARKER_COUNT
        self._show_original = True
        self._show_deformed = True
        self._show_torsion_markers = False
        self._deformation_active = False
        self._torsion_active = False

    @property
    def viewport(self) -> Quick3DViewport:
        return self._viewport

    def set_model(self, model: StructuralModel) -> None:
        self._viewport.end_time_history_deformation()
        self._model = model
        self._deformation_active = False
        self._torsion_active = False
        self._viewport.set_model(model, reset_camera=True)

    def set_result(self, result: AnalysisResult) -> None:
        if self._deformation_active or self._torsion_active:
            self._viewport.end_time_history_deformation()
        self._result = result
        self._step_index = 0
        self._deformation_active = False
        self._torsion_active = False

    def set_step(self, index: int) -> None:
        if self._result is None or not self._result.time_history:
            return
        self._step_index = max(0, min(index, len(self._result.time_history) - 1))
        self._refresh()

    def set_translation_scale(self, scale: float) -> None:
        self._translation_scale = scale

    def set_rotation_scale(self, scale: float) -> None:
        self._rotation_scale = sanitize_rotation_scale(scale)

    def set_marker_count(self, count: int) -> None:
        count = max(1, count)
        if count == self._marker_count:
            return
        self._marker_count = count
        self._torsion_active = False

    def set_show_original(self, enabled: bool) -> None:
        self._show_original = enabled
        if self._deformation_active:
            self._refresh()

    def set_show_deformed(self, enabled: bool) -> None:
        self._show_deformed = enabled
        if self._deformation_active:
            self._refresh()

    def set_show_torsion_markers(self, enabled: bool) -> None:
        self._show_torsion_markers = enabled
        if self._deformation_active:
            self._refresh()

    def clear(self) -> None:
        self._result = None
        self._step_index = 0
        self._deformation_active = False
        self._torsion_active = False
        self._viewport.end_time_history_deformation()

    def current_step_index(self) -> int:
        return self._step_index

    def requested_marker_count(self) -> int:
        return self._marker_count

    def effective_marker_count(self) -> int:
        return compute_effective_marker_count(self._model, self._marker_count)

    def is_marker_density_capped(self) -> bool:
        return self.effective_marker_count() < self._marker_count

    def effective_rotation_scale(self) -> float:
        return self._rotation_scale

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
            self._torsion_active = False

    def _ensure_torsion_mode(self) -> None:
        if self._model is None:
            return
        if not self._torsion_active:
            self._viewport.begin_torsion_marker_mode(
                self._model,
                self.effective_marker_count(),
            )
            self._torsion_active = True

    def _refresh(self) -> None:
        if self._model is None or self._result is None or not self._result.time_history:
            return
        if not self._show_deformed and not self._show_original:
            if self._deformation_active:
                self._viewport.end_time_history_deformation()
                self._deformation_active = False
                self._torsion_active = False
            return
        if not self._show_deformed:
            self._ensure_deformation_mode()
            self._viewport.update_deformed_node_positions(
                {},
                show_original=self._show_original,
                show_deformed=False,
            )
            self._viewport.update_torsion_markers((), visible=False)
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
        for node in state.nodes:
            if node.valid:
                deformed_points[node.node_tag] = Quick3DSceneBridge._view_coordinates(
                    node.deformed_x,
                    node.deformed_y,
                    node.deformed_z,
                )
            else:
                base = self._viewport.bridge._points.get(node.node_tag)
                if base is not None:
                    deformed_points[node.node_tag] = base

        # Playback is the deformed shape, not a contour. Mapping displacement
        # onto the blue-yellow-red ramp every step recoloured every member
        # (and forced InstanceList to rebuild the GPU table on top of the
        # transform upload). Static result views still use that ramp through
        # set_result(); animation keeps the modeling member-type colours.
        self._ensure_deformation_mode()
        self._viewport.update_deformed_node_positions(
            deformed_points,
            show_original=self._show_original,
            show_deformed=self._show_deformed,
        )

        torsion_state = build_member_torsion_state(
            self._model,
            self._result,
            state,
            self._step_index,
            self._rotation_scale,
            marker_count=self.effective_marker_count(),
        )
        show_markers = (
            self._show_torsion_markers
            and torsion_state is not None
            and torsion_state.has_torsion
        )
        if show_markers:
            self._ensure_torsion_mode()
            self._viewport.update_torsion_markers(torsion_state.markers, visible=True)
        elif self._torsion_active:
            self._viewport.update_torsion_markers((), visible=False)
