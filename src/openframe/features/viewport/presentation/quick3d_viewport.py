"""Embedded Qt Quick 3D viewport for structural models."""

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)


class Quick3DViewport(QFrame):
    camera_mode_changed = Signal(str)
    node_picked = Signal(int, int, int)
    #: A click on the active work plane, as structural (x, y, z) — already
    #: converted out of the QML scene's y-up view coordinates, so callers never
    #: need to know about that mapping.
    plane_point_picked = Signal(float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bridge = Quick3DSceneBridge(self)
        self.quick_widget = QQuickWidget(self)
        self.quick_widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.quick_widget.setClearColor(Qt.GlobalColor.transparent)
        self.quick_widget.rootContext().setContextProperty("sceneBridge", self.bridge)
        qml_path = Path(__file__).with_name("qml") / "structural_view.qml"
        self.quick_widget.setSource(QUrl.fromLocalFile(str(qml_path)))
        layout.addWidget(self.quick_widget)

        root = self.quick_widget.rootObject()
        if root is not None:
            root.cameraModeChanged.connect(self.camera_mode_changed.emit)
            root.nodePicked.connect(self._on_node_picked)
            root.planePicked.connect(self._on_plane_picked)

    def _on_node_picked(self, tag: int, x: float, y: float) -> None:
        global_pos = self.quick_widget.mapToGlobal(QPoint(int(x), int(y)))
        self.node_picked.emit(tag, global_pos.x(), global_pos.y())

    def _on_plane_picked(self, view_x: float, view_y: float, view_z: float) -> None:
        # Inverse of Quick3DSceneBridge._view_coordinates: view = (x, z, -y).
        self.plane_point_picked.emit(view_x, -view_z, view_y)

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

    def set_load_filter(self, load_filter: str) -> None:
        self.bridge.set_load_filter(load_filter)

    def set_load_case_filter(self, case_filter: str) -> None:
        self.bridge.set_load_case_filter(case_filter)

    def set_selected_node(self, tag: int | None) -> None:
        self.bridge.set_selected_node(tag)

    def set_camera_preset(self, preset: str) -> None:
        if preset not in {"iso", "xy", "xz", "yz"}:
            return
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
