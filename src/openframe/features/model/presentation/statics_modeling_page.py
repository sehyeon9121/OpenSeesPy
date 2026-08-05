"""Free-form 2D editor for textbook statics problems."""

from itertools import pairwise

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
    UniformElementLoad,
    UnitSystem,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy
from openframe.features.results.presentation.result_viewport import ResultViewport


class StaticsDrawingCanvas(QGraphicsView):
    model_changed = Signal()
    _DRAW_SCALE = 40.0

    def __init__(self, parent: QWidget | None = None) -> None:
        self.scene_model = QGraphicsScene()
        super().__init__(self.scene_model, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setSceneRect(-100_000, -100_000, 200_000, 200_000)
        self.nodes: dict[int, Node] = {}
        self.elements: dict[int, Element] = {}
        self.boundaries: dict[int, BoundaryCondition] = {}
        self.nodal_loads: dict[int, NodalLoad] = {}
        self.element_loads: dict[int, UniformElementLoad] = {}
        self.mode = "select"
        self.selection_filter = "all"
        self.grid = 1.0
        self._member_start: int | None = None
        self._selected: tuple[str, int] | None = None
        self.selected_nodes: set[int] = set()
        self.selected_elements: set[int] = set()
        self.hinge_nodes: set[int] = set()
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self._preview_point: QPointF | None = None
        self._panning = False
        self._pan_start = QPointF()
        self.support_restraints = (True, True, False)
        self.pending_nodal_load = (0.0, -10.0, 0.0)
        self.pending_uniform_load = (0.0, -10.0)
        self._undo_stack: list[dict[str, object]] = []
        self._redo_stack: list[dict[str, object]] = []
        self._history_group_depth = 0
        self._history_group_snapshot: dict[str, object] | None = None

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._member_start = None
        self._preview_point = None
        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
            if mode == "select"
            else QGraphicsView.DragMode.NoDrag
        )
        self._redraw()

    def select_all(self) -> None:
        self.selected_nodes = set(self.nodes)
        self.selected_elements = set(self.elements)
        self._redraw()

    def clear_selection(self) -> None:
        self.selected_nodes.clear()
        self.selected_elements.clear()
        self._selected = None
        self._redraw()

    def fit_model(self) -> None:
        bounds = self.scene_model.itemsBoundingRect()
        if not bounds.isEmpty():
            self.fitInView(bounds.adjusted(-50, -50, 50, 50), Qt.AspectRatioMode.KeepAspectRatio)

    def set_selected_node_kind(self, hinge: bool) -> None:
        if not self.selected_nodes:
            return
        self._record_history()
        if hinge:
            self.hinge_nodes.update(self.selected_nodes)
        else:
            self.hinge_nodes.difference_update(self.selected_nodes)
        self._changed()

    def apply_support_to_selection(self, restraints: tuple[bool, bool, bool]) -> None:
        if not self.selected_nodes:
            return
        self._record_history()
        for node_tag in self.selected_nodes:
            self.boundaries[node_tag] = BoundaryCondition(node_tag, restraints)
        self._changed()

    def apply_nodal_load_to_selection(self, values: tuple[float, float, float]) -> None:
        if not self.selected_nodes:
            return
        self._record_history()
        for node_tag in self.selected_nodes:
            self.nodal_loads[node_tag] = NodalLoad(node_tag, values)
        self._changed()

    def apply_uniform_load_to_selection(self, values: tuple[float, float]) -> None:
        if not self.selected_elements:
            return
        self._record_history()
        for element_tag in self.selected_elements:
            self.element_loads[element_tag] = UniformElementLoad(
                element_tag, wx=values[0], wy=values[1]
            )
        self._changed()

    def add_node(self, x: float, y: float) -> int:
        existing = self._nearest_node(x, y)
        if existing is not None:
            return existing
        self._record_history()
        tag = max(self.nodes, default=0) + 1
        self.nodes[tag] = Node(tag, x, y)
        self._split_members_at_node(tag)
        self._changed()
        return tag

    def add_member(self, node_i: int, node_j: int) -> int | None:
        if node_i == node_j:
            return None
        start = self.nodes[node_i]
        end = self.nodes[node_j]
        intermediate = sorted(
            (
                (parameter, tag)
                for tag, node in self.nodes.items()
                if tag not in {node_i, node_j}
                and (parameter := self._point_parameter(node, start, end)) is not None
            ),
            key=lambda item: item[0],
        )
        chain = [node_i, *(tag for _, tag in intermediate), node_j]
        pairs = list(pairwise(chain))
        missing = [
            pair
            for pair in pairs
            if not any(
                {element.node_i, element.node_j} == set(pair)
                for element in self.elements.values()
            )
        ]
        if not missing:
            return None
        self._record_history()
        first_tag: int | None = None
        for pair in missing:
            tag = max(self.elements, default=0) + 1
            self.elements[tag] = Element(tag, pair[0], pair[1], "frame")
            first_tag = tag if first_tag is None else first_tag
        self._changed()
        return first_tag

    def _split_members_at_node(self, node_tag: int) -> None:
        node = self.nodes[node_tag]
        for tag, element in list(self.elements.items()):
            start = self.nodes[element.node_i]
            end = self.nodes[element.node_j]
            if self._point_parameter(node, start, end) is None:
                continue
            original_end = element.node_j
            self.elements[tag] = Element(
                tag,
                element.node_i,
                node_tag,
                element.element_type,
                dict(element.properties),
            )
            new_tag = max(self.elements, default=0) + 1
            self.elements[new_tag] = Element(
                new_tag,
                node_tag,
                original_end,
                element.element_type,
                dict(element.properties),
            )
            load = self.element_loads.get(tag)
            if load is not None:
                self.element_loads[new_tag] = UniformElementLoad(
                    new_tag,
                    wx=load.wx,
                    wy=load.wy,
                    wz=load.wz,
                    pattern_tag=load.pattern_tag,
                    case_type=load.case_type,
                )

    @staticmethod
    def _point_parameter(point: Node, start: Node, end: Node) -> float | None:
        dx = end.x - start.x
        dy = end.y - start.y
        length_squared = dx * dx + dy * dy
        if length_squared <= 1.0e-18:
            return None
        parameter = ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_squared
        if not 1.0e-9 < parameter < 1.0 - 1.0e-9:
            return None
        projected_x = start.x + parameter * dx
        projected_y = start.y + parameter * dy
        tolerance = max(length_squared**0.5, 1.0) * 1.0e-8
        if abs(point.x - projected_x) > tolerance or abs(point.y - projected_y) > tolerance:
            return None
        return parameter

    def set_support(self, node_tag: int, restraints: tuple[bool, bool, bool]) -> None:
        self._record_history()
        self.boundaries[node_tag] = BoundaryCondition(node_tag, restraints)
        self._changed()

    def set_nodal_load(self, node_tag: int, values: tuple[float, float, float]) -> None:
        self._record_history()
        self.nodal_loads[node_tag] = NodalLoad(node_tag, values)
        self._changed()

    def set_uniform_load(self, element_tag: int, values: tuple[float, float]) -> None:
        self._record_history()
        self.element_loads[element_tag] = UniformElementLoad(
            element_tag, wx=values[0], wy=values[1]
        )
        self._changed()

    def build_model(self) -> StructuralModel:
        model = StructuralModel(
            nodes=dict(self.nodes),
            elements=dict(self.elements),
            boundaries=list(self.boundaries.values()),
            nodal_loads=list(self.nodal_loads.values()),
            element_loads=list(self.element_loads.values()),
        )
        model.metadata["hinge_nodes"] = ",".join(str(tag) for tag in sorted(self.hinge_nodes))
        return model

    def delete_selected(self) -> None:
        node_tags = set(self.selected_nodes)
        element_tags = set(self.selected_elements)
        if self._selected is not None:
            kind, tag = self._selected
            (node_tags if kind == "node" else element_tags).add(tag)
        if not node_tags and not element_tags:
            return
        self._record_history()
        for tag in node_tags:
            connected = [
                key
                for key, element in self.elements.items()
                if tag in {element.node_i, element.node_j}
            ]
            element_tags.update(connected)
            self.nodes.pop(tag, None)
            self.boundaries.pop(tag, None)
            self.nodal_loads.pop(tag, None)
            self.hinge_nodes.discard(tag)
        for tag in element_tags:
            self.elements.pop(tag, None)
            self.element_loads.pop(tag, None)
        self._selected = None
        self.selected_nodes.clear()
        self.selected_elements.clear()
        self._changed()

    def begin_history_group(self) -> None:
        if self._history_group_depth == 0:
            self._history_group_snapshot = self._snapshot()
        self._history_group_depth += 1

    def end_history_group(self) -> None:
        if self._history_group_depth == 0:
            return
        self._history_group_depth -= 1
        if self._history_group_depth == 0 and self._history_group_snapshot is not None:
            if self._history_group_snapshot != self._snapshot():
                self._undo_stack.append(self._history_group_snapshot)
                self._redo_stack.clear()
            self._history_group_snapshot = None

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())

    def _record_history(self) -> None:
        if self._history_group_depth:
            return
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()

    def _snapshot(self) -> dict[str, object]:
        return {
            "nodes": dict(self.nodes),
            "elements": dict(self.elements),
            "boundaries": dict(self.boundaries),
            "nodal_loads": dict(self.nodal_loads),
            "element_loads": dict(self.element_loads),
            "hinge_nodes": set(self.hinge_nodes),
        }

    def _restore(self, snapshot: dict[str, object]) -> None:
        self.nodes = dict(snapshot["nodes"])
        self.elements = dict(snapshot["elements"])
        self.boundaries = dict(snapshot["boundaries"])
        self.nodal_loads = dict(snapshot["nodal_loads"])
        self.element_loads = dict(snapshot["element_loads"])
        self.hinge_nodes = set(snapshot["hinge_nodes"])
        self.selected_nodes.clear()
        self.selected_elements.clear()
        self._selected = None
        self._member_start = None
        self._preview_point = None
        self._changed()

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
        point = self.mapToScene(event.position().toPoint())
        x = round(point.x() / self._DRAW_SCALE / self.grid) * self.grid
        y = round(-point.y() / self._DRAW_SCALE / self.grid) * self.grid
        node = self._node_at_view(event.position().toPoint())
        if node is None:
            node = self._node_near_scene(point)
        member = self._member_at_view(event.position().toPoint())
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
            self.set_support(node, self.support_restraints)
        elif self.mode == "nodal_load" and node is not None:
            self.set_nodal_load(node, self.pending_nodal_load)
        elif self.mode == "uniform_load" and member is not None:
            self.set_uniform_load(member, self.pending_uniform_load)

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
        if self.mode == "member" and self._member_start is not None:
            snapped = self._node_near_scene(point)
            if snapped is not None:
                node = self.nodes[snapped]
                self._preview_point = QPointF(
                    node.x * self._DRAW_SCALE, -node.y * self._DRAW_SCALE
                )
            else:
                self._preview_point = point
            self._redraw()
            return
        if self.mode == "select" and self._drag_start is not None:
            self._drag_current = point
            self._redraw()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        if self.mode == "select" and self._drag_start is not None:
            current = self._drag_current or self._drag_start
            rectangle = QRectF(self._drag_start, current).normalized()
            self._select_in_rect(rectangle, crossing=current.x() < self._drag_start.x())
            self._drag_start = None
            self._drag_current = None
            self._redraw()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self.scale(factor, factor)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
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

    def _changed(self) -> None:
        self._redraw()
        self.model_changed.emit()

    def _redraw(self) -> None:
        self.scene_model.clear()
        scale = self._DRAW_SCALE
        for tag, element in self.elements.items():
            a, b = self.nodes[element.node_i], self.nodes[element.node_j]
            selected = tag in self.selected_elements or self._selected == ("element", tag)
            item = self.scene_model.addLine(
                a.x * scale,
                -a.y * scale,
                b.x * scale,
                -b.y * scale,
                QPen(QColor("#ef4444" if selected else "#174ea6"), 4),
            )
            item.setData(0, ("element", tag))
            if tag in self.element_loads:
                self._draw_uniform_load(a, b, self.element_loads[tag], scale)
        for tag, node in self.nodes.items():
            item = QGraphicsEllipseItem(-6, -6, 12, 12)
            item.setPos(node.x * scale, -node.y * scale)
            selected = tag in self.selected_nodes or self._selected == ("node", tag)
            if tag in self.hinge_nodes:
                item.setRect(-8, -8, 16, 16)
                item.setBrush(QColor("#fff7ed"))
                item.setPen(QPen(QColor("#f97316" if not selected else "#ef4444"), 3))
            else:
                item.setBrush(QColor("#dbeafe" if selected else "#174ea6"))
            item.setPen(QPen(QColor("#174ea6"), 2))
            item.setData(0, ("node", tag))
            self.scene_model.addItem(item)
            self.scene_model.addText(f"N{tag}").setPos(node.x * scale + 7, -node.y * scale - 22)
            if tag in self.boundaries:
                self._draw_support(node, self.boundaries[tag].restraints, scale)
            if tag in self.nodal_loads:
                self._draw_nodal_load(node, self.nodal_loads[tag].values, scale)
        if self._member_start in self.nodes:
            node = self.nodes[self._member_start]
            self.scene_model.addEllipse(
                node.x * scale - 10, -node.y * scale - 10, 20, 20, QPen(QColor("#22c55e"), 2)
            )
            if self._preview_point is not None:
                preview_pen = QPen(QColor("#22c55e"), 2, Qt.PenStyle.DashLine)
                self.scene_model.addLine(
                    node.x * scale,
                    -node.y * scale,
                    self._preview_point.x(),
                    self._preview_point.y(),
                    preview_pen,
                )
                snapped = self._node_near_scene(self._preview_point)
                if snapped is not None:
                    target = self.nodes[snapped]
                    self.scene_model.addEllipse(
                        target.x * scale - 11,
                        -target.y * scale - 11,
                        22,
                        22,
                        QPen(QColor("#22c55e"), 2),
                    )
        if self._drag_start is not None and self._drag_current is not None:
            crossing = self._drag_current.x() < self._drag_start.x()
            selection_color = QColor("#16a34a" if crossing else "#2563eb")
            self.scene_model.addRect(
                QRectF(self._drag_start, self._drag_current).normalized(),
                QPen(selection_color, 1, Qt.PenStyle.DashLine),
                QColor(selection_color.red(), selection_color.green(), selection_color.blue(), 35),
            )

    def _nearest_node(self, x: float, y: float) -> int | None:
        return next(
            (tag for tag, node in self.nodes.items() if abs(node.x - x) < 0.2 and abs(node.y - y) < 0.2),
            None,
        )

    def _node_near_scene(self, point: QPointF, tolerance: float = 16.0) -> int | None:
        candidates = (
            (
                (node.x * self._DRAW_SCALE - point.x()) ** 2
                + (-node.y * self._DRAW_SCALE - point.y()) ** 2,
                tag,
            )
            for tag, node in self.nodes.items()
        )
        distance, tag = min(candidates, default=(float("inf"), None))
        return tag if distance <= tolerance * tolerance else None

    def _toggle_selection(
        self, key: tuple[str, int], modifiers: Qt.KeyboardModifier
    ) -> None:
        if not modifiers & Qt.KeyboardModifier.ControlModifier:
            self.selected_nodes.clear()
            self.selected_elements.clear()
        kind, tag = key
        if self.selection_filter == "nodes" and kind != "node":
            return
        if self.selection_filter == "elements" and kind != "element":
            return
        target = self.selected_nodes if kind == "node" else self.selected_elements
        if tag in target and modifiers & Qt.KeyboardModifier.ControlModifier:
            target.remove(tag)
        else:
            target.add(tag)
        self._selected = key
        self._redraw()

    def _select_in_rect(self, rectangle: QRectF, *, crossing: bool) -> None:
        scale = self._DRAW_SCALE
        if self.selection_filter in {"all", "nodes"}:
            for tag, node in self.nodes.items():
                if rectangle.contains(QPointF(node.x * scale, -node.y * scale)):
                    self.selected_nodes.add(tag)
        if self.selection_filter in {"all", "elements"}:
            for tag, element in self.elements.items():
                a, b = self.nodes[element.node_i], self.nodes[element.node_j]
                start = QPointF(a.x * scale, -a.y * scale)
                end = QPointF(b.x * scale, -b.y * scale)
                fully_inside = rectangle.contains(start) and rectangle.contains(end)
                member_line = QLineF(start, end)
                edges = (
                    QLineF(rectangle.topLeft(), rectangle.topRight()),
                    QLineF(rectangle.topRight(), rectangle.bottomRight()),
                    QLineF(rectangle.bottomRight(), rectangle.bottomLeft()),
                    QLineF(rectangle.bottomLeft(), rectangle.topLeft()),
                )
                intersects = rectangle.contains(start) or rectangle.contains(end)
                if not intersects:
                    intersects = any(
                        member_line.intersects(edge)[0]
                        != QLineF.IntersectionType.NoIntersection
                        for edge in edges
                    )
                if fully_inside or (crossing and intersects):
                    self.selected_elements.add(tag)

    def _draw_support(
        self, node: Node, restraints: tuple[bool, ...], scale: float
    ) -> None:
        x, y = node.x * scale, -node.y * scale
        pen = QPen(QColor("#334155"), 2)
        normalized = tuple(restraints[:3])
        if normalized == (True, True, True):
            self.scene_model.addLine(x - 14, y + 8, x + 14, y + 8, pen)
            for offset in (-12, -6, 0, 6, 12):
                self.scene_model.addLine(x + offset, y + 8, x + offset - 5, y + 16, pen)
            return
        if normalized == (True, False, False):
            self.scene_model.addLine(x + 8, y - 12, x + 8, y + 12, pen)
            self.scene_model.addLine(x, y, x + 8, y - 10, pen)
            self.scene_model.addLine(x, y, x + 8, y + 10, pen)
            self.scene_model.addEllipse(x + 10, y - 7, 4, 4, pen)
            self.scene_model.addEllipse(x + 10, y + 3, 4, 4, pen)
            return
        self.scene_model.addLine(x, y, x - 11, y + 17, pen)
        self.scene_model.addLine(x, y, x + 11, y + 17, pen)
        self.scene_model.addLine(x - 11, y + 17, x + 11, y + 17, pen)
        if normalized == (False, True, False):
            self.scene_model.addEllipse(x - 8, y + 18, 5, 5, pen)
            self.scene_model.addEllipse(x + 3, y + 18, 5, 5, pen)

    def _draw_nodal_load(self, node: Node, values: tuple[float, ...], scale: float) -> None:
        fx, fy, mz = (*values, 0.0, 0.0, 0.0)[:3]
        origin = QPointF(node.x * scale, -node.y * scale)
        if fx:
            direction = -1.0 if fx > 0 else 1.0
            self._draw_arrow(origin + QPointF(direction * 38, 0), origin, f"Fx {fx:g}")
        if fy:
            direction = 1.0 if fy > 0 else -1.0
            self._draw_arrow(origin + QPointF(0, direction * 38), origin, f"Fy {fy:g}")
        if mz:
            label = self.scene_model.addText(f"↻ Mz {mz:g}" if mz < 0 else f"↺ Mz {mz:g}")
            label.setDefaultTextColor(QColor("#dc2626"))
            label.setPos(origin + QPointF(10, -38))

    def _draw_uniform_load(
        self, start: Node, end: Node, load: UniformElementLoad, scale: float
    ) -> None:
        for fraction in (0.1, 0.3, 0.5, 0.7, 0.9):
            point = QPointF(
                (start.x + (end.x - start.x) * fraction) * scale,
                -(start.y + (end.y - start.y) * fraction) * scale,
            )
            if load.wy:
                offset = QPointF(0, -32 if load.wy < 0 else 32)
                self._draw_arrow(point + offset, point, "" if fraction != 0.5 else f"qy {load.wy:g}")
            if load.wx and fraction == 0.5:
                offset = QPointF(-35 if load.wx > 0 else 35, 0)
                self._draw_arrow(point + offset, point, f"qx {load.wx:g}")

    def _draw_arrow(self, start: QPointF, end: QPointF, text: str) -> None:
        pen = QPen(QColor("#dc2626"), 2)
        self.scene_model.addLine(start.x(), start.y(), end.x(), end.y(), pen)
        delta = start - end
        length = max((delta.x() ** 2 + delta.y() ** 2) ** 0.5, 1.0)
        unit = QPointF(delta.x() / length, delta.y() / length)
        normal = QPointF(-unit.y(), unit.x())
        wing = 7.0
        self.scene_model.addLine(
            end.x(), end.y(),
            end.x() + unit.x() * wing + normal.x() * wing / 2,
            end.y() + unit.y() * wing + normal.y() * wing / 2,
            pen,
        )
        self.scene_model.addLine(
            end.x(), end.y(),
            end.x() + unit.x() * wing - normal.x() * wing / 2,
            end.y() + unit.y() * wing - normal.y() * wing / 2,
            pen,
        )
        if text:
            label = self.scene_model.addText(text)
            label.setDefaultTextColor(QColor("#dc2626"))
            label.setPos(start + QPointF(4, -18))

    def _item_key(self, position) -> tuple[str, int] | None:
        item = self.itemAt(position)
        value = item.data(0) if item is not None else None
        return value if isinstance(value, tuple) else None

    def _node_at_view(self, position) -> int | None:
        key = self._item_key(position)
        return key[1] if key and key[0] == "node" else None

    def _member_at_view(self, position) -> int | None:
        key = self._item_key(position)
        return key[1] if key and key[0] == "element" else None


