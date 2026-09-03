"""Node/member CRUD methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

import math
from dataclasses import replace

from openframe.core.domain import BoundaryCondition, Element, NodalLoad, Node, UniformElementLoad
from openframe.features.model.presentation.canvas_model_build import _lerp

#: Matches _nearest_node_3d's own per-axis 1e-9 coincidence tolerance -
#: see _add_node_at's ``coord_index`` parameter.
_COORD_TOLERANCE = 1.0e-9


def _quantize_point(point: tuple[float, float, float]) -> tuple[int, int, int]:
    return (
        round(point[0] / _COORD_TOLERANCE),
        round(point[1] / _COORD_TOLERANCE),
        round(point[2] / _COORD_TOLERANCE),
    )


class _GeometryMixin:
    def add_node(self, x: float, y: float) -> int:
        """Add a node from a point on the active work plane (plane-local u, v).

        In 2D mode the active plane is always the identity ground plane, so
        ``(x, y)`` is the model point directly — unchanged from before this class
        knew about planes.
        """
        return self._add_node_at(self.work_plane.to_3d(x, y))

    def _add_node_at(
        self,
        point: tuple[float, float, float],
        *,
        coord_index: dict[tuple[int, int, int], int] | None = None,
    ) -> int:
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

        ``coord_index`` is an optional coordinate -> tag cache a caller
        making many calls in a row (e.g. transform_selected_nodes's "copy"
        loop) builds once and keeps reusing, in place of the default
        ``_nearest_node_3d`` duplicate check - a full O(existing nodes)
        linear scan every call, which turned copying a K-node structure into
        an O(K x nodes) scan and was a real contributor to the whole app
        going "Not Responding" on a large "copy a floor upward" transform.
        Omitted (the default) everywhere else; behavior there is unchanged.
        """
        if coord_index is not None:
            key = _quantize_point(point)
            existing = coord_index.get(key)
        else:
            existing = self._nearest_node_3d(point)
        if existing is not None:
            return existing
        self._record_history()
        tag = max(self.nodes, default=0) + 1
        self.nodes[tag] = Node(tag, *point)
        if coord_index is not None:
            coord_index[key] = tag
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

    def add_member(
        self,
        node_i: int,
        node_j: int,
        *,
        edge_index: set[frozenset[int]] | None = None,
        template: Element | None = None,
    ) -> int | None:
        """``edge_index`` is an optional cache of every existing member's
        ``frozenset({node_i, node_j})``, built once and reused across many
        calls (see ``transform_selected_nodes``'s "copy" loop) so the
        duplicate-member check below is an O(1) set lookup instead of an
        O(existing elements) scan repeated once per new member. Omitted
        (the default) everywhere else; behavior is unchanged there.

        ``template`` lets transform operations install the copied member's
        structural identity before intersection splitting runs. Applying it
        afterward would overwrite the first split piece with the unsplit
        endpoints and leave overlapping geometry at the new joint.
        """
        if node_i == node_j:
            return None
        pair = frozenset((node_i, node_j))
        if edge_index is not None:
            if pair in edge_index:
                return None
        elif any(
            {element.node_i, element.node_j} == pair for element in self.elements.values()
        ):
            return None
        self._record_history()
        tag = max(self.elements, default=0) + 1
        if template is None:
            self.elements[tag] = Element(
                tag, node_i, node_j, self.element_family, {"behavior": self.element_behavior}
            )
        else:
            self.elements[tag] = replace(
                template,
                tag=tag,
                node_i=node_i,
                node_j=node_j,
                properties=dict(template.properties),
            )
        if edge_index is not None:
            edge_index.add(pair)
        # Only the *new* member's own line can newly qualify a pre-existing
        # node for embedding here - every other node/member pair was already
        # resolved when each of them was created, so re-running the general
        # _attach_node_to_member() sweep (checks a node against every element
        # in the model, falling through past `preferred_member` to recheck
        # ones that never changed) turned every add_member() call into an
        # O(nodes x elements) scan. On a "copy a whole floor upward" transform
        # - hundreds of new members, each one re-scanning an already-large
        # model - that compounded into the multi-minute UI freeze reported as
        # "복잡한 구조물을 위로 복사하면 아예 응답없음". A direct check
        # against just (node_i, node_j) is O(nodes) per call instead, and
        # (as a side effect) no longer risks silently re-embedding an
        # unrelated node onto a *different*, coincidentally-collinear member
        # it already belonged to just because this new member happened to
        # sort earlier by tag.
        start = self.nodes[node_i]
        end = self.nodes[node_j]
        for candidate_tag, candidate_node in self.nodes.items():
            if candidate_tag in pair:
                continue
            position = self._point_parameter(candidate_node, start, end)
            if position is not None:
                self.embedded_nodes[candidate_tag] = (tag, position)
        self._split_crossings_for(tag)
        self._changed()
        return tag

    def _split_crossings_for(self, new_tag: int) -> None:
        """Split ``new_tag`` and any existing member it crosses in free
        space (no shared endpoint) at their true 3D geometric intersection —
        two members drawn to cross, like X-bracing, are meant to transfer
        force at that point, not silently pass through each other.

        Only a proper *interior* crossing counts (strictly between both
        segments' endpoints); a member merely touching an existing node is
        already handled by the ``_attach_node_to_member`` sweep above, and
        collinear/parallel members have no single crossing point to speak
        of. In 3D, the closest points on both segments must coincide within
        the same coordinate tolerance used for duplicate nodes, so members
        that overlap only in the current screen projection remain separate.
        """
        current = new_tag
        while True:
            element = self.elements[current]
            a = self.nodes[element.node_i]
            b = self.nodes[element.node_j]
            best: tuple[float, int, float, tuple[float, float, float]] | None = None
            for other_tag in sorted(self.elements):
                if other_tag == current:
                    continue
                other = self.elements[other_tag]
                if {other.node_i, other.node_j} & {element.node_i, element.node_j}:
                    continue
                c = self.nodes[other.node_i]
                d = self.nodes[other.node_j]
                if not self._segment_bounds_overlap(a, b, c, d):
                    continue
                hit = self._segment_crossing(
                    a, b, c, d
                )
                if hit is None:
                    continue
                t_new, t_other, point = hit
                if best is None or t_new < best[0]:
                    best = (t_new, other_tag, t_other, point)
            if best is None:
                return
            t_new, other_tag, t_other, point = best
            joint = self._nearest_node_3d(point)
            if joint is None:
                joint = max(self.nodes, default=0) + 1
                self.nodes[joint] = Node(joint, *point)
            self.embedded_nodes.pop(joint, None)
            _, current = self._split_element_at(current, t_new, joint)
            self._split_element_at(other_tag, t_other, joint)

    @staticmethod
    def _segment_bounds_overlap(a: Node, b: Node, c: Node, d: Node) -> bool:
        """Cheap broad-phase rejection before the true 3D intersection test."""
        tolerance = _COORD_TOLERANCE
        return not (
            max(a.x, b.x) + tolerance < min(c.x, d.x)
            or max(c.x, d.x) + tolerance < min(a.x, b.x)
            or max(a.y, b.y) + tolerance < min(c.y, d.y)
            or max(c.y, d.y) + tolerance < min(a.y, b.y)
            or max(a.z, b.z) + tolerance < min(c.z, d.z)
            or max(c.z, d.z) + tolerance < min(a.z, b.z)
        )

    @staticmethod
    def _segment_crossing(
        a: Node, b: Node, c: Node, d: Node
    ) -> tuple[float, float, tuple[float, float, float]] | None:
        """Return one proper interior intersection of two true 3D segments."""
        first = (b.x - a.x, b.y - a.y, b.z - a.z)
        second = (d.x - c.x, d.y - c.y, d.z - c.z)
        first_length_squared = sum(component * component for component in first)
        second_length_squared = sum(component * component for component in second)
        if first_length_squared <= 1.0e-18 or second_length_squared <= 1.0e-18:
            return None

        def cross(
            left: tuple[float, float, float], right: tuple[float, float, float]
        ) -> tuple[float, float, float]:
            return (
                left[1] * right[2] - left[2] * right[1],
                left[2] * right[0] - left[0] * right[2],
                left[0] * right[1] - left[1] * right[0],
            )

        def dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
            return sum(left[index] * right[index] for index in range(3))

        normal = cross(first, second)
        denominator = dot(normal, normal)
        if denominator <= 1.0e-24 * first_length_squared * second_length_squared:
            return None

        offset = (c.x - a.x, c.y - a.y, c.z - a.z)
        t = dot(cross(offset, second), normal) / denominator
        u = dot(cross(offset, first), normal) / denominator
        eps = 1.0e-6
        if not (eps < t < 1.0 - eps and eps < u < 1.0 - eps):
            return None

        first_point = tuple(
            start + t * delta for start, delta in zip((a.x, a.y, a.z), first, strict=True)
        )
        second_point = tuple(
            start + u * delta for start, delta in zip((c.x, c.y, c.z), second, strict=True)
        )
        coordinate_scale = max(
            1.0,
            *(abs(value) for node in (a, b, c, d) for value in (node.x, node.y, node.z)),
        )
        tolerance = max(_COORD_TOLERANCE, 16.0 * math.ulp(coordinate_scale))
        if math.dist(first_point, second_point) > tolerance:
            return None

        point = tuple(
            (first_point[index] + second_point[index]) / 2.0 for index in range(3)
        )
        return t, u, point

    def add_arch(
        self, start_x: float, start_y: float, span: float, rise: float, segments: int
    ) -> tuple[int, ...]:
        """A circular arch from just its span endpoints and rise, as
        ``segments`` straight facets — most textbook arch problems keep the
        same rise/shape (curvature) and only vary the span, so the whole
        job is these four numbers, not a radius the user would otherwise
        have to compute by hand.

        The result is nothing but ordinary ``add_node``/``add_member`` calls
        along the arc, so every other tool (지점/노드 유형/부재/하중, and
        노드 분할 for adding still more nodes along one straight facet)
        already works on it without any special case - an arch is just a
        frame whose nodes happen to lie on a circle.

        ``rise`` is measured from the chord (the straight line between the
        two span endpoints, both at ``start_y``) to the arc's highest point
        at midspan - the standard circular-segment construction: a circle
        of radius ``R = (half_span² + rise²) / (2·rise)`` through both
        endpoints and the midspan crown, centred on the perpendicular
        bisector of the chord.
        """
        if span <= 0.0 or segments < 1:
            return ()
        half_span = span / 2.0
        if rise <= 0.0:
            # A degenerate/non-positive rise has no circle to speak of
            # (division by zero below) - fall back to a straight chord of
            # evenly spaced points rather than reject the request outright.
            points = [(start_x + span * i / segments, start_y) for i in range(segments + 1)]
        else:
            radius = (half_span**2 + rise**2) / (2.0 * rise)
            center_x = start_x + half_span
            center_y = start_y + rise - radius
            theta0 = math.atan2(start_y - center_y, start_x - center_x)
            theta1 = math.atan2(start_y - center_y, start_x + span - center_x)
            points = [
                (
                    center_x + radius * math.cos(theta0 + (theta1 - theta0) * i / segments),
                    center_y + radius * math.sin(theta0 + (theta1 - theta0) * i / segments),
                )
                for i in range(segments + 1)
            ]
        self.begin_history_group()
        created: list[int] = []
        try:
            for x, y in points:
                created.append(self.add_node(x, y))
            for node_i, node_j in zip(created, created[1:]):
                self.add_member(node_i, node_j)
        finally:
            self.end_history_group()
        self.selected_nodes = set(created)
        self.selected_elements.clear()
        self._selection_changed()
        return tuple(created)

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
        """Embed ``node_tag`` onto whichever member's line it geometrically
        sits on, if any - ``preferred_member`` (when given) is checked
        first, purely so a node landing on the member that was *just*
        created finds it without waiting to reach it in iteration order.

        Iterates ``self.elements`` in its own (insertion, i.e. ascending-tag
        for any element never deleted and re-added) order rather than
        ``sorted(self.elements)`` - re-sorting every element tag on every
        single new-node/new-member call turned into real, measurable cost
        once a "copy a whole floor" transform started calling this hundreds
        or thousands of times in a row on an already-large model.
        """
        node = self.nodes[node_tag]
        if preferred_member is not None and preferred_member in self.elements:
            element = self.elements[preferred_member]
            if node_tag not in {element.node_i, element.node_j}:
                position = self._point_parameter(
                    node, self.nodes[element.node_i], self.nodes[element.node_j]
                )
                if position is not None:
                    self.embedded_nodes[node_tag] = (preferred_member, position)
                    return True
        for element_tag, element in self.elements.items():
            if element_tag == preferred_member or node_tag in {element.node_i, element.node_j}:
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

    def remove_support(self, node_tag: int) -> None:
        """Clear a node's boundary condition without deleting the node
        itself - unlike ``delete_selected``, which drops the node (and every
        member it touches) along with its boundary."""
        if node_tag not in self.boundaries:
            return
        self._record_history()
        self.boundaries.pop(node_tag, None)
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
