"""Embedded Qt Quick 3D viewport for structural models."""

from pathlib import Path

from PySide6.QtCore import Q_ARG, QMetaObject, QPoint, Qt, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from openframe.core.domain import AnalysisResult, StructuralModel
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)


class Quick3DViewport(QFrame):
    camera_mode_changed = Signal(str)
    node_picked = Signal(int, int, int)

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

    def _on_node_picked(self, tag: int, x: float, y: float) -> None:
        global_pos = self.quick_widget.mapToGlobal(QPoint(int(x), int(y)))
        self.node_picked.emit(tag, global_pos.x(), global_pos.y())

    def set_picking_mode(self, enabled: bool) -> None:
        if enabled:
            self.quick_widget.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.quick_widget.unsetCursor()
        root = self.quick_widget.rootObject()
        if root is not None:
            root.setProperty("pickingEnabled", enabled)

    def set_model(self, model: StructuralModel) -> None:
        self.bridge.set_model(model)
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
            QMetaObject.invokeMethod(root, "setPreset", Q_ARG(str, preset))

    def zoom(self, factor: float) -> None:
        root = self.quick_widget.rootObject()
        if root is not None:
            QMetaObject.invokeMethod(root, "zoomBy", Q_ARG(float, factor))
