"""Node/member CRUD methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from openframe.core.domain import BoundaryCondition, Element, NodalLoad, Node, UniformElementLoad
from openframe.features.model.presentation.canvas_model_build import _lerp


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

        Used where the target point is already known in model space — a
        station on an existing member, a mirrored or arrayed copy — so it is
        placed exactly there regardless of which plane is being viewed.

        A brand-new node landing exactly on an existing member's line is
        treated as a deliberate request for a real joint there — split the
        member into two independent elements immediately, rather than only
        marking an *embedded* pass-through point that stays part of one
        logical member until build_model() splits it purely for analysis.
        Without this, a member could only ever carry a single linear load
        ramp end to end, with no way to give each side of an inserted node
        its own independent load — exactly the case a textbook beam with a
        different distributed load on each span needs. This is deliberately
        narrower than ``add_member``'s own sweep over already-existing nodes
        when a *new* member is drawn through one of them (kept embedded on
        purpose — see ``test_collinear_node_is_auto_attached_without_
        splitting_the_visible_member``): here the node is what's new, so
        there is no question the user meant to add something at this exact
        point on the member, not just happened to draw across it.
        """
        existing = self._nearest_node_3d(point)
        if existing is not None:
            return existing
        self._record_history()
        tag = max(self.nodes, default=0) + 1
        self.nodes[tag] = Node(tag, *point)
        self._attach_node_to_member(tag)
        host = self.embedded_nodes.pop(tag, None)
        if host is not None:
            self._split_element_at(host[0], host[1], tag)
        self._changed()
        return tag

    def _split_element_at(self, element_tag: int, position: float, joint: int) -> tuple[int, int]:
        """Split ``element_tag`` into two independent elements meeting at the
        already-created ``joint`` node, ``position`` (0..1) along its
        original length. Returns (first_tag, second_tag); ``first_tag`` is
        always ``element_tag`` itself (the node_i side keeps the original
        tag), ``second_tag`` is freshly minted for the node_j side.

        Any existing load on the original member is split at the same
        fraction (the interpolated value at the joint becomes the shared
        boundary value), any releases stay on their original outer end (the
        new internal joint is a plain rigid connection unless the user
        explicitly releases it afterward via the usual N1/N2 쪽 핀 해제
        checkboxes), and any node already embedded further along the
        original span is reassigned to whichever new piece now actually
        contains it, at that piece's own local fraction.
        """
        element = self.elements[element_tag]
        load = self.element_loads.pop(element_tag, None)
        first_tag = element_tag
        second_tag = max(self.elements, default=0) + 1
        self.elements[first_tag] = Element(
            first_tag,
            element.node_i,
            joint,
            element.element_type,
            dict(element.properties),
            moment_release_i=element.moment_release_i,
            moment_release_j=False,
        )
        self.elements[second_tag] = Element(
            second_tag,
            joint,
            element.node_j,
            element.element_type,
            dict(element.properties),
            moment_release_i=False,
            moment_release_j=element.moment_release_j,
        )
        if load is not None:
            split_wx = _lerp(load.wx, load.wx_j, position)
            split_wy = _lerp(load.wy, load.wy_j, position)
            split_wz = _lerp(load.wz, load.wz_j, position)
            self.element_loads[first_tag] = UniformElementLoad(
                first_tag,
                wx=load.wx,
                wy=load.wy,
                wz=load.wz,
                wx_j=split_wx,
                wy_j=split_wy,
                wz_j=split_wz,
                pattern_tag=load.pattern_tag,
                case_type=load.case_type,
            )
            self.element_loads[second_tag] = UniformElementLoad(
                second_tag,
                wx=split_wx,
                wy=split_wy,
                wz=split_wz,
                wx_j=load.wx_j,
                wy_j=load.wy_j,
                wz_j=load.wz_j,
                pattern_tag=load.pattern_tag,
                case_type=load.case_type,
            )
        for node_tag, (host_tag, existing_position) in list(self.embedded_nodes.items()):
            if host_tag != element_tag or node_tag == joint:
                continue
            if existing_position < position:
                self.embedded_nodes[node_tag] = (first_tag, existing_position / position)
            else:
                self.embedded_nodes[node_tag] = (
                    second_tag,
                    (existing_position - position) / (1.0 - position),
                )
        if element_tag in self.selected_elements:
            self.selected_elements.discard(element_tag)
            self.selected_elements.update({first_tag, second_tag})
        return first_tag, second_tag

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
        """Place a node ``position`` (0..1) along ``element_tag`` — splitting
        it into two independent elements there (see ``_add_node_at``), so
        each side can carry its own load, end release and section.
        """
        node, _ = self._insert_station_node(element_tag, position)
        return node

    def _insert_station_node(self, element_tag: int, position: float) -> tuple[int, int]:
        """Like ``add_member_station_node``, but also returns whichever
        element now spans from the new node to the original element's far
        (node_j) end — the "tail" ``subdivide_member`` needs to keep
        splitting the correct remaining piece instead of re-measuring
        fractions against the whole original span every step.

        The actual split happens inside ``_add_node_at`` itself (any
        brand-new node landing on a member splits it); this just locates the
        result afterward instead of repeating that logic.
        """
        position = max(1.0e-9, min(1.0 - 1.0e-9, position))
        element = self.elements[element_tag]
        start = self.nodes[element.node_i]
        end = self.nodes[element.node_j]
        point = (
            start.x + (end.x - start.x) * position,
            start.y + (end.y - start.y) * position,
            start.z + (end.z - start.z) * position,
        )
        node = self._add_node_at(point)
        tail = next(
            (tag for tag, candidate in self.elements.items() if candidate.node_i == node),
            element_tag,
        )
        return node, tail

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
