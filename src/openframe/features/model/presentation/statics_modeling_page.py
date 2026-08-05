"""Free-form 2D editor for textbook statics problems."""

from dataclasses import replace
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
from openframe.features.model.drawing import (
    SnapOptions,
    SnapResult,
    apply_ortho,
    parse_entry,
    resolve_snap,
)
from openframe.features.model.drawing.coordinates import direction_degrees, distance
from openframe.features.results.presentation.result_viewport import ResultViewport


class StaticsDrawingCanvas(QGraphicsView):
    model_changed = Signal()
    draw_state_changed = Signal()
    _DRAW_SCALE = 40.0
    _SNAP_PIXELS = 14.0

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
        self.embedded_nodes: dict[int, tuple[int, float]] = {}
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
        self._preview_midpoint: tuple[int, QPointF, float] | None = None
        self._panning = False
        self._pan_start = QPointF()
        self.support_restraints = (True, True, False)
        self.pending_nodal_load = (0.0, -10.0, 0.0)
        self.pending_uniform_load = (0.0, -10.0)
        self.snap_options = SnapOptions()
        self.ortho = False
        self.ortho_increment = 45.0
        self._chain: list[int] = []
        self._snap: SnapResult | None = None
        self._undo_stack: list[dict[str, object]] = []
        self._redo_stack: list[dict[str, object]] = []
        self._history_group_depth = 0
        self._history_group_snapshot: dict[str, object] | None = None

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._member_start = None
        self._preview_point = None
        self._preview_midpoint = None
        self._chain.clear()
        self._snap = None
        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
            if mode == "select"
            else QGraphicsView.DragMode.NoDrag
        )
        self._redraw()
        self.draw_state_changed.emit()

    # --- free-form drawing -------------------------------------------------

    @property
    def is_drawing(self) -> bool:
        return bool(self._chain)

    @property
    def chain_anchor(self) -> tuple[float, float] | None:
        """Model-space point the next member starts from, if a chain is open."""
        node = self.nodes.get(self._chain[-1]) if self._chain else None
        return None if node is None else (node.x, node.y)

    @property
    def snap_label(self) -> str:
        return self._snap.label if self._snap is not None else ""

    def pending_length_and_angle(self) -> tuple[float, float] | None:
        """Length and angle of the member currently being rubber-banded."""
        anchor = self.chain_anchor
        if anchor is None or self._snap is None:
            return None
        return (
            distance(anchor, self._snap.point),
            direction_degrees(anchor, self._snap.point),
        )

    def snap_at(self, x: float, y: float) -> SnapResult:
        options = replace(self.snap_options, grid=max(0.0, self.grid))
        return resolve_snap(self.nodes, self.elements, (x, y), self._tolerance(), options)

    def place_point(self, x: float, y: float, snap: SnapResult | None = None) -> int:
        """Add the next point of the drawing chain, connecting it to the previous one.

        A single click is one undo step even though it may create both a node and a
        member, so the history group wraps the whole placement.
        """
        self.begin_history_group()
        try:
            tag = self._node_for_point(x, y, snap)
            if self._chain and self._chain[-1] != tag:
                self.add_member(self._chain[-1], tag)
            if not self._chain or self._chain[-1] != tag:
                self._chain.append(tag)
        finally:
            self.end_history_group()
        self._preview_point = None
        self._changed()
        self.draw_state_changed.emit()
        return tag

    def commit_entry(self, text: str) -> bool:
        """Place a point from a typed entry such as ``5<30``, ``@3,4`` or ``3,4``."""
        anchor = self.chain_anchor or (0.0, 0.0)
        heading = None
        if self._snap is not None and self.chain_anchor is not None:
            heading = direction_degrees(anchor, self._snap.point)
        point = parse_entry(text, anchor, heading)
        if point is None:
            return False
        self.place_point(*point)
        return True

    def end_chain(self) -> None:
        if not self._chain and self._preview_point is None:
            return
        self._chain.clear()
        self._preview_point = None
        self._redraw()
        self.draw_state_changed.emit()

    def _node_for_point(
        self, x: float, y: float, snap: SnapResult | None
    ) -> int:
        if snap is not None and snap.node_tag is not None:
            return snap.node_tag
        if snap is not None and snap.element_tag is not None and snap.position is not None:
            return self.add_member_station_node(snap.element_tag, snap.position)
        return self.add_node(x, y)

    def _tolerance(self) -> float:
        """Snap radius in model units, held constant in pixels while zooming."""
        zoom = abs(self.transform().m11()) or 1.0
        return self._SNAP_PIXELS / (self._DRAW_SCALE * zoom)

    def _model_point(self, scene_point: QPointF) -> tuple[float, float]:
        return (scene_point.x() / self._DRAW_SCALE, -scene_point.y() / self._DRAW_SCALE)

    def _scene_point(self, x: float, y: float) -> QPointF:
        return QPointF(x * self._DRAW_SCALE, -y * self._DRAW_SCALE)

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

    def transform_selected_nodes(
        self,
        operation: str,
        dx: float,
        dy: float,
        repeat: int = 1,
    ) -> int:
        """Move selected nodes, or create translated copies with new node tags."""
        if not self.selected_nodes or (dx == 0.0 and dy == 0.0):
            return 0
        selected = sorted(self.selected_nodes)
        if operation == "move":
            targets = {
                tag: (self.nodes[tag].x + dx, self.nodes[tag].y + dy) for tag in selected
            }
            occupied = {
                (round(node.x, 12), round(node.y, 12))
                for tag, node in self.nodes.items()
                if tag not in self.selected_nodes
            }
            if any((round(x, 12), round(y, 12)) in occupied for x, y in targets.values()):
                return 0
            self._record_history()
            for tag, (x, y) in targets.items():
                old = self.nodes[tag]
                self.nodes[tag] = Node(tag, x, y, old.z, old.ndf)
                self.embedded_nodes.pop(tag, None)
                self._attach_node_to_member(tag)
            self._changed()
            return len(selected)

        if operation != "copy":
            raise ValueError(f"Unknown node transform operation: {operation}")
        self.begin_history_group()
        created: set[int] = set()
        try:
            for step in range(1, max(1, repeat) + 1):
                for source_tag in selected:
                    source = self.nodes[source_tag]
                    before = set(self.nodes)
                    tag = self.add_node(source.x + dx * step, source.y + dy * step)
                    if tag in before:
                        continue
                    created.add(tag)
                    if source_tag in self.hinge_nodes:
                        self.hinge_nodes.add(tag)
        finally:
            self.end_history_group()
        self.selected_nodes = created
        self.selected_elements.clear()
        self._redraw()
        return len(created)

    def add_node(self, x: float, y: float) -> int:
        existing = self._nearest_node(x, y)
        if existing is not None:
            return existing
        self._record_history()
        tag = max(self.nodes, default=0) + 1
        self.nodes[tag] = Node(tag, x, y)
        self._attach_node_to_member(tag)
        self._changed()
        return tag

    def add_member(self, node_i: int, node_j: int) -> int | None:
        if node_i == node_j:
            return None
        if any(
            {element.node_i, element.node_j} == {node_i, node_j}
            for element in self.elements.values()
        ):
            return None
        self._record_history()
        tag = max(self.elements, default=0) + 1
        self.elements[tag] = Element(tag, node_i, node_j, "frame")
        for candidate_tag in self.nodes:
            if candidate_tag not in {node_i, node_j}:
                self._attach_node_to_member(candidate_tag, preferred_member=tag)
        self._changed()
        return tag

    def add_member_midpoint_node(self, element_tag: int) -> int:
        return self.add_member_station_node(element_tag, 0.5)

    def add_member_station_node(self, element_tag: int, position: float) -> int:
        position = max(1.0e-9, min(1.0 - 1.0e-9, position))
        for node_tag, (host_tag, existing_position) in self.embedded_nodes.items():
            if host_tag == element_tag and abs(existing_position - position) < 1.0e-9:
                return node_tag
        element = self.elements[element_tag]
        start = self.nodes[element.node_i]
        end = self.nodes[element.node_j]
        x = start.x + (end.x - start.x) * position
        y = start.y + (end.y - start.y) * position
        existing = self._nearest_node(x, y)
        if existing is not None:
            if self.embedded_nodes.get(existing) != (element_tag, position):
                self._record_history()
                self.embedded_nodes[existing] = (element_tag, position)
                self._changed()
            return existing
        tag = self.add_node(x, y)
        self.embedded_nodes[tag] = (element_tag, position)
        self._changed()
        return tag

    def _attach_node_to_member(
        self, node_tag: int, preferred_member: int | None = None
    ) -> bool:
        node = self.nodes[node_tag]
        ordered = sorted(self.elements)
        if preferred_member in self.elements:
            ordered.remove(preferred_member)
            ordered.insert(0, preferred_member)
        for element_tag in ordered:
            element = self.elements[element_tag]
            if node_tag in {element.node_i, element.node_j}:
                continue
            position = self._point_parameter(
                node, self.nodes[element.node_i], self.nodes[element.node_j]
            )
            if position is not None:
                self.embedded_nodes[node_tag] = (element_tag, position)
                return True
        return False

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
        analysis_elements: dict[int, Element] = {}
        analysis_loads: list[UniformElementLoad] = []
        next_tag = max(self.elements, default=0) + 1
        for element_tag, element in self.elements.items():
            stations = sorted(
                (
                    (position, node_tag)
                    for node_tag, (host_tag, position) in self.embedded_nodes.items()
                    if host_tag == element_tag
                ),
                key=lambda item: item[0],
            )
            chain = [element.node_i, *(node_tag for _, node_tag in stations), element.node_j]
            segment_tags = [element_tag]
            segment_tags.extend(range(next_tag, next_tag + max(0, len(chain) - 2)))
            next_tag += max(0, len(chain) - 2)
            for segment_tag, (node_i, node_j) in zip(
                segment_tags, pairwise(chain), strict=True
            ):
                analysis_elements[segment_tag] = Element(
                    segment_tag,
                    node_i,
                    node_j,
                    element.element_type,
                    dict(element.properties),
                )
                load = self.element_loads.get(element_tag)
                if load is not None:
                    analysis_loads.append(
                        UniformElementLoad(
                            segment_tag,
                            wx=load.wx,
                            wy=load.wy,
                            wz=load.wz,
                            pattern_tag=load.pattern_tag,
                            case_type=load.case_type,
                        )
                    )
        model = StructuralModel(
            nodes=dict(self.nodes),
            elements=self._apply_hinge_releases(analysis_elements),
            boundaries=list(self.boundaries.values()),
            nodal_loads=list(self.nodal_loads.values()),
            element_loads=analysis_loads,
        )
        model.metadata["hinge_nodes"] = ",".join(str(tag) for tag in sorted(self.hinge_nodes))
        model.metadata["logical_member_count"] = str(len(self.elements))
        model.metadata["embedded_nodes"] = ",".join(
            f"{node_tag}:{host_tag}:{position:g}"
            for node_tag, (host_tag, position) in sorted(self.embedded_nodes.items())
        )
        return model

    def _apply_hinge_releases(self, elements: dict[int, Element]) -> dict[int, Element]:
        """Turn node-level hinges into member end releases for the analysis model.

        A hinge releases the bending moment of every member end meeting at the node.
        When the node itself carries no rotational restraint one member must stay
        rigid, otherwise the joint spins freely and the stiffness matrix is singular.
        """
        releases = {tag: [False, False] for tag in elements}
        for node_tag in self.hinge_nodes:
            ends = sorted(
                (tag, end)
                for tag, element in elements.items()
                for end in (0, 1)
                if (element.node_i if end == 0 else element.node_j) == node_tag
            )
            if not ends:
                continue
            boundary = self.boundaries.get(node_tag)
            rotation_restrained = bool(
                boundary and len(boundary.restraints) > 2 and boundary.restraints[2]
            )
            if not rotation_restrained:
                ends = ends[1:]
            for tag, end in ends:
                releases[tag][end] = True
        return {
            tag: replace(
                element,
                moment_release_i=releases[tag][0],
                moment_release_j=releases[tag][1],
            )
            for tag, element in elements.items()
        }

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
            self.embedded_nodes.pop(tag, None)
        for tag in element_tags:
            hosted_nodes = [
                node_tag
                for node_tag, (host_tag, _) in self.embedded_nodes.items()
                if host_tag == tag
            ]
            for node_tag in hosted_nodes:
                self.nodes.pop(node_tag, None)
                self.boundaries.pop(node_tag, None)
                self.nodal_loads.pop(node_tag, None)
                self.hinge_nodes.discard(node_tag)
                self.embedded_nodes.pop(node_tag, None)
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
            "embedded_nodes": dict(self.embedded_nodes),
        }

    def _restore(self, snapshot: dict[str, object]) -> None:
        self.nodes = dict(snapshot["nodes"])
        self.elements = dict(snapshot["elements"])
        self.boundaries = dict(snapshot["boundaries"])
        self.nodal_loads = dict(snapshot["nodal_loads"])
        self.element_loads = dict(snapshot["element_loads"])
        self.hinge_nodes = set(snapshot["hinge_nodes"])
        self.embedded_nodes = dict(snapshot["embedded_nodes"])
        self.selected_nodes.clear()
        self.selected_elements.clear()
        self._selected = None
        self._member_start = None
        self._preview_point = None
        self._chain.clear()
        self._snap = None
        self._changed()
        self.draw_state_changed.emit()

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
            self.set_support(node, self.support_restraints)
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
                node = self.nodes[snapped]
                self._preview_point = QPointF(
                    node.x * self._DRAW_SCALE, -node.y * self._DRAW_SCALE
                )
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

    def _resolve_cursor(self, scene_point: QPointF, modifiers) -> SnapResult:
        x, y = self._model_point(scene_point)
        anchor = self.chain_anchor
        locked = self.ortho or bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if anchor is not None and locked:
            x, y = apply_ortho(anchor, (x, y), self.ortho_increment)
        return self.snap_at(x, y)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.end_chain()
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
        anchor_point = self.chain_anchor
        if anchor_point is not None and self._preview_point is not None:
            anchor = self._scene_point(*anchor_point)
            self.scene_model.addLine(
                anchor.x(),
                anchor.y(),
                self._preview_point.x(),
                self._preview_point.y(),
                QPen(QColor("#22c55e"), 2, Qt.PenStyle.DashLine),
            )
            measure = self.pending_length_and_angle()
            if measure is not None:
                readout = self.scene_model.addText(f"{measure[0]:.4g} m   {measure[1]:.1f}°")
                readout.setDefaultTextColor(QColor("#16a34a"))
                readout.setPos(self._preview_point + QPointF(12, -32))
        if self.mode == "draw" and self._snap is not None and self._snap.label:
            marker = self._scene_point(self._snap.x, self._snap.y)
            self.scene_model.addRect(
                marker.x() - 6, marker.y() - 6, 12, 12, QPen(QColor("#0f766e"), 2)
            )
            hint = self.scene_model.addText(self._snap.label)
            hint.setDefaultTextColor(QColor("#0f766e"))
            hint.setPos(marker + QPointF(10, 2))
        if self._drag_start is not None and self._drag_current is not None:
            crossing = self._drag_current.x() < self._drag_start.x()
            selection_color = QColor("#16a34a" if crossing else "#2563eb")
            self.scene_model.addRect(
                QRectF(self._drag_start, self._drag_current).normalized(),
                QPen(selection_color, 1, Qt.PenStyle.DashLine),
                QColor(selection_color.red(), selection_color.green(), selection_color.blue(), 35),
            )
        if self._preview_midpoint is not None:
            _, midpoint, position = self._preview_midpoint
            self.scene_model.addEllipse(
                midpoint.x() - 10,
                midpoint.y() - 10,
                20,
                20,
                QPen(QColor("#22c55e"), 2),
                QColor(34, 197, 94, 45),
            )
            station_label = "MID" if abs(position - 0.5) < 1.0e-9 else f"{position:.3g}L"
            label = self.scene_model.addText(station_label)
            label.setDefaultTextColor(QColor("#16a34a"))
            label.setPos(midpoint + QPointF(10, -25))

    def _nearest_node(self, x: float, y: float) -> int | None:
        return next(
            (
                tag
                for tag, node in self.nodes.items()
                if abs(node.x - x) < 1.0e-9 and abs(node.y - y) < 1.0e-9
            ),
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

    def _member_near_scene(self, point: QPointF, tolerance: float = 14.0) -> int | None:
        candidates: list[tuple[float, int]] = []
        for tag, element in self.elements.items():
            start_node = self.nodes[element.node_i]
            end_node = self.nodes[element.node_j]
            start = QPointF(
                start_node.x * self._DRAW_SCALE, -start_node.y * self._DRAW_SCALE
            )
            end = QPointF(end_node.x * self._DRAW_SCALE, -end_node.y * self._DRAW_SCALE)
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length_squared = dx * dx + dy * dy
            if length_squared == 0.0:
                continue
            station = max(
                0.0,
                min(1.0, ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / length_squared),
            )
            projected = QPointF(start.x() + station * dx, start.y() + station * dy)
            distance = (point.x() - projected.x()) ** 2 + (point.y() - projected.y()) ** 2
            candidates.append((distance, tag))
        distance, tag = min(candidates, default=(float("inf"), None))
        return tag if distance <= tolerance * tolerance else None

    def _member_station_near_scene(
        self, point: QPointF, tolerance: float = 14.0
    ) -> tuple[int, float, QPointF] | None:
        candidates: list[tuple[float, int, float, QPointF, float]] = []
        for tag, element in self.elements.items():
            a = self.nodes[element.node_i]
            b = self.nodes[element.node_j]
            start = QPointF(a.x * self._DRAW_SCALE, -a.y * self._DRAW_SCALE)
            end = QPointF(b.x * self._DRAW_SCALE, -b.y * self._DRAW_SCALE)
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length_squared = dx * dx + dy * dy
            if length_squared == 0.0:
                continue
            position = max(
                0.0,
                min(
                    1.0,
                    ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy)
                    / length_squared,
                ),
            )
            if abs(position - 0.5) * length_squared**0.5 <= tolerance:
                position = 0.5
            projected = QPointF(start.x() + position * dx, start.y() + position * dy)
            distance = (point.x() - projected.x()) ** 2 + (point.y() - projected.y()) ** 2
            candidates.append((distance, tag, position, projected, length_squared))
        distance, tag, position, projected, _ = min(
            candidates, default=(float("inf"), 0, 0.0, QPointF(), 0.0)
        )
        if distance > tolerance * tolerance or position in {0.0, 1.0}:
            return None
        return tag, position, projected

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
