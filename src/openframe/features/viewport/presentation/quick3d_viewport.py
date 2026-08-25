"""Embedded Qt Quick 3D viewport for structural models."""

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
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

        # setSource() itself (not just becoming visible) is what makes
        # QQuickWidget stand up its scene graph/RHI context - three of these
        # get constructed eagerly at app startup (main viewport, modeling
        # page preview, result viewport), and doing that immediately in
        # __init__ made all three flash a blank native surface before the
        # app's own window ever appears. Deferred to this widget's first real
        # showEvent instead, so a viewport nobody has scrolled to yet never
        # touches the GPU at all. _pending_camera_preset lets a caller that
        # sets a model/camera before the first show (e.g. set_model() while
        # this page isn't the visible one) still take effect once loaded.
        self._loaded = False
        self._pending_camera_preset: str | None = None
        self._qml_path = Path(__file__).with_name("qml") / "structural_view.qml"

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
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
            if self._pending_camera_preset is not None:
                root.setPreset(self._pending_camera_preset)

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

    def set_preview_segment(
        self,
        start: tuple[float, float, float] | None,
        end: tuple[float, float, float] | None,
    ) -> None:
        """Rubber-band the free-form 3D draw preview from ``start`` to ``end``
        (both structural x/y/z), or clear it if either is ``None``."""
        self.bridge.set_preview_segment(start, end)

    def set_picking_mode(self, enabled: bool) -> None:
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
        if enabled:
            self.quick_widget.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.quick_widget.unsetCursor()
        root = self.quick_widget.rootObject()
        if root is not None:
            root.setProperty("planePickingEnabled", enabled)

    def set_active_plane(self, kind: str, offset: float) -> None:
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
        """
        self.bridge.set_model(model)
        if reset_camera:
            self.set_camera_preset("iso")

    def show_result(
        self,
        model: StructuralModel,
        result: AnalysisResult,
        scale: float,
        show_undeformed: bool = True,
    ) -> None:
        self.bridge.set_result(model, result, scale, show_undeformed)

    def clear_result(self) -> None:
        self.bridge.clear_result()

    def set_loads_visible(self, visible: bool) -> None:
        self.bridge.set_loads_visible(visible)

    def set_supports_visible(self, visible: bool) -> None:
        self.bridge.set_supports_visible(visible)

    def set_local_axes_visible(self, visible: bool) -> None:
        self.bridge.set_local_axes_visible(visible)

    def set_load_filter(self, load_filter: str) -> None:
        self.bridge.set_load_filter(load_filter)

    def set_load_case_filter(self, case_filter: str) -> None:
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
        self.bridge.set_selected_node(tag)

    def set_selection(self, node_tags: set[int], member_tags: set[int]) -> None:
        self.bridge.set_selection(node_tags, member_tags)

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
