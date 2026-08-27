"""Embedded Qt Quick 3D viewport for structural models."""

from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QCursor, QShowEvent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)


class _UnloadedQuickSurface(QObject):
    """Stand-in for ``QQuickWidget`` until the first real show.

    Callers (and tests) touch ``preview_3d.quick_widget`` during construction —
    notably ``installEventFilter`` on the modeling page — long before any 3D
    page is on screen. Returning a real ``QQuickWidget`` that early is what
    flashes blank native title-bar windows on Windows at app startup (several
    viewports are built eagerly). This proxy accepts those early calls without
    touching the GPU; ``rootObject()`` stays ``None`` so "not loaded yet"
    checks keep working.
    """

    def __init__(self, owner: "Quick3DViewport") -> None:
        super().__init__(owner)
        self._owner = owner

    def installEventFilter(self, obj: QObject) -> None:
        self._owner._pending_event_filters.append(obj)

    def rootObject(self) -> None:
        return None

    def status(self) -> QQuickWidget.Status:
        return QQuickWidget.Status.Null

    def cursor(self) -> QCursor:
        # Picking cursors only exist on a real surface; an unloaded viewport
        # must not report CrossCursor or 2D-path tests falsely look "armed".
        return QCursor()

    def setCursor(self, _cursor: QCursor) -> None:
        return

    def unsetCursor(self) -> None:
        return

    def mapToGlobal(self, pos: QPoint) -> QPoint:
        return self._owner.mapToGlobal(pos)

    def focusPolicy(self) -> Qt.FocusPolicy:
        return Qt.FocusPolicy.StrongFocus

    def setFocus(self, *_args: object) -> None:
        return


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
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.bridge = Quick3DSceneBridge(self)

        # Both constructing QQuickWidget and calling setSource() stand up an
        # RHI/OpenGL surface. Four of these viewports are built at app startup
        # (import ModelViewport, results, 2D authoring preview, 3D authoring
        # preview); creating them in __init__ flashed a blank native window
        # per instance before MainWindow appeared. Construction + setSource
        # are deferred to the first showEvent where this widget is actually
        # visible inside an already-shown top-level window.
        self._quick_widget: QQuickWidget | None = None
        self._unloaded_surface = _UnloadedQuickSurface(self)
        self._loaded = False
        self._pending_camera_preset: str | None = None
        self._pending_plane: tuple[str, float] | None = None
        self._pending_picking: bool | None = None
        self._pending_plane_picking: bool | None = None
        self._pending_event_filters: list[QObject] = []
        self._qml_path = Path(__file__).with_name("qml") / "structural_view.qml"

    @property
    def quick_widget(self) -> QQuickWidget | _UnloadedQuickSurface:
        if self._quick_widget is not None:
            return self._quick_widget
        return self._unloaded_surface

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # QStackedWidget can mark a page "shown" while an ancestor is still
        # hidden (e.g. geometry_page_3d enabling its 3D stack during __init__).
        # isVisible() is False until the whole chain is on screen — only then
        # is it safe to create the native QQuickWidget without a flash.
        if self.isVisible():
            self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        quick_widget = QQuickWidget(self)
        quick_widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        quick_widget.setClearColor(Qt.GlobalColor.transparent)
        # Needed for the modeling page's Space-bar draw-tool shortcut (scoped
        # to this viewport in 3D mode) to fire at all: a QShortcut with
        # WidgetWithChildrenShortcut context only dispatches while its widget
        # (or a child) actually holds keyboard focus, and QWidget's default
        # focus policy is NoFocus. StrongFocus makes a click in the viewport
        # (already the natural first step of drawing) grab focus for it.
        quick_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        quick_widget.rootContext().setContextProperty("sceneBridge", self.bridge)
        self._layout.addWidget(quick_widget)
        self._quick_widget = quick_widget

        for watcher in self._pending_event_filters:
            quick_widget.installEventFilter(watcher)
        self._pending_event_filters.clear()

        quick_widget.setSource(QUrl.fromLocalFile(str(self._qml_path)))
        root = quick_widget.rootObject()
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
            if self._pending_plane is not None:
                kind, offset = self._pending_plane
                root.setProperty("planeKind", kind)
                root.setProperty("planeOffset", offset)
            if self._pending_picking is not None:
                root.setProperty("pickingEnabled", self._pending_picking)
            if self._pending_plane_picking is not None:
                root.setProperty("planePickingEnabled", self._pending_plane_picking)

        if self._pending_picking:
            quick_widget.setCursor(Qt.CursorShape.CrossCursor)
        if self._pending_plane_picking:
            quick_widget.setCursor(Qt.CursorShape.CrossCursor)

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

    def set_floor_boundary_outline(self, points: list[tuple[float, float, float]]) -> None:
        """Trace the in-progress floor boundary's yellow outline - see
        ``Quick3DSceneBridge.set_floor_boundary_outline``."""
        self.bridge.set_floor_boundary_outline(points)

    def set_picking_mode(self, enabled: bool) -> None:
        self._pending_picking = enabled
        if self._quick_widget is None:
            return
        if enabled:
            self._quick_widget.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._quick_widget.unsetCursor()
        root = self._quick_widget.rootObject()
        if root is not None:
            root.setProperty("pickingEnabled", enabled)

    def set_plane_picking_mode(self, enabled: bool) -> None:
        """Toggle click-to-place-on-the-active-plane, for free-form 3D drawing.

        Kept distinct from ``set_picking_mode`` (used by the read-only result
        viewport to inspect a node's displacement) so turning one on never
        changes the other's behaviour.
        """
        self._pending_plane_picking = enabled
        if self._quick_widget is None:
            return
        if enabled:
            self._quick_widget.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._quick_widget.unsetCursor()
        root = self._quick_widget.rootObject()
        if root is not None:
            root.setProperty("planePickingEnabled", enabled)

    def set_active_plane(self, kind: str, offset: float) -> None:
        self._pending_plane = (kind, offset)
        if self._quick_widget is None:
            return
        root = self._quick_widget.rootObject()
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
        member_magnitudes: dict[int, float] | None = None,
    ) -> None:
        self.bridge.set_result(
            model, result, scale, show_undeformed, member_magnitudes=member_magnitudes
        )

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
        if self._quick_widget is None:
            return
        root = self._quick_widget.rootObject()
        if root is not None:
            # QMetaObject.invokeMethod(root, "setPreset", Q_ARG(str, preset)) silently
            # fails (returns False) for this plain, untyped QML JS function - calling
            # it directly as an attribute is what PySide6 actually resolves reliably.
            root.setPreset(preset)

    def zoom(self, factor: float) -> None:
        if self._quick_widget is None:
            return
        root = self._quick_widget.rootObject()
        if root is not None:
            root.zoomBy(factor)
