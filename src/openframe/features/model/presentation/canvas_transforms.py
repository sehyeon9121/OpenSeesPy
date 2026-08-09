"""Move/copy/array/rotate/mirror/subdivide methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

import math

from openframe.core.domain import Node


class _TransformMixin:
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
