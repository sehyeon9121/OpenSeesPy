"""Node/member CRUD methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from openframe.core.domain import BoundaryCondition, Element, NodalLoad, Node, UniformElementLoad


class _GeometryMixin:
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
