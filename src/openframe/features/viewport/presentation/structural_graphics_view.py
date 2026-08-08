"""Mouse navigation shared by model and result structural viewports."""

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QGraphicsView


class StructuralGraphicsView(QGraphicsView):
    """QGraphicsView with CAD-style orbit, pan and wheel zoom controls."""

    orbit_dragged = Signal(float, float)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._orbit_enabled = False
        self._middle_drag_position: QPoint | None = None
        self._middle_drag_mode: str | None = None
        self._content_scene_rect: QRectF | None = None

    def set_orbit_enabled(self, enabled: bool) -> None:
        self._orbit_enabled = enabled

    def set_content_scene_rect(self, rect: QRectF) -> None:
        """Remember the real content bounds separately from temporary pan space."""
        self._content_scene_rect = QRectF(rect)
        if self.scene() is not None:
            self.scene().setSceneRect(rect)

    def fit_content(self) -> None:
        if self._content_scene_rect is None or self.scene() is None:
            return
        self.scene().setSceneRect(self._content_scene_rect)
        self.fitInView(
            self._content_scene_rect,
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_drag_position = event.position().toPoint()
            shift_pressed = bool(
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            )
            self._middle_drag_mode = (
                "orbit" if self._orbit_enabled and not shift_pressed else "pan"
            )
            if self._middle_drag_mode == "pan":
                self._ensure_pan_space()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._middle_drag_position is None:
            super().mouseMoveEvent(event)
            return

        current = event.position().toPoint()
        previous = self._middle_drag_position
        delta = current - previous
        self._middle_drag_position = current
        if self._middle_drag_mode == "orbit":
            self.orbit_dragged.emit(float(delta.x()), float(delta.y()))
        else:
            horizontal = self.horizontalScrollBar()
            vertical = self.verticalScrollBar()
            horizontal.setValue(horizontal.value() - delta.x())
            vertical.setValue(vertical.value() - delta.y())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle_drag_position = None
            self._middle_drag_mode = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() == 0:
            super().wheelEvent(event)
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)
        event.accept()

    def _ensure_pan_space(self) -> None:
        scene = self.scene()
        if scene is None:
            return
        content = self._content_scene_rect or scene.sceneRect()
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        combined = content.united(visible)
        horizontal_margin = max(visible.width() * 2.0, content.width() * 2.0, 1.0)
        vertical_margin = max(visible.height() * 2.0, content.height() * 2.0, 1.0)
        scene.setSceneRect(
            combined.adjusted(
                -horizontal_margin,
                -vertical_margin,
                horizontal_margin,
                vertical_margin,
            )
        )
