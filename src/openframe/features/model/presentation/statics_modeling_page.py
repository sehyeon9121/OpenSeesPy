"""Free-form 2D editor for textbook statics problems."""

import math
from dataclasses import replace
from itertools import pairwise

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
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
    LoadCaseKind,
    NodalLoad,
    Node,
    StructuralModel,
    UniformElementLoad,
    UnitSystem,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy
from openframe.features.model.drawing import (
    PlaneKind,
    SnapOptions,
    SnapResult,
    WorkPlane,
    apply_ortho,
    parse_entry,
    resolve_snap,
)
from openframe.features.model.drawing.coordinates import direction_degrees, distance
from openframe.features.results.presentation.result_viewport import ResultViewport


def _lerp(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * fraction


class StaticsDrawingCanvas(QGraphicsView):
    model_changed = Signal()
    draw_state_changed = Signal()
    selection_changed = Signal()
    escape_requested = Signal()
    _DRAW_SCALE = 40.0
    _SNAP_PIXELS = 14.0

    def __init__(self, parent: QWidget | None = None) -> None:
        self.scene_model = QGraphicsScene()
        super().__init__(self.scene_model, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSceneRect(-100_000, -100_000, 200_000, 200_000)
        self.nodes: dict[int, Node] = {}
        self.elements: dict[int, Element] = {}
        self.boundaries: dict[int, BoundaryCondition] = {}
        self.nodal_loads: dict[int, NodalLoad] = {}
        self.element_loads: dict[int, UniformElementLoad] = {}
        self.embedded_nodes: dict[int, tuple[int, float]] = {}
        self.mode = "select"
        # "frame" members carry moment/shear/axial; "truss" members are pinned at
        # both ends and carry axial force only. This governs every member drawn
        # from now on, not the members already on the canvas — matching how a
        # real truss/frame is a whole-model choice, not a per-click one.
        self.element_family = "frame"
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
        self.support_angle = 0.0
        self.pending_nodal_load = (0.0, -10.0, 0.0)
        self.pending_uniform_load = (0.0, -10.0)
        # Off by default: a determinate textbook problem almost never wants its
        # own member weight mixed into a hand-picked point load, and turning it
        # on requires each member to also carry a density (see _self_weight_local).
        self.include_self_weight = False
        self.snap_options = SnapOptions()
        self.ortho = False
        self.ortho_increment = 45.0
        self._chain: list[int] = []
        self._snap: SnapResult | None = None
        self._undo_stack: list[dict[str, object]] = []
        self._redo_stack: list[dict[str, object]] = []
        self._history_group_depth = 0
        self._history_group_snapshot: dict[str, object] | None = None
        # A plain 2D canvas is a 3D one whose only plane is the ground (identity
        # XY at 0): every coordinate a node ever gets is (u, v, 0), which is
        # exactly what this class always produced before it knew about planes.
        self.ndm = 2
        self.work_plane = WorkPlane()
        self.levels: list[WorkPlane] = [self.work_plane]

    # --- work planes (3D authoring) -----------------------------------------

    def enter_3d_mode(self) -> None:
        """Switch the canvas from a flat 2D sheet to a stack of work planes."""
        self.ndm = 3

    def add_level(self, offset: float, label: str, kind: PlaneKind = PlaneKind.XY) -> WorkPlane:
        plane = WorkPlane(kind, offset, label)
        self.levels.append(plane)
        return plane

    def set_active_plane(self, plane: WorkPlane) -> None:
        self.work_plane = plane
        self.clear_selection()
        self._changed()

    def extrude_selection_to_plane(self, target: WorkPlane) -> int:
        """Connect the selected nodes straight up (or across) to another plane.

        This is how a column between two storeys gets drawn: pick the base nodes
        on the current plan, extrude to the next level's plane, and a member
        appears between each node and its counterpart there. Clicking a point in
        empty 3D space has no single right answer, so free-form 3D authoring
        never asks for that — every point is placed on a plane, including this one.
        """
        if not self.selected_nodes:
            return 0
        self.begin_history_group()
        created_members = 0
        try:
            for tag in sorted(self.selected_nodes):
                u, v = self._uv(self.nodes[tag])
                target_tag = self._add_node_at(target.to_3d(u, v))
                if self.add_member(tag, target_tag) is not None:
                    created_members += 1
        finally:
            self.end_history_group()
        return created_members

    def _uv(self, node: Node) -> tuple[float, float]:
        """Project a node onto the active work plane's local 2D coordinates."""
        return self.work_plane.to_2d((node.x, node.y, node.z))

    def _on_plane(self, node: Node) -> bool:
        return self.work_plane.contains((node.x, node.y, node.z))

    def _plane_node_tags(self) -> set[int]:
        return {tag for tag, node in self.nodes.items() if self._on_plane(node)}

    def _plane_element_tags(self, plane_nodes: set[int] | None = None) -> set[int]:
        """Members fully on the active plane — both ends, not just one."""
        on_plane = self._plane_node_tags() if plane_nodes is None else plane_nodes
        return {
            tag
            for tag, element in self.elements.items()
            if element.node_i in on_plane and element.node_j in on_plane
        }

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
        """Plane-local point the next member starts from, if a chain is open."""
        node = self.nodes.get(self._chain[-1]) if self._chain else None
        return None if node is None else self._uv(node)

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
        """Resolve a cursor position against geometry on the active plane only.

        ``resolve_snap`` knows nothing about planes — it compares ``Node.x``/``.y``
        directly — so a node from another storey must never reach it. Passing a
        plane-projected, plane-filtered copy of the model keeps that boundary in
        one place instead of every caller having to remember it. In 2D mode the
        plane is the identity ground plane, so this is exactly ``self.nodes`` and
        ``self.elements`` unchanged.
        """
        options = replace(self.snap_options, grid=max(0.0, self.grid))
        plane_node_tags = self._plane_node_tags()
        plane_nodes = {tag: self._projected_node(self.nodes[tag]) for tag in plane_node_tags}
        plane_elements = {
            tag: self.elements[tag] for tag in self._plane_element_tags(plane_node_tags)
        }
        return resolve_snap(plane_nodes, plane_elements, (x, y), self._tolerance(), options)

    def place_point(self, x: float, y: float, snap: SnapResult | None = None) -> int:
        """Add the next point of the drawing chain, connecting it to the previous one.

        A single click is one undo step even though it may create both a node and a
        member, so the history group wraps the whole placement.
        """
        self.begin_history_group()
        try:
            tag = self._node_for_point(x, y, snap)
            return self._continue_chain(tag)
        finally:
            self.end_history_group()

    def continue_chain_to_node(self, tag: int) -> int:
        """Extend the current chain to an already-known node tag directly.

        Used when a point was resolved somewhere other than the active work
        plane's own (u, v) math — a 3D viewport click on an existing node, say,
        which may not even lie on the plane currently showing. Going through
        ``place_point``'s plane conversion there would reproduce the wrong point
        whenever the node isn't on that plane; this bypasses it entirely.
        """
        if tag not in self.nodes:
            return tag
        return self._continue_chain(tag)

    def _continue_chain(self, tag: int) -> int:
        self.begin_history_group()
        try:
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
        plane_nodes = self._plane_node_tags()
        self.selected_nodes = plane_nodes
        self.selected_elements = self._plane_element_tags(plane_nodes)
        self._selection_changed()

    def clear_selection(self) -> None:
        self.selected_nodes.clear()
        self.selected_elements.clear()
        self._selected = None
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._redraw()
        self.selection_changed.emit()

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

    def apply_support_to_selection(
        self, restraints: tuple[bool, ...], angle: float = 0.0
    ) -> None:
        """Assign a support, or remove it entirely when nothing is restrained."""
        if not self.selected_nodes:
            return
        self._record_history()
        for node_tag in self.selected_nodes:
            if any(restraints):
                self.boundaries[node_tag] = BoundaryCondition(node_tag, restraints, angle)
            else:
                self.boundaries.pop(node_tag, None)
        self._changed()

    def apply_nodal_load_to_selection(self, values: tuple[float, ...]) -> None:
        if not self.selected_nodes:
            return
        self._record_history()
        for node_tag in self.selected_nodes:
            self.nodal_loads[node_tag] = NodalLoad(node_tag, values)
        self._changed()

    def set_member_end_release(self, element_tag: int, end: str, released: bool) -> None:
        """Pin one end of a drawn member, independent of any node-level hinge.

        ``end`` is ``"i"`` for the end at ``node_i`` or ``"j"`` for ``node_j`` — the
        two ends a member always has, regardless of which node tags they land on.
        """
        element = self.elements.get(element_tag)
        if element is None or end not in {"i", "j"}:
            return
        self._record_history()
        self.elements[element_tag] = replace(
            element,
            moment_release_i=released if end == "i" else element.moment_release_i,
            moment_release_j=released if end == "j" else element.moment_release_j,
        )
        self._changed()

    def apply_section_to_selection(
        self, width: float, height: float, elastic: float, density: float = 0.0
    ) -> None:
        """Rectangular section (width x height) + elastic modulus, applied to
        every selected member — stored as A = width*height, I = width*height^3/12
        (the properties MaterialFreeStaticsSolver actually reads, per
        Element.properties["E"/"A"/"I"]) alongside the raw width/height/E so
        the property panel can re-populate its fields and its section preview
        when a member carrying one is re-selected. ``density`` (a unit
        *weight*, force/volume, matching every other force-based property
        here) is what ``_self_weight_local`` reads when "자중 포함" is on —
        left at 0 (the default), the member simply opts out of self-weight.
        """
        if not self.selected_elements:
            return
        area = width * height
        inertia = width * height**3 / 12.0
        self._record_history()
        for element_tag in self.selected_elements:
            element = self.elements.get(element_tag)
            if element is None:
                continue
            self.elements[element_tag] = replace(
                element,
                properties={
                    **element.properties,
                    "E": elastic,
                    "A": area,
                    "I": inertia,
                    "width": width,
                    "height": height,
                    "density": density,
                },
            )
        self._changed()

    def apply_uniform_load_to_selection(
        self, values: tuple[float, float] | tuple[float, float, float, float]
    ) -> None:
        """``values`` is (wx, wy) for a plain uniform load, or (wx_i, wy_i,
        wx_j, wy_j) for a linearly-varying (triangular/trapezoidal) one."""
        if not self.selected_elements:
            return
        wx, wy = values[0], values[1]
        wx_j, wy_j = (values[2], values[3]) if len(values) >= 4 else (wx, wy)
        self._record_history()
        for element_tag in self.selected_elements:
            self.element_loads[element_tag] = UniformElementLoad(
                element_tag, wx=wx, wy=wy, wx_j=wx_j, wy_j=wy_j
            )
        self._changed()

    def transform_selected_nodes(
        self,
        operation: str,
        dx: float,
        dy: float,
        repeat: int = 1,
    ) -> int:
        """Move selected nodes, or create translated copies with new node tags.

        ``dx``/``dy`` are offsets along the active work plane's local axes, not
        necessarily global X/Y — on an elevation plane, "dy" moves along Z.
        """
        if not self.selected_nodes or (dx == 0.0 and dy == 0.0):
            return 0
        selected = sorted(self.selected_nodes)
        if operation == "move":
            targets: dict[int, tuple[float, float, float]] = {}
            for tag in selected:
                u, v = self._uv(self.nodes[tag])
                targets[tag] = self.work_plane.to_3d(u + dx, v + dy)
            occupied = {
                (round(node.x, 12), round(node.y, 12), round(node.z, 12))
                for tag, node in self.nodes.items()
                if tag not in self.selected_nodes
            }
            if any(
                (round(x, 12), round(y, 12), round(z, 12)) in occupied
                for x, y, z in targets.values()
            ):
                return 0
            self._record_history()
            for tag, (x, y, z) in targets.items():
                old = self.nodes[tag]
                self.nodes[tag] = Node(tag, x, y, z, old.ndf)
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
                    source_u, source_v = self._uv(self.nodes[source_tag])
                    before = set(self.nodes)
                    tag = self.add_node(source_u + dx * step, source_v + dy * step)
                    if tag in before:
                        continue
                    created.add(tag)
                    if source_tag in self.hinge_nodes:
                        self.hinge_nodes.add(tag)
        finally:
            self.end_history_group()
        self.selected_nodes = created
        self.selected_elements.clear()
        self._selection_changed()
        return len(created)

    def mirror_selection(self, axis: str, value: float) -> int:
        """Mirror the selected nodes, and any selected member between them, across
        a vertical (``axis="x"``) or horizontal (``axis="y"``) line **within the
        active work plane** — the plane's local axes, not necessarily global X/Y.

        Existing points and duplicate members are reused through the ordinary
        coincidence checks in ``add_node``/``add_member``, so mirroring a half-gable
        frame across the line through its own apex reconnects at the apex instead
        of stacking a second node on top of it.
        """
        if not self.selected_nodes or axis not in {"x", "y"}:
            return 0
        self.begin_history_group()
        mapping: dict[int, int] = {}
        try:
            for tag in sorted(self.selected_nodes):
                u, v = self._uv(self.nodes[tag])
                mirrored = (2.0 * value - u, v) if axis == "x" else (u, 2.0 * value - v)
                mapping[tag] = self.add_node(*mirrored)
                if tag in self.hinge_nodes:
                    self.hinge_nodes.add(mapping[tag])
            for element in list(self.elements.values()):
                if element.node_i in mapping and element.node_j in mapping:
                    self.add_member(mapping[element.node_i], mapping[element.node_j])
        finally:
            self.end_history_group()
        self.selected_nodes = set(mapping.values())
        self.selected_elements.clear()
        self._selection_changed()
        return len(mapping)

    def array_copy_selection(self, dx: float, dy: float, count: int) -> int:
        """Repeat the selected nodes, and the members between them, along a step.

        This is what turning one truss panel into a run of ``count`` panels needs:
        the plain node copy only duplicates points, never the members joining them.
        """
        if not self.selected_nodes or count < 1:
            return 0
        self.begin_history_group()
        original_elements = list(self.elements.values())
        created_members = 0
        try:
            for step in range(1, count + 1):
                mapping: dict[int, int] = {}
                for tag in sorted(self.selected_nodes):
                    source_u, source_v = self._uv(self.nodes[tag])
                    mapping[tag] = self.add_node(source_u + dx * step, source_v + dy * step)
                    if tag in self.hinge_nodes:
                        self.hinge_nodes.add(mapping[tag])
                for element in original_elements:
                    if (
                        element.node_i in mapping
                        and element.node_j in mapping
                        and self.add_member(mapping[element.node_i], mapping[element.node_j])
                        is not None
                    ):
                        created_members += 1
        finally:
            self.end_history_group()
        self._redraw()
        return created_members

    def rotate_copy_selection(
        self, center_u: float, center_v: float, angle_degrees: float, count: int
    ) -> int:
        """Repeat the selected nodes, and the members between them, rotated by
        ``angle_degrees`` increments around ``(center_u, center_v)`` — the
        same step-and-repeat shape as ``array_copy_selection``, but stepping
        around a pivot instead of along a straight offset. This is what a
        radial fan of rafters or a segmented arch needs and a straight array
        copy cannot reach without the user pre-computing each copy's offset
        by hand.
        """
        if not self.selected_nodes or count < 1 or angle_degrees == 0.0:
            return 0
        self.begin_history_group()
        original_elements = list(self.elements.values())
        created_members = 0
        try:
            for step in range(1, count + 1):
                theta = math.radians(angle_degrees * step)
                cos_t, sin_t = math.cos(theta), math.sin(theta)
                mapping: dict[int, int] = {}
                for tag in sorted(self.selected_nodes):
                    source_u, source_v = self._uv(self.nodes[tag])
                    du, dv = source_u - center_u, source_v - center_v
                    rotated_u = center_u + du * cos_t - dv * sin_t
                    rotated_v = center_v + du * sin_t + dv * cos_t
                    mapping[tag] = self.add_node(rotated_u, rotated_v)
                    if tag in self.hinge_nodes:
                        self.hinge_nodes.add(mapping[tag])
                for element in original_elements:
                    if (
                        element.node_i in mapping
                        and element.node_j in mapping
                        and self.add_member(mapping[element.node_i], mapping[element.node_j])
                        is not None
                    ):
                        created_members += 1
        finally:
            self.end_history_group()
        self._redraw()
        return created_members

    def subdivide_member(self, element_tag: int, segments: int) -> list[int]:
        """Insert nodes splitting a member into ``segments`` equal-length pieces."""
        if element_tag not in self.elements or segments < 2:
            return []
        created: list[int] = []
        self.begin_history_group()
        try:
            for step in range(1, segments):
                created.append(self.add_member_station_node(element_tag, step / segments))
        finally:
            self.end_history_group()
        return created

    def add_node(self, x: float, y: float) -> int:
        """Add a node from a point on the active work plane (plane-local u, v).

        In 2D mode the active plane is always the identity ground plane, so
        ``(x, y)`` is the model point directly — unchanged from before this class
        knew about planes.
        """
        return self._add_node_at(self.work_plane.to_3d(x, y))

    def _add_node_at(self, point: tuple[float, float, float]) -> int:
        """Add a node at a true 3D model point, bypassing the active plane.

        Used where the target point is already known in model space — an
        embedded station on an existing member, a mirrored or arrayed copy — so
        it is placed exactly there regardless of which plane is being viewed.
        """
        existing = self._nearest_node_3d(point)
        if existing is not None:
            return existing
        self._record_history()
        tag = max(self.nodes, default=0) + 1
        self.nodes[tag] = Node(tag, *point)
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
        self.elements[tag] = Element(tag, node_i, node_j, self.element_family)
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
        point = (
            start.x + (end.x - start.x) * position,
            start.y + (end.y - start.y) * position,
            start.z + (end.z - start.z) * position,
        )
        existing = self._nearest_node_3d(point)
        if existing is not None:
            if self.embedded_nodes.get(existing) != (element_tag, position):
                self._record_history()
                self.embedded_nodes[existing] = (element_tag, position)
                self._changed()
            return existing
        tag = self._add_node_at(point)
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
        """Where ``point`` falls on segment ``start``-``end``, in true 3D.

        Colinearity is a real geometric relationship the current work plane has
        no say in — a node dropped mid-height on a column has to embed there
        whether you are looking at a floor plan or an elevation. The z terms are
        zero for every node a purely 2D canvas ever creates, so this reduces
        exactly to the old x/y-only formula in that case.
        """
        dx = end.x - start.x
        dy = end.y - start.y
        dz = end.z - start.z
        length_squared = dx * dx + dy * dy + dz * dz
        if length_squared <= 1.0e-18:
            return None
        parameter = (
            (point.x - start.x) * dx + (point.y - start.y) * dy + (point.z - start.z) * dz
        ) / length_squared
        if not 1.0e-9 < parameter < 1.0 - 1.0e-9:
            return None
        projected_x = start.x + parameter * dx
        projected_y = start.y + parameter * dy
        projected_z = start.z + parameter * dz
        tolerance = max(length_squared**0.5, 1.0) * 1.0e-8
        if (
            abs(point.x - projected_x) > tolerance
            or abs(point.y - projected_y) > tolerance
            or abs(point.z - projected_z) > tolerance
        ):
            return None
        return parameter

    def set_support(
        self, node_tag: int, restraints: tuple[bool, bool, bool], angle: float = 0.0
    ) -> None:
        self._record_history()
        self.boundaries[node_tag] = BoundaryCondition(node_tag, restraints, angle)
        self._changed()

    def set_nodal_load(self, node_tag: int, values: tuple[float, float, float]) -> None:
        self._record_history()
        self.nodal_loads[node_tag] = NodalLoad(node_tag, values)
        self._changed()

    def set_uniform_load(
        self, element_tag: int, values: tuple[float, float] | tuple[float, float, float, float]
    ) -> None:
        wx, wy = values[0], values[1]
        wx_j, wy_j = (values[2], values[3]) if len(values) >= 4 else (wx, wy)
        self._record_history()
        self.element_loads[element_tag] = UniformElementLoad(
            element_tag, wx=wx, wy=wy, wx_j=wx_j, wy_j=wy_j
        )
        self._changed()

    def _self_weight_local(self, element: Element) -> tuple[float, float] | None:
        """Self-weight of one member as a (wx, wy) uniform load in the
        member's own local axes - ``None`` if self-weight is off or the
        member is missing the (density, A) it needs.

        Weight always acts in the global -Y direction regardless of how the
        member is drawn, so the constant force-per-length magnitude
        ``density * A`` (density here is a unit *weight*, force/volume - the
        same force-based convention the rest of this app already uses for E,
        not a mass needing a separate g factor) has to be projected onto the
        member's own local x (axial) and y (transverse) axes: a horizontal
        member gets it entirely as wy (bending under its own weight, exactly
        like a plain vertical UDL), a vertical column gets it entirely as wx
        (pure self-weight compression, no bending), and anything in between
        is the same projection ``load_arrow_segments``/``eleLoad`` already
        use for any other local-axis load on a sloped member.
        """
        # 3D distributed loads aren't solved at all yet (see solver.py) - the
        # projection below is also a 2D in-plane one (along/normal, no z
        # component), so self-weight quietly does nothing in 3D rather than
        # feeding the solver a load it would reject anyway.
        if not self.include_self_weight or self.ndm != 2:
            return None
        try:
            density = float(element.properties["density"])
            area = float(element.properties["A"])
        except (KeyError, TypeError, ValueError):
            return None
        if density == 0.0 or area == 0.0:
            return None
        start = self.nodes[element.node_i]
        end = self.nodes[element.node_j]
        dx, dy = end.x - start.x, end.y - start.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0.0:
            return None
        weight_per_length = density * area
        # Global weight vector (0, -w) dotted with the local x axis (dx, dy)/L
        # and the local y axis (-dy, dx)/L - the same along/normal pair
        # load_arrow_segments and _draw_distributed_load_box already use.
        wx = -weight_per_length * dy / length
        wy = -weight_per_length * dx / length
        return wx, wy

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
            # Fraction (0..1) along the *original* drawn member of every node in the
            # chain, needed to interpolate a linearly-varying load correctly onto
            # each analysis segment below - a plain uniform load doesn't care, but
            # splitting a trapezoidal one at its actual wx/wy would otherwise copy
            # the whole member's i/j values onto every segment instead of each
            # segment's own local slice of the load.
            chain_fractions = [0.0, *(position for position, _ in stations), 1.0]
            segment_tags = [element_tag]
            segment_tags.extend(range(next_tag, next_tag + max(0, len(chain) - 2)))
            next_tag += max(0, len(chain) - 2)
            last_index = len(segment_tags) - 1
            # Self-weight is the same (wx, wy) at every point of the *original*
            # drawn member (density/A don't vary along it), computed once here
            # from the member's own endpoints rather than per segment.
            self_weight = self._self_weight_local(element)
            for index, (segment_tag, (node_i, node_j)) in enumerate(
                zip(segment_tags, pairwise(chain), strict=True)
            ):
                # A member the user split with an embedded node becomes several
                # analysis segments; only the outer edges of the chain can carry the
                # end release the user set on the original drawn member.
                analysis_elements[segment_tag] = Element(
                    segment_tag,
                    node_i,
                    node_j,
                    element.element_type,
                    dict(element.properties),
                    moment_release_i=element.moment_release_i if index == 0 else False,
                    moment_release_j=element.moment_release_j if index == last_index else False,
                )
                load = self.element_loads.get(element_tag)
                start_fraction = chain_fractions[index]
                end_fraction = chain_fractions[index + 1]
                wx0 = _lerp(load.wx, load.wx_j, start_fraction) if load else 0.0
                wy0 = _lerp(load.wy, load.wy_j, start_fraction) if load else 0.0
                wz0 = _lerp(load.wz, load.wz_j, start_fraction) if load else 0.0
                wx1 = _lerp(load.wx, load.wx_j, end_fraction) if load else 0.0
                wy1 = _lerp(load.wy, load.wy_j, end_fraction) if load else 0.0
                wz1 = _lerp(load.wz, load.wz_j, end_fraction) if load else 0.0
                if self_weight is not None:
                    # Uniform along the whole member, so it adds identically to
                    # both ends of every segment - no interpolation needed.
                    wx0 += self_weight[0]
                    wx1 += self_weight[0]
                    wy0 += self_weight[1]
                    wy1 += self_weight[1]
                if load is not None or self_weight is not None:
                    analysis_loads.append(
                        UniformElementLoad(
                            segment_tag,
                            wx=wx0,
                            wy=wy0,
                            wz=wz0,
                            wx_j=wx1,
                            wy_j=wy1,
                            wz_j=wz1,
                            pattern_tag=load.pattern_tag if load else None,
                            case_type=load.case_type if load else LoadCaseKind.UNCLASSIFIED,
                        )
                    )
        model = StructuralModel(
            ndm=self.ndm,
            ndf=3 if self.ndm == 2 else 6,
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
        Explicit per-member end releases set via ``set_member_end_release`` are
        combined with, never overwritten by, the node-level hinge.
        """
        releases = {
            tag: [element.moment_release_i, element.moment_release_j]
            for tag, element in elements.items()
        }
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
        self.selection_changed.emit()

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
        self.selection_changed.emit()

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
            self._select_in_rect(rectangle, crossing=current.x() < self._drag_start.x())
            self._drag_start = None
            self._drag_current = None
            self._selection_changed()
            return
        super().mouseReleaseEvent(event)

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

    def _changed(self) -> None:
        self._redraw()
        self.model_changed.emit()

    def _projected_node(self, node: Node) -> Node:
        """The node's position on the active plane, as a drawable (u, v, 0) node.

        Every scene-drawing helper only ever reads ``.x``/``.y``; feeding them this
        projection instead of the real node is what lets them stay plane-agnostic.
        In 2D mode the plane is the identity ground plane, so this is ``node``
        itself in every case that matters (z is always 0 already).
        """
        u, v = self._uv(node)
        return Node(node.tag, u, v, 0.0, node.ndf)

    def _redraw(self) -> None:
        self.scene_model.clear()
        scale = self._DRAW_SCALE
        plane_nodes = self._plane_node_tags()
        for tag in self._plane_element_tags(plane_nodes):
            element = self.elements[tag]
            a = self._projected_node(self.nodes[element.node_i])
            b = self._projected_node(self.nodes[element.node_j])
            selected = tag in self.selected_elements or self._selected == ("element", tag)
            item = self.scene_model.addLine(
                a.x * scale,
                -a.y * scale,
                b.x * scale,
                -b.y * scale,
                QPen(QColor("#ef4444" if selected else "#174ea6"), 4),
            )
            item.setData(0, ("element", tag))
            if element.moment_release_i:
                self._draw_end_release(a, b, scale)
            if element.moment_release_j:
                self._draw_end_release(b, a, scale)
            if tag in self.element_loads:
                self._draw_uniform_load(a, b, self.element_loads[tag], scale)
        for tag in plane_nodes:
            node = self._projected_node(self.nodes[tag])
            selected = tag in self.selected_nodes or self._selected == ("node", tag)
            if tag in self.hinge_nodes:
                # A hinge (절점) is drawn as the textbook symbol: an open ring
                # around the joint with a small pin dot at its centre, not just a
                # colour change on the same filled dot a rigid node (노드) uses —
                # the two must read as different symbols at a glance, not
                # different shades of the same one.
                accent = QColor("#ef4444" if selected else "#f97316")
                ring = QGraphicsEllipseItem(-9, -9, 18, 18)
                ring.setPos(node.x * scale, -node.y * scale)
                ring.setBrush(QColor("#fff7ed"))
                ring.setPen(QPen(accent, 3))
                ring.setData(0, ("node", tag))
                self.scene_model.addItem(ring)
                pin = QGraphicsEllipseItem(-3, -3, 6, 6)
                pin.setPos(node.x * scale, -node.y * scale)
                pin.setBrush(accent)
                pin.setPen(QPen(accent, 0))
                pin.setData(0, ("node", tag))
                self.scene_model.addItem(pin)
            else:
                item = QGraphicsEllipseItem(-6, -6, 12, 12)
                item.setPos(node.x * scale, -node.y * scale)
                item.setBrush(QColor("#dbeafe" if selected else "#174ea6"))
                item.setPen(QPen(QColor("#174ea6"), 2))
                item.setData(0, ("node", tag))
                self.scene_model.addItem(item)
            # A plain node ("N") is a rigid connection; a hinge is a "절점"
            # (joint) where rotation is released. The label says which one this
            # is at a glance, not just the marker shape/colour.
            label_text = f"절점{tag}" if tag in self.hinge_nodes else f"N{tag}"
            self.scene_model.addText(label_text).setPos(
                node.x * scale + 7, -node.y * scale - 22
            )
            if tag in self.boundaries:
                self._draw_support(node, self.boundaries[tag], scale)
            if tag in self.nodal_loads:
                self._draw_nodal_load(node, self.nodal_loads[tag].values, scale)
        if self._member_start in plane_nodes:
            node = self._projected_node(self.nodes[self._member_start])
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
                    target = self._projected_node(self.nodes[snapped])
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

    def _nearest_node_3d(self, point: tuple[float, float, float]) -> int | None:
        return next(
            (
                tag
                for tag, node in self.nodes.items()
                if abs(node.x - point[0]) < 1.0e-9
                and abs(node.y - point[1]) < 1.0e-9
                and abs(node.z - point[2]) < 1.0e-9
            ),
            None,
        )

    def _node_near_scene(self, point: QPointF, tolerance: float = 16.0) -> int | None:
        """Nearest node to a scene point, restricted to nodes on the active plane."""
        candidates = []
        for tag, node in self.nodes.items():
            if not self._on_plane(node):
                continue
            u, v = self._uv(node)
            candidates.append(
                (
                    (u * self._DRAW_SCALE - point.x()) ** 2
                    + (-v * self._DRAW_SCALE - point.y()) ** 2,
                    tag,
                )
            )
        distance, tag = min(candidates, default=(float("inf"), None))
        return tag if distance <= tolerance * tolerance else None

    def _member_near_scene(self, point: QPointF, tolerance: float = 14.0) -> int | None:
        candidates: list[tuple[float, int]] = []
        for tag in self._plane_element_tags():
            element = self.elements[tag]
            start_node = self.nodes[element.node_i]
            end_node = self.nodes[element.node_j]
            start_u, start_v = self._uv(start_node)
            end_u, end_v = self._uv(end_node)
            start = QPointF(start_u * self._DRAW_SCALE, -start_v * self._DRAW_SCALE)
            end = QPointF(end_u * self._DRAW_SCALE, -end_v * self._DRAW_SCALE)
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
        for tag in self._plane_element_tags():
            element = self.elements[tag]
            a = self.nodes[element.node_i]
            b = self.nodes[element.node_j]
            a_u, a_v = self._uv(a)
            b_u, b_v = self._uv(b)
            start = QPointF(a_u * self._DRAW_SCALE, -a_v * self._DRAW_SCALE)
            end = QPointF(b_u * self._DRAW_SCALE, -b_v * self._DRAW_SCALE)
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
        self._selection_changed()

    def _select_in_rect(self, rectangle: QRectF, *, crossing: bool) -> None:
        """Drag-select — restricted to what the active plane actually shows.

        Selecting something invisible (a node from another storey) would be a
        trap: it looks unselected but the next delete or support click would
        silently reach it anyway.
        """
        scale = self._DRAW_SCALE
        plane_nodes = self._plane_node_tags()
        if self.selection_filter in {"all", "nodes"}:
            for tag in plane_nodes:
                u, v = self._uv(self.nodes[tag])
                if rectangle.contains(QPointF(u * scale, -v * scale)):
                    self.selected_nodes.add(tag)
        if self.selection_filter in {"all", "elements"}:
            for tag in self._plane_element_tags(plane_nodes):
                element = self.elements[tag]
                a, b = self.nodes[element.node_i], self.nodes[element.node_j]
                a_u, a_v = self._uv(a)
                b_u, b_v = self._uv(b)
                start = QPointF(a_u * scale, -a_v * scale)
                end = QPointF(b_u * scale, -b_v * scale)
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
                    # QLineF.intersects() reports UnboundedIntersection whenever the
                    # two *infinite* lines would cross somewhere, even if that point
                    # is nowhere near either actual segment - checking only "!=
                    # NoIntersection" therefore matched almost every non-parallel
                    # member against almost every rectangle edge, selecting the
                    # entire model on any crossing-mode drag. BoundedIntersection is
                    # the one value that means the two finite segments actually cross.
                    intersects = any(
                        member_line.intersects(edge)[0]
                        == QLineF.IntersectionType.BoundedIntersection
                        for edge in edges
                    )
                if fully_inside or (crossing and intersects):
                    self.selected_elements.add(tag)

    def _draw_support(self, node: Node, boundary: BoundaryCondition, scale: float) -> None:
        """Draw the support glyph rotated to the boundary condition's incline angle.

        The glyph is built at the origin in an unrotated local frame — the same
        shape as before this method learned about angles — then the whole group is
        positioned and rotated once. Qt rotates clockwise for a positive angle in
        its y-down scene space, which is exactly the on-screen direction a
        counter-clockwise angle in model space (y-up) needs, so ``setRotation``
        takes the boundary's angle unchanged.
        """
        pen = QPen(QColor("#334155"), 2)
        group = QGraphicsItemGroup()
        normalized = tuple(boundary.restraints[:3])
        if normalized == (True, True, True):
            group.addToGroup(self._line_item(-14, 8, 14, 8, pen))
            for offset in (-12, -6, 0, 6, 12):
                group.addToGroup(self._line_item(offset, 8, offset - 5, 16, pen))
        elif normalized == (True, False, False):
            group.addToGroup(self._line_item(8, -12, 8, 12, pen))
            group.addToGroup(self._line_item(0, 0, 8, -10, pen))
            group.addToGroup(self._line_item(0, 0, 8, 10, pen))
            group.addToGroup(self._ellipse_item(10, -7, 4, 4, pen))
            group.addToGroup(self._ellipse_item(10, 3, 4, 4, pen))
        else:
            group.addToGroup(self._line_item(0, 0, -11, 17, pen))
            group.addToGroup(self._line_item(0, 0, 11, 17, pen))
            group.addToGroup(self._line_item(-11, 17, 11, 17, pen))
            if normalized == (False, True, False):
                group.addToGroup(self._ellipse_item(-8, 18, 5, 5, pen))
                group.addToGroup(self._ellipse_item(3, 18, 5, 5, pen))
        group.setPos(node.x * scale, -node.y * scale)
        group.setRotation(boundary.angle)
        self.scene_model.addItem(group)
        if boundary.is_inclined:
            label = self.scene_model.addText(f"{boundary.angle:g}°")
            label.setDefaultTextColor(QColor("#0f766e"))
            label.setPos(node.x * scale + 16, -node.y * scale + 14)

    @staticmethod
    def _line_item(x1: float, y1: float, x2: float, y2: float, pen: QPen) -> QGraphicsLineItem:
        item = QGraphicsLineItem(x1, y1, x2, y2)
        item.setPen(pen)
        return item

    @staticmethod
    def _ellipse_item(x: float, y: float, w: float, h: float, pen: QPen) -> QGraphicsEllipseItem:
        item = QGraphicsEllipseItem(x, y, w, h)
        item.setPen(pen)
        return item

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

    @staticmethod
    def load_arrow_segments(
        start: Node, end: Node, load: UniformElementLoad, reach: float
    ) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
        """Arrow tails and tips in model space, expressed in the member's local axes.

        A uniform load is defined along the member, so the arrows have to follow the
        member: on a sloped rafter they stand perpendicular to it, not straight down.

        A trapezoidal load (wy != wy_j, or wx != wx_j) additionally tapers each
        arrow's length to the interpolated w(x) at that arrow's own position
        (0.25..1.0 of ``reach``, never fully to zero so the light end stays
        visible), so a triangular/trapezoidal load visibly reads as one instead
        of looking exactly like a uniform load. A plain uniform load (wy == wy_j)
        reduces to the original fixed-length arrows unchanged, since every
        position then interpolates back to the same constant value.
        """
        dx = end.x - start.x
        dy = end.y - start.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0.0:
            return []
        along = (dx / length, dy / length)
        normal = (-along[1], along[0])
        peak_y = max(abs(load.wy), abs(load.wy_j))
        peak_x = max(abs(load.wx), abs(load.wx_j))
        trapezoid_x = load.wx != load.wx_j
        segments = []
        for fraction in (0.1, 0.3, 0.5, 0.7, 0.9):
            tip = (start.x + dx * fraction, start.y + dy * fraction)
            local_y = load.wy + (load.wy_j - load.wy) * fraction
            if local_y and peak_y:
                sign = -1.0 if local_y < 0 else 1.0
                local_reach = reach * (0.25 + 0.75 * abs(local_y) / peak_y)
                tail = (
                    tip[0] - normal[0] * local_reach * sign,
                    tip[1] - normal[1] * local_reach * sign,
                )
                label = (
                    f"qy {load.wy:g}~{load.wy_j:g}" if load.wy != load.wy_j else f"qy {load.wy:g}"
                )
                segments.append((tail, tip, label if fraction == 0.5 else ""))
            local_x = load.wx + (load.wx_j - load.wx) * fraction
            if local_x and peak_x and (fraction == 0.5 or trapezoid_x):
                sign = 1.0 if local_x > 0 else -1.0
                local_reach = reach * (0.25 + 0.75 * abs(local_x) / peak_x)
                tail = (
                    tip[0] - along[0] * local_reach * sign,
                    tip[1] - along[1] * local_reach * sign,
                )
                label = (
                    f"qx {load.wx:g}~{load.wx_j:g}" if trapezoid_x else f"qx {load.wx:g}"
                )
                segments.append((tail, tip, label if fraction == 0.5 else ""))
        return segments

    def _draw_end_release(self, end: Node, away_from: Node, scale: float) -> None:
        """Small open circle set back from the joint marking a pinned member end."""
        dx, dy = away_from.x - end.x, away_from.y - end.y
        length = max((dx * dx + dy * dy) ** 0.5, 1.0e-9)
        offset = 11.0
        x = end.x * scale + dx / length * offset
        y = -end.y * scale - dy / length * offset
        self.scene_model.addEllipse(
            x - 4, y - 4, 8, 8, QPen(QColor("#f97316"), 2), QColor("#fff7ed")
        )

    def _draw_uniform_load(
        self, start: Node, end: Node, load: UniformElementLoad, scale: float
    ) -> None:
        """The transverse (qy) component draws as a semi-transparent closed box -
        a trapezoid when wy != wy_j, a rectangle when uniform - instead of
        floating arrows with no connecting edge, which made it hard to tell at a
        glance whether the load actually spanned the whole member. The axial
        (qx) component, a much rarer case where a perpendicular "box" would read
        confusingly, keeps the arrow representation: ``load_arrow_segments``
        still generates both, so only the ones running along the member (not
        perpendicular to it) are drawn here.
        """
        if load.wy or load.wy_j:
            self._draw_distributed_load_box(start, end, load, scale)
        dx = end.x - start.x
        dy = end.y - start.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0.0:
            return
        normal = (-dy / length, dx / length)
        for tail, tip, text in self.load_arrow_segments(start, end, load, 32.0 / scale):
            vector = (tip[0] - tail[0], tip[1] - tail[1])
            perpendicular_component = vector[0] * normal[0] + vector[1] * normal[1]
            if abs(perpendicular_component) < 1.0e-9:  # runs along the member -> axial (qx)
                self._draw_arrow(
                    QPointF(tail[0] * scale, -tail[1] * scale),
                    QPointF(tip[0] * scale, -tip[1] * scale),
                    text,
                )

    def _draw_distributed_load_box(
        self, start: Node, end: Node, load: UniformElementLoad, scale: float
    ) -> None:
        dx = end.x - start.x
        dy = end.y - start.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0.0:
            return
        along = (dx / length, dy / length)
        normal = (-along[1], along[0])
        peak = max(abs(load.wy), abs(load.wy_j))
        if peak <= 0.0:
            return
        max_reach = 30.0 / scale

        def offset(x: float, y: float, w: float) -> tuple[float, float]:
            # Mirrors the sign convention load_arrow_segments already uses for
            # qy, so a downward load's box sits on the same side its arrows
            # used to: above the member, hatched down into it.
            if w == 0.0:
                return (x, y)
            sign = -1.0 if w < 0.0 else 1.0
            reach = max_reach * abs(w) / peak
            return (x - normal[0] * reach * sign, y - normal[1] * reach * sign)

        def to_scene(point: tuple[float, float]) -> QPointF:
            return QPointF(point[0] * scale, -point[1] * scale)

        inner_i, inner_j = (start.x, start.y), (end.x, end.y)
        outer_i = offset(start.x, start.y, load.wy)
        outer_j = offset(end.x, end.y, load.wy_j)

        color = QColor("#dc2626")
        fill = QColor(color)
        fill.setAlpha(55)
        pen = QPen(color, 1.4)
        self.scene_model.addPolygon(
            QPolygonF([to_scene(inner_i), to_scene(inner_j), to_scene(outer_j), to_scene(outer_i)]),
            pen,
            fill,
        )
        # Hatch lines from the outer edge back to the member so the load's
        # direction still reads clearly through the semi-transparent fill.
        for fraction in (0.15, 0.5, 0.85):
            member_point = (start.x + dx * fraction, start.y + dy * fraction)
            local_w = load.wy + (load.wy_j - load.wy) * fraction
            outer_point = offset(*member_point, local_w)
            scene_outer, scene_inner = to_scene(outer_point), to_scene(member_point)
            self.scene_model.addLine(
                scene_outer.x(), scene_outer.y(), scene_inner.x(), scene_inner.y(), QPen(color, 1.0)
            )

        label = f"qy {load.wy:g}~{load.wy_j:g}" if load.wy != load.wy_j else f"qy {load.wy:g}"
        midpoint = (start.x + dx * 0.5, start.y + dy * 0.5)
        midpoint_load = load.wy + (load.wy_j - load.wy) * 0.5
        label_point = to_scene(offset(*midpoint, midpoint_load))
        text_item = self.scene_model.addText(label)
        text_item.setDefaultTextColor(color)
        text_item.setPos(label_point + QPointF(4, -14))

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
        self.support_kind.addItem("수직 롤러", (True, False, False))
        self.support_kind.addItem("수평 롤러", (False, True, False))
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
