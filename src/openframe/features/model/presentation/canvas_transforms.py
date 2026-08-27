"""Move/copy/array/rotate/mirror/subdivide methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

import math
from dataclasses import replace

from openframe.core.domain import Node


class _TransformMixin:
    def _copy_member_between(
        self,
        source,
        node_i: int,
        node_j: int,
        *,
        copy_element_loads: bool,
    ) -> int | None:
        """Create a geometric copy without dropping its structural identity."""
        new_tag = self.add_member(node_i, node_j)
        if new_tag is None:
            return None
        self.elements[new_tag] = replace(
            source,
            tag=new_tag,
            node_i=node_i,
            node_j=node_j,
            properties=dict(source.properties),
        )
        if copy_element_loads and source.tag in self.element_loads:
            self.element_loads[new_tag] = replace(
                self.element_loads[source.tag], element_tag=new_tag
            )
        return new_tag

    def _copy_node_attributes(self, source_tag: int, target_tag: int) -> None:
        if source_tag in self.boundaries:
            self.boundaries[target_tag] = replace(
                self.boundaries[source_tag], node_tag=target_tag
            )
        if source_tag in self.nodal_loads:
            self.nodal_loads[target_tag] = replace(
                self.nodal_loads[source_tag], node_tag=target_tag
            )

    def _effective_transform_nodes(self) -> set[int]:
        """Nodes a move/copy/array/rotate/mirror operation should act on:
        whatever is directly selected, plus the endpoints of any selected
        *member* - so picking a member (MIDAS's "Element" selection mode)
        drags or duplicates both its ends together, the same as picking both
        of its endpoint nodes by hand."""
        implied = {
            node_tag
            for tag in self.selected_elements
            for node_tag in (self.elements[tag].node_i, self.elements[tag].node_j)
            if tag in self.elements
        }
        return set(self.selected_nodes) | implied

    def transform_selected_nodes(
        self,
        operation: str,
        dx: float,
        dy: float,
        repeat: int = 1,
        *,
        dz: float = 0.0,
        copy_node_attributes: bool = False,
        copy_element_loads: bool = False,
    ) -> int:
        """Move selected nodes (and any selected member's endpoints), or create
        translated copies with new node tags - and, for "copy", a new member
        wherever a *selected* member's own two endpoints both got copied.

        ``dx``/``dy`` are offsets along the active work plane's local axes, not
        necessarily global X/Y — on an elevation plane, "dy" moves along Z.
        ``dz`` is the offset along the plane's own normal (out-of-plane) axis -
        0.0 (the default) reproduces the old in-plane-only behaviour exactly.
        """
        effective_nodes = self._effective_transform_nodes()
        if not effective_nodes or (dx == 0.0 and dy == 0.0 and dz == 0.0):
            return 0
        selected = sorted(effective_nodes)
        if operation == "move":
            targets: dict[int, tuple[float, float, float]] = {}
            for tag in selected:
                u, v = self._uv(self.nodes[tag])
                targets[tag] = self._replace_uvw(self.nodes[tag], u + dx, v + dy, dz)
            occupied = {
                (round(node.x, 12), round(node.y, 12), round(node.z, 12))
                for tag, node in self.nodes.items()
                if tag not in effective_nodes
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
        created_elements: set[int] = set()
        # Captured once, up front - a target point that happens to land
        # exactly on an existing member's own line makes _add_node_at split
        # that member into two pieces (see its own docstring), and if the
        # split member is itself one of the ones being copied, re-fetching
        # it from self.elements by tag *after* that split would silently
        # hand back the wrong (truncated) piece instead of the original
        # member's real endpoints - exactly the case that made a member's
        # copy quietly vanish while its nodes still got copied fine.
        selected_element_snapshot = [
            (element_tag, self.elements[element_tag])
            for element_tag in self.selected_elements
            if element_tag in self.elements
        ]
        try:
            for step in range(1, max(1, repeat) + 1):
                mapping: dict[int, int] = {}
                for source_tag in selected:
                    source_u, source_v = self._uv(self.nodes[source_tag])
                    before = set(self.nodes)
                    target_point = self._replace_uvw(
                        self.nodes[source_tag],
                        source_u + dx * step,
                        source_v + dy * step,
                        dz * step,
                    )
                    tag = self._add_node_at(target_point)
                    mapping[source_tag] = tag
                    if tag in before:
                        continue
                    created.add(tag)
                    if source_tag in self.hinge_nodes:
                        self.hinge_nodes.add(tag)
                    if copy_node_attributes:
                        self._copy_node_attributes(source_tag, tag)
                # Only a *selected* member gets carried along - copying two nodes
                # that happen to be a member's endpoints must not invent one, or
                # a plain node-only copy (no member picked) would start growing
                # members nobody asked for.
                for _element_tag, element in selected_element_snapshot:
                    if element.node_i in mapping and element.node_j in mapping:
                        new_tag = self._copy_member_between(
                            element,
                            mapping[element.node_i],
                            mapping[element.node_j],
                            copy_element_loads=copy_element_loads,
                        )
                        if new_tag is not None:
                            created_elements.add(new_tag)
        finally:
            self.end_history_group()
        self.selected_nodes = created
        self.selected_elements = created_elements
        self._selection_changed()
        return len(created)

    def mirror_selection(
        self,
        axis: str,
        value: float,
        *,
        copy_node_attributes: bool = False,
        copy_element_loads: bool = False,
    ) -> int:
        """Mirror the selected nodes, and any selected member between them, across
        a vertical (``axis="x"``) or horizontal (``axis="y"``) line **within the
        active work plane** — the plane's local axes, not necessarily global X/Y.

        Existing points and duplicate members are reused through the ordinary
        coincidence checks in ``add_node``/``add_member``, so mirroring a half-gable
        frame across the line through its own apex reconnects at the apex instead
        of stacking a second node on top of it.
        """
        effective_nodes = self._effective_transform_nodes()
        if not effective_nodes or axis not in {"x", "y"}:
            return 0
        self.begin_history_group()
        mapping: dict[int, int] = {}
        try:
            for tag in sorted(effective_nodes):
                u, v = self._uv(self.nodes[tag])
                mirrored = (2.0 * value - u, v) if axis == "x" else (u, 2.0 * value - v)
                before = set(self.nodes)
                mapping[tag] = self._add_node_at(self._replace_uv(self.nodes[tag], *mirrored))
                if tag in self.hinge_nodes:
                    self.hinge_nodes.add(mapping[tag])
                if copy_node_attributes and mapping[tag] not in before:
                    self._copy_node_attributes(tag, mapping[tag])
            for element in list(self.elements.values()):
                if element.node_i in mapping and element.node_j in mapping:
                    self._copy_member_between(
                        element,
                        mapping[element.node_i],
                        mapping[element.node_j],
                        copy_element_loads=copy_element_loads,
                    )
        finally:
            self.end_history_group()
        self.selected_nodes = set(mapping.values())
        self.selected_elements.clear()
        self._selection_changed()
        return len(mapping)

    def array_copy_selection(
        self,
        dx: float,
        dy: float,
        count: int,
        *,
        dz: float = 0.0,
        copy_node_attributes: bool = False,
        copy_element_loads: bool = False,
    ) -> int:
        """Repeat the selected nodes, and the members between them, along a step.

        This is what turning one truss panel into a run of ``count`` panels needs:
        the plain node copy only duplicates points, never the members joining them.
        ``dz`` (default 0.0) steps along the active plane's normal axis too - e.g.
        repeating a whole storey's frame upward in Z.
        """
        effective_nodes = self._effective_transform_nodes()
        if not effective_nodes or count < 1:
            return 0
        self.begin_history_group()
        original_elements = list(self.elements.values())
        created_members = 0
        try:
            for step in range(1, count + 1):
                mapping: dict[int, int] = {}
                for tag in sorted(effective_nodes):
                    source_u, source_v = self._uv(self.nodes[tag])
                    before = set(self.nodes)
                    target_point = self._replace_uvw(
                        self.nodes[tag],
                        source_u + dx * step,
                        source_v + dy * step,
                        dz * step,
                    )
                    mapping[tag] = self._add_node_at(target_point)
                    if tag in self.hinge_nodes:
                        self.hinge_nodes.add(mapping[tag])
                    if copy_node_attributes and mapping[tag] not in before:
                        self._copy_node_attributes(tag, mapping[tag])
                for element in original_elements:
                    if (
                        element.node_i in mapping
                        and element.node_j in mapping
                        and self._copy_member_between(
                            element,
                            mapping[element.node_i],
                            mapping[element.node_j],
                            copy_element_loads=copy_element_loads,
                        )
                        is not None
                    ):
                        created_members += 1
        finally:
            self.end_history_group()
        self._redraw()
        return created_members

    def rotate_copy_selection(
        self,
        center_u: float,
        center_v: float,
        angle_degrees: float,
        count: int,
        *,
        dz: float = 0.0,
        copy_node_attributes: bool = False,
        copy_element_loads: bool = False,
    ) -> int:
        """Repeat the selected nodes, and the members between them, rotated by
        ``angle_degrees`` increments around ``(center_u, center_v)`` — the
        same step-and-repeat shape as ``array_copy_selection``, but stepping
        around a pivot instead of along a straight offset. This is what a
        radial fan of rafters or a segmented arch needs and a straight array
        copy cannot reach without the user pre-computing each copy's offset
        by hand. ``dz`` (default 0.0) additionally steps along the active
        plane's normal axis each repetition, e.g. for a helical/spiral stair.
        """
        effective_nodes = self._effective_transform_nodes()
        if not effective_nodes or count < 1 or (angle_degrees == 0.0 and dz == 0.0):
            return 0
        self.begin_history_group()
        original_elements = list(self.elements.values())
        created_members = 0
        try:
            for step in range(1, count + 1):
                theta = math.radians(angle_degrees * step)
                cos_t, sin_t = math.cos(theta), math.sin(theta)
                mapping: dict[int, int] = {}
                for tag in sorted(effective_nodes):
                    source_u, source_v = self._uv(self.nodes[tag])
                    du, dv = source_u - center_u, source_v - center_v
                    rotated_u = center_u + du * cos_t - dv * sin_t
                    rotated_v = center_v + du * sin_t + dv * cos_t
                    before = set(self.nodes)
                    target_point = self._replace_uvw(
                        self.nodes[tag], rotated_u, rotated_v, dz * step
                    )
                    mapping[tag] = self._add_node_at(target_point)
                    if tag in self.hinge_nodes:
                        self.hinge_nodes.add(mapping[tag])
                    if copy_node_attributes and mapping[tag] not in before:
                        self._copy_node_attributes(tag, mapping[tag])
                for element in original_elements:
                    if (
                        element.node_i in mapping
                        and element.node_j in mapping
                        and self._copy_member_between(
                            element,
                            mapping[element.node_i],
                            mapping[element.node_j],
                            copy_element_loads=copy_element_loads,
                        )
                        is not None
                    ):
                        created_members += 1
        finally:
            self.end_history_group()
        self._redraw()
        return created_members

    def subdivide_member(self, element_tag: int, segments: int) -> list[int]:
        """Insert nodes splitting a member into ``segments`` equal, independent
        pieces. Each station node lands on and splits whatever piece remains
        of the original span (see ``_insert_station_node``) — after the first
        split, ``element_tag`` itself only names the first (shortest) piece,
        so every later station has to be re-measured as a *local* fraction of
        the remaining tail, not the original element_tag again.
        """
        if element_tag not in self.elements or segments < 2:
            return []
        created: list[int] = []
        self.begin_history_group()
        try:
            remaining_tag = element_tag
            consumed_fraction = 0.0
            for step in range(1, segments):
                global_fraction = step / segments
                local_fraction = (global_fraction - consumed_fraction) / (1.0 - consumed_fraction)
                node, remaining_tag = self._insert_station_node(remaining_tag, local_fraction)
                created.append(node)
                consumed_fraction = global_fraction
        finally:
            self.end_history_group()
        return created
