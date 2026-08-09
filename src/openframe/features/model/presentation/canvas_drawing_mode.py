"""Chain-drawing and snapping methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from dataclasses import replace

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsView

from openframe.features.model.drawing import SnapResult, parse_entry, resolve_snap
from openframe.features.model.drawing.coordinates import direction_degrees, distance


class _DrawingModeMixin:
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
