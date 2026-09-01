"""Qt mouse/key/wheel event overrides for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class. Qt resolves an overridden virtual (``mousePressEvent`` and
friends) the same way normal Python attribute lookup does, so defining these
here instead of directly on ``StaticsDrawingCanvas`` changes nothing about
how/when Qt calls them.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)

from openframe.features.model.drawing import SnapResult, apply_ortho

#: MIME type a Work Tree 물성/섹션 row's drag payload carries (see
#: modeling_interface_page.py's ``_WorkTree.startDrag``) - the payload body
#: is ``"material:<id>"`` or ``"section:<id>"``, resolved against the page's
#: own ``_user_materials``/``_user_sections`` in ``_apply_property_drop``
#: since the canvas itself has no notion of those saved definitions.
PROPERTY_DRAG_MIME_TYPE = "application/x-openframe-property"


class _InputEventsMixin:
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self.mode == "select":
            key = self._item_key(event.position().toPoint())
            if key is not None:
                self._toggle_selection(key, event.modifiers())
            else:
                self._drag_start = self.mapToScene(event.position().toPoint())
                self._drag_current = self._drag_start
                if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self.clear_selection()
            return
        if self.mode == "draw":
            target = self._resolve_cursor(
                self.mapToScene(event.position().toPoint()), event.modifiers()
            )
            self.place_point(target.x, target.y, snap=target)
            return
        point = self.mapToScene(event.position().toPoint())
        x = round(point.x() / self._DRAW_SCALE / self.grid) * self.grid
        y = round(-point.y() / self._DRAW_SCALE / self.grid) * self.grid
        node = self._node_at_view(event.position().toPoint())
        if node is None:
            node = self._node_near_scene(point)
        member = self._member_at_view(event.position().toPoint())
        if member is None:
            member = self._member_near_scene(point)
        can_start_global_selection = (
            node is None
            and member is None
            and not (self.mode == "member" and self._member_start is not None)
        )
        if can_start_global_selection:
            self._drag_start = point
            self._drag_current = point
            if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.clear_selection()
            return
        if self.mode == "node":
            self.add_node(x, y)
        elif self.mode == "member" and node is not None:
            if self._member_start is None:
                self._member_start = node
                self._redraw()
            else:
                start = self._member_start
                self._member_start = None
                self._preview_point = None
                self.add_member(start, node)
        elif self.mode == "support" and node is not None:
            self.set_support(node, self.support_restraints, self.support_angle)
        elif self.mode == "nodal_load" and node is not None:
            self.set_nodal_load(node, self.pending_nodal_load)
        elif self.mode == "uniform_load" and member is not None:
            self.set_uniform_load(member, self.pending_uniform_load)
        elif self.mode == "member_midpoint" and member is not None:
            station = self._member_station_near_scene(point)
            if station is not None:
                self.add_member_station_node(station[0], station[1])

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return
        point = self.mapToScene(event.position().toPoint())
        if self._drag_start is not None:
            self._drag_current = point
            self._redraw()
            return
        if self.mode == "draw":
            target = self._resolve_cursor(point, event.modifiers())
            self._snap = target
            self._preview_point = (
                self._scene_point(target.x, target.y) if self._chain else None
            )
            self._redraw()
            self.draw_state_changed.emit()
            return
        if self.mode == "member" and self._member_start is not None:
            snapped = self._node_near_scene(point)
            if snapped is not None:
                u, v = self._uv(self.nodes[snapped])
                self._preview_point = QPointF(u * self._DRAW_SCALE, -v * self._DRAW_SCALE)
            else:
                self._preview_point = point
            self._redraw()
            return
        if self.mode == "member_midpoint":
            station = self._member_station_near_scene(point)
            if station is None:
                self._preview_midpoint = None
            else:
                member, position, projected = station
                self._preview_midpoint = (member, projected, position)
            self._redraw()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        if self._drag_start is not None:
            current = self._drag_current or self._drag_start
            rectangle = QRectF(self._drag_start, current).normalized()
            self._select_in_rect(rectangle, crossing=self._is_crossing_drag(self._drag_start, current))
            self._drag_start = None
            self._drag_current = None
            self._selection_changed()
            return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(PROPERTY_DRAG_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if not event.mimeData().hasFormat(PROPERTY_DRAG_MIME_TYPE):
            super().dragMoveEvent(event)
            return
        member = self._member_at_view(event.position().toPoint())
        if member != self._drop_target_element:
            self._drop_target_element = member
            self._redraw()
        if member is None:
            event.ignore()
        else:
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        if self._drop_target_element is not None:
            self._drop_target_element = None
            self._redraw()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasFormat(PROPERTY_DRAG_MIME_TYPE):
            super().dropEvent(event)
            return
        member = self._drop_target_element
        self._drop_target_element = None
        self._redraw()
        if member is None:
            event.ignore()
            return
        payload = bytes(event.mimeData().data(PROPERTY_DRAG_MIME_TYPE)).decode("utf-8")
        kind, _, definition_id = payload.partition(":")
        if kind and definition_id:
            self.property_drop_requested.emit(kind, definition_id, member)
        event.acceptProposedAction()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom in/out keeping the point under the cursor fixed on screen.

        ``AnchorUnderMouse`` is not reliable here — it depends on internal Qt
        state this view's mode-switching ``mouseMoveEvent`` override does not
        reliably keep current — and a manual ``scale()`` + ``translate()``
        correction turned out not to compose the way the Qt docs imply either
        (translate's arguments are pre-multiplied into the *new* scale, not
        applied in absolute scene units, so a naive delta correction over- or
        under-shoots). Recomputing the viewport centre and calling ``centerOn``
        is the version that actually holds the anchor point fixed.
        """
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        anchor = event.position().toPoint()
        before = self.mapToScene(anchor)
        self.scale(factor, factor)
        viewport_center = self.mapToScene(QRectF(self.viewport().rect()).center().toPoint())
        anchor_now = self.mapToScene(anchor)
        self.centerOn(viewport_center + (before - anchor_now))
        event.accept()

    def _resolve_cursor(self, scene_point: QPointF, modifiers) -> SnapResult:
        x, y = self._model_point(scene_point)
        anchor = self.chain_anchor
        locked = self.ortho or bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if anchor is not None and locked:
            x, y = apply_ortho(anchor, (x, y), self.ortho_increment)
        return self.snap_at(x, y)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self.mode == "draw":
                # Leaving the tool entirely, not just clearing the in-progress
                # chain — the whole point is not having to reach for the 선택
                # button afterwards. The page listens for this to keep its rail
                # button and property panel in sync with the mode switch.
                self.escape_requested.emit()
            else:
                self.end_chain()
                # Esc doubles as "deselect" in select mode - matches the
                # usual CAD convention, and means clearing a selection never
                # requires reaching for empty canvas space to click on.
                self.clear_selection()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            self.delete_selected()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Undo):
            self.undo()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            self.redo()
            event.accept()
            return
        super().keyPressEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#fbfdff"))
        spacing = 40.0
        left = int(rect.left() // spacing) * spacing
        top = int(rect.top() // spacing) * spacing
        painter.setPen(QPen(QColor("#e7edf5"), 0))
        x = left
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += spacing
        y = top
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += spacing

        origin = self._scene_point(0.0, 0.0)
        x_axis, y_axis = self.axis_lines(
            (rect.left(), rect.top(), rect.right(), rect.bottom()), (origin.x(), origin.y())
        )
        if x_axis is not None:
            painter.setPen(QPen(QColor("#dc2626"), 1.4))
            painter.drawLine(QPointF(x_axis[0], x_axis[1]), QPointF(x_axis[2], x_axis[3]))
            painter.drawText(QPointF(rect.right() - 22, origin.y() - 6), "X")
        if y_axis is not None:
            painter.setPen(QPen(QColor("#16a34a"), 1.4))
            painter.drawLine(QPointF(y_axis[0], y_axis[1]), QPointF(y_axis[2], y_axis[3]))
            painter.drawText(QPointF(origin.x() + 6, rect.top() + 16), "Y")

    @staticmethod
    def axis_lines(
        rect: tuple[float, float, float, float], origin: tuple[float, float]
    ) -> tuple[tuple[float, float, float, float] | None, tuple[float, float, float, float] | None]:
        """X/Y axis line endpoints spanning the visible rect, or None if the
        origin is currently panned off screen in that direction.

        A plain function (rect and origin as tuples, not Qt types) so the
        geometry is testable without constructing a painter or a shown widget —
        the same pattern as ``load_arrow_segments``.
        """
        left, top, right, bottom = rect
        origin_x, origin_y = origin
        x_axis = (left, origin_y, right, origin_y) if top <= origin_y <= bottom else None
        y_axis = (origin_x, top, origin_x, bottom) if left <= origin_x <= right else None
        return x_axis, y_axis
