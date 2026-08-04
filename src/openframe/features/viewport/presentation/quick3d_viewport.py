"""Embedded Qt Quick 3D viewport for structural models."""

from pathlib import Path

from PySide6.QtCore import Q_ARG, QMetaObject, Qt, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from openframe.core.domain import StructuralModel
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)


class Quick3DViewport(QFrame):
    camera_mode_changed = Signal(str)

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

    def set_model(self, model: StructuralModel) -> None:
        self.bridge.set_model(model)
        self.set_camera_preset("iso")

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
