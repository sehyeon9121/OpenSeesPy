"""Embedded Qt Quick 3D viewport for structural models."""

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)


class Quick3DViewport(QFrame):
    camera_mode_changed = Signal(str)
    node_picked = Signal(int, int, int)
    member_picked = Signal(int, int, int)
    #: A click on the active work plane, as structural (x, y, z) — already
    #: converted out of the QML scene's y-up view coordinates, so callers never
    #: need to know about that mapping.
    plane_point_picked = Signal(float, float, float)
    #: Hover equivalents of the two signals above (no button held), fired
    #: continuously while set_plane_picking_mode(True) is in effect — drive
    #: free-form 3D draw mode's node-snap and rubber-band preview.
    node_hovered = Signal(int)
    plane_point_hovered = Signal(float, float, float)
    hover_cleared = Signal()
    selection_box_finished = Signal(object, object, bool)
    #: A plain click in select mode that hit neither a node nor a member -
    #: the 3D-view equivalent of clicking empty space on the 2D canvas.
    empty_space_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bridge = Quick3DSceneBridge(self)
        self.quick_widget = QQuickWidget(self)
        # Four of these viewports are built eagerly at app startup. On Windows,
        # constructing a QQuickWidget (and especially setSource()) maps a blank
        # native HWND that flashes as an empty title-bar window before
        # MainWindow appears. WA_DontShowOnScreen keeps the widget in the Qt
        # tree — so installEventFilter / QShortcut WidgetWithChildrenShortcut /
        # setFocus keep working from __init__ — without mapping that HWND.
        # Cleared on the first real visible showEvent, right before setSource.
        self.quick_widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.quick_widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.quick_widget.setClearColor(Qt.GlobalColor.transparent)
        # Needed for the modeling page's Space-bar draw-tool shortcut (scoped
        # to this viewport in 3D mode) to fire at all: a QShortcut with
        # WidgetWithChildrenShortcut context only dispatches while its widget
        # (or a child) actually holds keyboard focus, and QWidget's default
        # focus policy is NoFocus. StrongFocus makes a click in the viewport
        # (already the natural first step of drawing) grab focus for it.
        self.quick_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.quick_widget.rootContext().setContextProperty("sceneBridge", self.bridge)
        layout.addWidget(self.quick_widget)

        # setSource() is what stands up the scene graph/RHI context. Deferred
        # to the first visible showEvent so a viewport nobody has opened yet
        # never touches the GPU. _pending_* lets callers that configure the
        # view before the first show (set_model / set_active_plane / picking
        # while this page isn't the visible one) still take effect once loaded.
        self._loaded = False
        self._pending_camera_preset: str | None = None
        self._pending_plane: tuple[str, float] | None = None
        self._pending_picking: bool | None = None
        self._pending_plane_picking: bool | None = None
        self._qml_path = Path(__file__).with_name("qml") / "structural_view.qml"
        self._pending_model: StructuralModel | None = None
        self._pending_reset_camera = True
        self._model_coalesce_timer = QTimer(self)
        self._model_coalesce_timer.setSingleShot(True)
        self._model_coalesce_timer.timeout.connect(self._flush_coalesced_model)
        self._pending_display_visibility: dict[str, bool] = {}
        self._display_visibility_timer = QTimer(self)
        self._display_visibility_timer.setSingleShot(True)
        self._display_visibility_timer.timeout.connect(self._flush_display_visibility)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # QStackedWidget can mark a page shown while an ancestor is still
        # hidden (geometry_page_3d enabling its 3D stack during __init__).
        # Only map the native surface once this widget is actually on screen.
        if self.isVisible():
            self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        # Must clear before setSource: otherwise the RHI surface is created
        # while still DontShowOnScreen and never composites into the parent.
        self.quick_widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
        self.quick_widget.setSource(QUrl.fromLocalFile(str(self._qml_path)))
        root = self.quick_widget.rootObject()
        if root is not None:
            root.cameraModeChanged.connect(self.camera_mode_changed.emit)
            root.nodePicked.connect(self._on_node_picked)
            root.memberPicked.connect(self._on_member_picked)
            root.planePicked.connect(self._on_plane_picked)
            root.nodeHovered.connect(self.node_hovered.emit)
            root.planeHovered.connect(self._on_plane_hovered)
            root.hoverCleared.connect(self.hover_cleared.emit)
            root.selectionBoxFinished.connect(self._on_selection_box_finished)
            root.emptySpaceClicked.connect(self.empty_space_clicked.emit)
            root.displayVisibilityRequested.connect(self._queue_display_visibility)
            if self._pending_camera_preset is not None:
                root.setPreset(self._pending_camera_preset)
            if self._pending_plane is not None:
                kind, offset = self._pending_plane
                root.setProperty("planeKind", kind)
                root.setProperty("planeOffset", offset)
            if self._pending_picking is not None:
                root.setProperty("pickingEnabled", self._pending_picking)
            if self._pending_plane_picking is not None:
                root.setProperty("planePickingEnabled", self._pending_plane_picking)

        if self._pending_picking:
            self.quick_widget.setCursor(Qt.CursorShape.CrossCursor)
        elif self._pending_plane_picking:
            self.quick_widget.setCursor(Qt.CursorShape.CrossCursor)

        if self._pending_model is not None:
            self._model_coalesce_timer.stop()
            self._flush_coalesced_model()
        else:
            self.bridge.resync_after_qml_load()

    def _on_node_picked(self, tag: int, x: float, y: float) -> None:
        global_pos = self.quick_widget.mapToGlobal(QPoint(int(x), int(y)))
        self.node_picked.emit(tag, global_pos.x(), global_pos.y())

    def _on_member_picked(self, tag: int, x: float, y: float) -> None:
        global_pos = self.quick_widget.mapToGlobal(QPoint(int(x), int(y)))
        self.member_picked.emit(tag, global_pos.x(), global_pos.y())

    def _on_plane_picked(self, view_x: float, view_y: float, view_z: float) -> None:
        # Inverse of Quick3DSceneBridge._view_coordinates: view = (x, z, -y).
        self.plane_point_picked.emit(view_x, -view_z, view_y)

    def _on_plane_hovered(self, view_x: float, view_y: float, view_z: float) -> None:
        self.plane_point_hovered.emit(view_x, -view_z, view_y)

    def _on_selection_box_finished(
        self, node_tags: str, member_tags: str, additive: bool
    ) -> None:
        def parse_tags(serialized: str) -> set[int]:
            return {int(value) for value in serialized.split(",") if value}

        self.selection_box_finished.emit(
            parse_tags(node_tags), parse_tags(member_tags), additive
        )

    def _queue_display_visibility(self, item: str, visible: bool) -> None:
        """Apply QML display clicks after its pointer callback has returned."""
        self._pending_display_visibility[str(item)] = bool(visible)
        if not self._display_visibility_timer.isActive():
            self._display_visibility_timer.start(0)

    def _flush_display_visibility(self) -> None:
        pending = self._pending_display_visibility
        self._pending_display_visibility = {}
        setters = {
            "nodes": self.bridge.set_nodes_visible,
            "node_numbers": self.bridge.set_node_numbers_visible,
            "members": self.bridge.set_members_visible,
            "member_numbers": self.bridge.set_member_numbers_visible,
            "loads": self.bridge.set_loads_visible,
            "nodal_loads": self.bridge.set_nodal_loads_visible,
            "member_loads": self.bridge.set_member_loads_visible,
            "floor_loads": self.bridge.set_floor_loads_visible,
            "self_weight_loads": self.bridge.set_self_weight_loads_visible,
        }
        for item, visible in pending.items():
            setter = setters.get(item)
            if setter is not None:
                setter(visible)

    def set_preview_segment(
        self,
        start: tuple[float, float, float] | None,
        end: tuple[float, float, float] | None,
    ) -> None:
        """Rubber-band the free-form 3D draw preview from ``start`` to ``end``
        (both structural x/y/z), or clear it if either is ``None``."""
        self.bridge.set_preview_segment(start, end)

    def set_floor_boundary_outline(self, points: list[tuple[float, float, float]]) -> None:
        """Trace the in-progress floor boundary's yellow outline - see
        ``Quick3DSceneBridge.set_floor_boundary_outline``."""
        self.bridge.set_floor_boundary_outline(points)

    def set_picking_mode(self, enabled: bool) -> None:
        self._pending_picking = enabled
        if enabled:
            self.quick_widget.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.quick_widget.unsetCursor()
        root = self.quick_widget.rootObject()
        if root is not None:
            root.setProperty("pickingEnabled", enabled)

    def set_plane_picking_mode(self, enabled: bool) -> None:
        """Toggle click-to-place-on-the-active-plane, for free-form 3D drawing.

        Kept distinct from ``set_picking_mode`` (used by the read-only result
        viewport to inspect a node's displacement) so turning one on never
        changes the other's behaviour.
        """
        self._pending_plane_picking = enabled
        if enabled:
            self.quick_widget.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.quick_widget.unsetCursor()
        root = self.quick_widget.rootObject()
        if root is not None:
            root.setProperty("planePickingEnabled", enabled)

    def set_active_plane(self, kind: str, offset: float) -> None:
        self._pending_plane = (kind, offset)
        root = self.quick_widget.rootObject()
        if root is not None:
            root.setProperty("planeKind", kind)
            root.setProperty("planeOffset", offset)

    def set_model(self, model: StructuralModel, reset_camera: bool = True) -> None:
        """Load a model, optionally without reframing the camera.

        Reframing on every call is right for opening a file once, but wrong
        while a student is actively drawing — the view would jump back to ISO
        after every single click, which is the opposite of the free orbiting
        this viewport is meant to offer.

        Rapid ``model_changed`` bursts (copy/array, property apply) are
        coalesced to one bridge update per event-loop turn so intermediate
        ``build_model()`` results never stack back-to-back on the GUI thread.
        """
        self._pending_model = model
        self._pending_reset_camera = reset_camera
        if not self._model_coalesce_timer.isActive():
            self._model_coalesce_timer.start(0)

    def _flush_coalesced_model(self) -> None:
        model = self._pending_model
        if model is None:
            return
        reset_camera = self._pending_reset_camera
        self._pending_model = None
        self.bridge.set_model(model)
        if reset_camera:
            self.set_camera_preset("iso")

    def _ensure_bridge_current(self) -> None:
        """Apply any coalesced ``set_model`` before other bridge operations."""
        if self._pending_model is None:
            return
        self._model_coalesce_timer.stop()
        self._flush_coalesced_model()

    def show_result(
        self,
        model: StructuralModel,
        result: AnalysisResult,
        scale: float,
        show_undeformed: bool = True,
        member_magnitudes: dict[int, float] | None = None,
        force_diagrams: list[dict[str, object]] | None = None,
        overlay_labels: list[dict[str, object]] | None = None,
    ) -> None:
        self._ensure_bridge_current()
        self.bridge.set_result(
            model,
            result,
            scale,
            show_undeformed,
            member_magnitudes=member_magnitudes,
            force_diagrams=force_diagrams,
            overlay_labels=overlay_labels,
        )

    def begin_time_history_deformation(
        self,
        model: StructuralModel,
        *,
        show_original: bool = True,
        show_deformed: bool = True,
    ) -> None:
        self._ensure_bridge_current()
        self.bridge.begin_time_history_deformation(
            model, show_original=show_original, show_deformed=show_deformed
        )

    def update_deformed_node_positions(
        self,
        deformed_points: dict[int, tuple[float, float, float]],
        *,
        show_original: bool = True,
        show_deformed: bool = True,
        node_ratios: dict[int, float] | None = None,
    ) -> None:
        self._ensure_bridge_current()
        self.bridge.update_deformed_node_positions(
            deformed_points,
            show_original=show_original,
            show_deformed=show_deformed,
            node_ratios=node_ratios,
        )

    def end_time_history_deformation(self) -> None:
        self._ensure_bridge_current()
        self.bridge.end_time_history_deformation()

    def begin_torsion_marker_mode(self, model: StructuralModel, marker_count: int = 5) -> None:
        self._ensure_bridge_current()
        self.bridge.begin_torsion_marker_mode(model, marker_count=marker_count)

    def update_torsion_markers(self, arms: tuple[object, ...], *, visible: bool) -> None:
        self._ensure_bridge_current()
        self.bridge.update_torsion_markers(arms, visible=visible)

    def end_torsion_marker_mode(self) -> None:
        self._ensure_bridge_current()
        self.bridge.end_torsion_marker_mode()

    def clear_result(self) -> None:
        self._ensure_bridge_current()
        self.bridge.clear_result()

    def set_nodes_visible(self, visible: bool) -> None:
        self.bridge.set_nodes_visible(visible)

    def set_node_numbers_visible(self, visible: bool) -> None:
        self.bridge.set_node_numbers_visible(visible)

    def set_members_visible(self, visible: bool) -> None:
        self.bridge.set_members_visible(visible)

    def set_member_numbers_visible(self, visible: bool) -> None:
        self.bridge.set_member_numbers_visible(visible)

    def set_loads_visible(self, visible: bool) -> None:
        self._ensure_bridge_current()
        self.bridge.set_loads_visible(visible)

    def set_supports_visible(self, visible: bool) -> None:
        self._ensure_bridge_current()
        self.bridge.set_supports_visible(visible)

    def set_local_axes_visible(self, visible: bool) -> None:
        self._ensure_bridge_current()
        self.bridge.set_local_axes_visible(visible)

    def set_load_filter(self, load_filter: str) -> None:
        self._ensure_bridge_current()
        self.bridge.set_load_filter(load_filter)

    def set_load_case_filter(self, case_filter: str) -> None:
        self._ensure_bridge_current()
        self.bridge.set_load_case_filter(case_filter)

    def set_load_entries(
        self,
        load_entries,
        load_cases,
        load_combinations,
        *,
        mode: str = "case",
        active_case_id: str | None = None,
        active_combination_id: str | None = None,
        scale: float = 1.0,
    ) -> None:
        self._ensure_bridge_current()
        self.bridge.set_load_entries(
            load_entries,
            load_cases,
            load_combinations,
            mode=mode,
            active_case_id=active_case_id,
            active_combination_id=active_combination_id,
            scale=scale,
        )

    def set_selected_node(self, tag: int | None) -> None:
        self._ensure_bridge_current()
        self.bridge.set_selected_node(tag)

    def set_selection(self, node_tags: set[int], member_tags: set[int]) -> None:
        self._ensure_bridge_current()
        self.bridge.set_selection(node_tags, member_tags)

    def set_isolate(self, node_tags: set[int], member_tags: set[int]) -> None:
        self._ensure_bridge_current()
        self.bridge.set_isolate(node_tags, member_tags)

    def clear_isolate(self) -> None:
        self._ensure_bridge_current()
        self.bridge.clear_isolate()

    def isolate_active(self) -> bool:
        return self.bridge.isolateActive

    def set_camera_preset(self, preset: str) -> None:
        if preset not in {"iso", "xy", "xz", "yz"}:
            return
        self._pending_camera_preset = preset
        root = self.quick_widget.rootObject()
        if root is not None:
            # QMetaObject.invokeMethod(root, "setPreset", Q_ARG(str, preset)) silently
            # fails (returns False) for this plain, untyped QML JS function - calling
            # it directly as an attribute is what PySide6 actually resolves reliably.
            root.setPreset(preset)

    def zoom(self, factor: float) -> None:
        root = self.quick_widget.rootObject()
        if root is not None:
            root.zoomBy(factor)