class StaticsModelingPage(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._solver = MaterialFreeStaticsSolver()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        toolbar = QHBoxLayout()
        self.canvas = StaticsDrawingCanvas()
        for text, mode in (("선택", "select"), ("절점", "node"), ("부재", "member")):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, value=mode: self.canvas.set_mode(value))
            toolbar.addWidget(button)
        self.support_kind = QComboBox()
        self.support_kind.addItem("핀", (True, True, False))
        self.support_kind.addItem("수직 롤러", (False, True, False))
        self.support_kind.addItem("수평 롤러", (True, False, False))
        self.support_kind.addItem("고정", (True, True, True))
        support = QPushButton("지점 배치")
        support.clicked.connect(self._support_mode)
        toolbar.addWidget(self.support_kind)
        toolbar.addWidget(support)
        self.fy = self._number(-10.0)
        load = QPushButton("절점하중 배치")
        load.clicked.connect(self._load_mode)
        toolbar.addWidget(QLabel("Fy"))
        toolbar.addWidget(self.fy)
        toolbar.addWidget(load)
        self.qy = self._number(-10.0)
        uniform = QPushButton("분포하중 배치")
        uniform.clicked.connect(self._uniform_mode)
        toolbar.addWidget(QLabel("qy"))
        toolbar.addWidget(self.qy)
        toolbar.addWidget(uniform)
        delete = QPushButton("삭제")
        delete.clicked.connect(self.canvas.delete_selected)
        toolbar.addWidget(delete)
        toolbar.addStretch(1)
        self.solve_button = QPushButton("해석")
        self.solve_button.clicked.connect(self.solve)
        toolbar.addWidget(self.solve_button)
        root.addLayout(toolbar)
        self.status = QLabel("절점 도구로 절점을 배치한 뒤 부재를 연결하세요.")
        root.addWidget(self.status)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.canvas)
        result_page = QFrame()
        result_layout = QVBoxLayout(result_page)
        result_tools = QHBoxLayout()
        back = QPushButton("모델로 돌아가기")
        back.clicked.connect(lambda: self.stack.setCurrentWidget(self.canvas))
        result_tools.addWidget(back)
        for text, kind in (("반력", "reaction"), ("N", "axial"), ("V", "shear"), ("M", "moment")):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, value=kind: self.viewport.set_result_type(value))
            result_tools.addWidget(button)
        result_tools.addStretch(1)
        result_layout.addLayout(result_tools)
        self.viewport = ResultViewport()
        result_layout.addWidget(self.viewport)
        self.stack.addWidget(result_page)
        root.addWidget(self.stack, 1)
        self.canvas.model_changed.connect(self._update_status)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self.viewport.set_unit_system(unit_system)

    def solve(self) -> None:
        model = self.canvas.build_model()
        check = check_determinacy(model)
        self.status.setText(check.message)
        result = self._solver.solve(model)
        if result.status.value != "completed":
            return
        self.viewport.set_model(model)
        self.viewport.show_result(result)
        self.viewport.set_result_type("reaction")
        self.stack.setCurrentIndex(1)

    def _support_mode(self) -> None:
        self.canvas.support_restraints = self.support_kind.currentData()
        self.canvas.set_mode("support")

    def _load_mode(self) -> None:
        self.canvas.pending_nodal_load = (0.0, self.fy.value(), 0.0)
        self.canvas.set_mode("nodal_load")

    def _uniform_mode(self) -> None:
        self.canvas.pending_uniform_load = (0.0, self.qy.value())
        self.canvas.set_mode("uniform_load")

    def _update_status(self) -> None:
        model = self.canvas.build_model()
        self.status.setText(
            f"절점 {len(model.nodes)} · 부재 {len(model.elements)} · "
            f"지점 {len(model.boundaries)} · 하중 {len(model.nodal_loads) + len(model.element_loads)}"
        )

    @staticmethod
    def _number(value: float) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setRange(-1_000_000.0, 1_000_000.0)
        field.setValue(value)
        field.setMaximumWidth(90)
        return field
