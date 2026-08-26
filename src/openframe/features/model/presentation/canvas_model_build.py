"""build_model()/self-weight/delete methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from dataclasses import replace
from itertools import pairwise

from openframe.core.domain import (
    Element,
    LoadCaseKind,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    Node,
    NodalLoad,
    PointElementLoad,
    RigidDiaphragm,
    SelfWeightEntry,
    StructuralModel,
    UniformElementLoad,
)
from openframe.features.model.presentation.floor_tributary import convert_floor_entry

# The exact same vecxz-picking rule solver.py's _build uses to orient every 3D
# element's geomTransf - self-weight's local y/z projection below MUST use
# this same rule, or the load would be resolved against axes the solver
# itself never actually built the element with, landing self-weight in the
# wrong physical direction. Imported rather than duplicated so the two can
# never drift apart.
from openframe.features.analysis.statics.solver import _reference_vector


def _lerp(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * fraction


def _member_length(element: Element, nodes: dict, ndm: int) -> float:
    start = nodes[element.node_i]
    end = nodes[element.node_j]
    dz = (end.z - start.z) if ndm != 2 else 0.0
    return ((end.x - start.x) ** 2 + (end.y - start.y) ** 2 + dz**2) ** 0.5


def _position_fraction(position: float, position_unit: str, member_length: float) -> float:
    """A LoadEntry's own ``position``/``start_position``/``end_position`` as
    a 0..1 fraction of the *original* drawn member - matches
    ``chain_fractions``' own convention so the two can be compared directly.
    ``"length"`` (an absolute distance from node_i) needs the member's real
    length to convert; a zero-length member (should never happen for a real
    member) falls back to 0.0 rather than dividing by zero."""
    if position_unit != "length":
        return min(max(position, 0.0), 1.0)
    if member_length <= 0.0:
        return 0.0
    return min(max(position / member_length, 0.0), 1.0)


def _resolve_local_load_components(
    direction: str,
    coordinate_system: str,
    value: float,
    local_x: tuple[float, float, float],
    local_y: tuple[float, float, float],
    local_z: tuple[float, float, float],
) -> tuple[float, float, float]:
    """``value`` applied along ``direction`` (x/y/z), resolved into the
    member's own local axes as ``(n, py, pz)`` - ``n`` is axial (local x),
    ``py``/``pz`` are the two transverse local directions, matching
    OpenSeesPy's own ``-beamPoint`` argument order (``Py, xL, Pz, N``).
    ``coordinate_system == "local"`` means ``direction`` already names a
    local axis directly; ``"global"`` means it names a global axis, which
    gets projected onto local_x/y/z the same way
    ``apply_uniform_load_to_selection``'s 2D-only ``_global_to_local_load``
    does, just generalized to 3D via dot products against the same triad
    ``_local_axes``/the solver's own ``geomTransf`` use."""
    if coordinate_system == "local":
        return (
            value if direction == "x" else 0.0,
            value if direction == "y" else 0.0,
            value if direction == "z" else 0.0,
        )
    global_vector = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}.get(
        direction, (0.0, 0.0, 0.0)
    )
    scaled = tuple(component * value for component in global_vector)

    def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    return (_dot(scaled, local_x), _dot(scaled, local_y), _dot(scaled, local_z))


def _local_axes(
    element: Element, nodes: dict, ndm: int
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]] | None:
    """(local_x, local_y, local_z) unit-vector triad for ``element``, using
    the same vecxz-picking rule ``solver.py``'s ``_build`` uses to orient
    every 3D element's ``geomTransf`` - ``None`` for a zero-length member.
    Extracted out of ``_self_weight_local`` so any other feature projecting
    a global force onto a member's own local axes (see
    ``floor_tributary.py``) can never drift from what the solver itself
    actually built the element with. 2D returns ``local_z=(0,0,1)``, the
    plane normal, matching this mixin's existing 2D self-weight convention."""
    start = nodes[element.node_i]
    end = nodes[element.node_j]
    if ndm != 2:
        dx, dy, dz = end.x - start.x, end.y - start.y, end.z - start.z
        length = (dx * dx + dy * dy + dz * dz) ** 0.5
        if length <= 0.0:
            return None
        local_x = (dx / length, dy / length, dz / length)
        reference = _reference_vector(start, end)
        raw_y = (
            reference[1] * local_x[2] - reference[2] * local_x[1],
            reference[2] * local_x[0] - reference[0] * local_x[2],
            reference[0] * local_x[1] - reference[1] * local_x[0],
        )
        y_length = (raw_y[0] ** 2 + raw_y[1] ** 2 + raw_y[2] ** 2) ** 0.5 or 1.0
        local_y = tuple(component / y_length for component in raw_y)
        local_z = (
            local_x[1] * local_y[2] - local_x[2] * local_y[1],
            local_x[2] * local_y[0] - local_x[0] * local_y[2],
            local_x[0] * local_y[1] - local_x[1] * local_y[0],
        )
        return local_x, local_y, local_z
    dx, dy = end.x - start.x, end.y - start.y
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0.0:
        return None
    local_x = (dx / length, dy / length, 0.0)
    local_y = (-dy / length, dx / length, 0.0)
    return local_x, local_y, (0.0, 0.0, 1.0)


class _ModelBuildMixin:
    def _self_weight_local(self, element: Element) -> tuple[float, float, float] | None:
        """Self-weight of one member as a (wx, wy, wz) uniform load in the
        member's own local axes - ``None`` if self-weight is off or the
        member is missing the (density, A) it needs.

        Weight always acts straight down in the model's own vertical global
        axis - global -Y in 2D, global -Z in 3D (this mixin has no access to
        a page-level "gravity direction" setting to do otherwise, the same
        simplification 2D self-weight already made) - so the constant
        force-per-length magnitude ``density * A`` (density here is a unit
        *weight*, force/volume - the same force-based convention the rest of
        this app already uses for E, not a mass needing a separate g factor)
        has to be projected onto the member's own local axes: a horizontal
        member gets it entirely as transverse bending (exactly like a plain
        vertical UDL), a plumb column gets it entirely as axial compression,
        and anything in between is the same projection ``load_arrow_
        segments``/``eleLoad`` already use for any other local-axis load on a
        sloped member.

        In 3D, ``local_y``/``local_z`` come from the same right-hand
        ``reference x local_x`` / ``local_x x local_y`` construction OpenSees'
        own ``geomTransf`` uses internally (see ``_reference_vector``'s own
        docstring for the vecxz-picking rule and its known limitation for a
        member with a real, asymmetric section).
        """
        if not self.include_self_weight:
            return None
        try:
            density = float(element.properties["density"])
            area = float(element.properties["A"])
        except (KeyError, TypeError, ValueError):
            return None
        if density == 0.0 or area == 0.0:
            return None
        axes = _local_axes(element, self.nodes, self.ndm)
        if axes is None:
            return None
        local_x, local_y, local_z = axes
        weight_per_length = density * area
        if self.ndm != 2:
            # Global weight vector (0, 0, -w) dotted with each local axis -
            # only the axis's own Z-component survives that dot product.
            wx = -weight_per_length * local_x[2]
            wy = -weight_per_length * local_y[2]
            wz = -weight_per_length * local_z[2]
            return wx, wy, wz
        # Global weight vector (0, -w) dotted with the local x/y axes - the
        # same along/normal pair load_arrow_segments/_draw_distributed_load_box
        # already use.
        wx = -weight_per_length * local_x[1]
        wy = -weight_per_length * local_y[1]
        return wx, wy, 0.0

    def _case_self_weight_local(
        self, element: Element, entries: list
    ) -> tuple[float, float, float] | None:
        """Same (density * A) unit self-weight ``_self_weight_local`` already
        computes, but for the active load case's own ``SelfWeightEntry``
        items instead of the page-level ``include_self_weight`` toggle -
        each entry supplies its own global direction/magnitude
        (``factor_x/y/z``, not always straight down) rather than the fixed
        global -Y/-Z every ``include_self_weight`` member uses. Turning both
        on for the same member double-counts self-weight - that is two
        distinct features stacking, not a bug here to guard against.
        Multiple applicable entries (e.g. from more than one combination)
        sum onto each other, same as ``_activate_generated_case_for_analysis``
        already sums multiple entries of other kinds."""
        try:
            density = float(element.properties["density"])
            area = float(element.properties["A"])
        except (KeyError, TypeError, ValueError):
            return None
        if density == 0.0 or area == 0.0:
            return None
        applicable = [
            entry
            for entry in entries
            if entry.payload.apply_to_all or element.tag in entry.payload.target_elements
        ]
        if not applicable:
            return None
        axes = _local_axes(element, self.nodes, self.ndm)
        if axes is None:
            return None
        local_x, local_y, local_z = axes
        weight_per_length = density * area
        total_wx = total_wy = total_wz = 0.0
        for entry in applicable:
            payload: SelfWeightEntry = entry.payload
            global_vector = (
                payload.factor_x * weight_per_length,
                payload.factor_y * weight_per_length,
                payload.factor_z * weight_per_length,
            )
            total_wx += (
                global_vector[0] * local_x[0] + global_vector[1] * local_x[1] + global_vector[2] * local_x[2]
            )
            total_wy += (
                global_vector[0] * local_y[0] + global_vector[1] * local_y[1] + global_vector[2] * local_y[2]
            )
            if self.ndm != 2:
                total_wz += (
                    global_vector[0] * local_z[0]
                    + global_vector[1] * local_z[1]
                    + global_vector[2] * local_z[2]
                )
        return total_wx, total_wy, total_wz

    def build_model(self) -> StructuralModel:
        analysis_elements: dict[int, Element] = {}
        analysis_loads: list[UniformElementLoad] = []
        analysis_point_loads: list[PointElementLoad] = []
        analysis_nodal_loads: list[NodalLoad] = list(self.nodal_loads.values())
        extra_nodes: dict[int, Node] = {}
        next_tag = max(self.elements, default=0) + 1
        next_node_tag = max(self.nodes, default=0) + 1

        # Everything below reads the *active* load case's LoadEntry store
        # directly, live, at solve time - Apply on Direct Loads' Point/
        # Partial/Moment/Self Weight/Floor commands writes straight into
        # ``self.load_entries`` (``_commit_load3d_entry``), so whatever is in
        # the active case here is exactly what gets analyzed, no separate
        # "activate for analysis" step needed. Deliberately excludes nodal/
        # member_uniform/member_linear/floor's own combination-bridge path
        # (``_activate_generated_case_for_analysis``) - those already reach
        # ``self.nodal_loads``/``self.element_loads`` their own way and must
        # not be double-counted here.
        point_entries: dict[int, list] = {}
        partial_entries: dict[int, list] = {}
        moment_entries: dict[int, list] = {}
        self_weight_entries: list = []
        floor_entries: list = []
        for entry in self.load_entries.values():
            if entry.case_id != self.active_load_case_id or entry.hidden:
                continue
            if entry.kind == "member_point" and isinstance(entry.payload, MemberPointLoadEntry):
                point_entries.setdefault(entry.target[0], []).append(entry)
            elif entry.kind == "member_partial" and isinstance(entry.payload, MemberDistributedLoadEntry):
                partial_entries.setdefault(entry.target[0], []).append(entry)
            elif entry.kind == "member_moment" and isinstance(entry.payload, MemberPointLoadEntry):
                moment_entries.setdefault(entry.target[0], []).append(entry)
            elif entry.kind == "self_weight" and isinstance(entry.payload, SelfWeightEntry):
                self_weight_entries.append(entry)
            elif entry.kind == "floor":
                floor_entries.append(entry)

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
            # Self-weight is the same (wx, wy, wz) at every point of the
            # *original* drawn member (density/A don't vary along it),
            # computed once here from the member's own endpoints rather than
            # per segment.
            self_weight = self._self_weight_local(element)
            case_self_weight = self._case_self_weight_local(element, self_weight_entries)
            member_length = _member_length(element, self.nodes, self.ndm)
            axes = _local_axes(element, self.nodes, self.ndm)
            element_points = point_entries.get(element_tag, ())
            element_partials = partial_entries.get(element_tag, ())
            element_moments = list(moment_entries.get(element_tag, ()))
            for index, (segment_tag, (node_i, node_j)) in enumerate(
                zip(segment_tags, pairwise(chain), strict=True)
            ):
                start_fraction = chain_fractions[index]
                end_fraction = chain_fractions[index + 1]
                segment_span = end_fraction - start_fraction

                # A concentrated moment has no native OpenSeesPy eleLoad type
                # (confirmed against the installed openseespy) - it is applied
                # as a real nodal moment at a synthetic node inserted exactly
                # at its position, splitting this segment in two. Only the
                # first applicable moment per segment is honored (a rare
                # multi-moment-in-one-undivided-segment case is left for a
                # future pass rather than an open-ended split loop here). A
                # moment landing within tolerance of an *existing* chain node
                # (start_fraction) applies directly to that node instead of
                # splitting a zero-length sliver - see the end-of-member
                # fallback after this loop for the one node (chain[-1]) that
                # can never be a segment's start_fraction.
                split_fraction: float | None = None
                split_moment = None
                if axes is not None and segment_span > 0.0:
                    for moment_entry in list(element_moments):
                        payload = moment_entry.payload
                        position_fraction = _position_fraction(
                            payload.position, payload.position_unit, member_length
                        )
                        if abs(position_fraction - start_fraction) <= 1e-9:
                            self._apply_moment_nodal_load(
                                moment_entry, node_i, axes, analysis_nodal_loads
                            )
                            element_moments.remove(moment_entry)
                            continue
                        if split_fraction is not None:
                            continue
                        local_split = (position_fraction - start_fraction) / segment_span
                        if 0.0 < local_split < 1.0:
                            split_fraction = local_split
                            split_moment = (moment_entry, position_fraction)
                            element_moments.remove(moment_entry)

                # A member the user split with an embedded node becomes several
                # analysis segments; only the outer edges of the chain can carry the
                # end release the user set on the original drawn member.
                release_i = element.moment_release_i if index == 0 else False
                release_j = element.moment_release_j if index == last_index else False

                load = self.element_loads.get(element_tag)

                def _uniform_at(fraction: float) -> tuple[float, float, float]:
                    wx = _lerp(load.wx, load.wx_j, fraction) if load else 0.0
                    wy = _lerp(load.wy, load.wy_j, fraction) if load else 0.0
                    wz = _lerp(load.wz, load.wz_j, fraction) if load else 0.0
                    if self_weight is not None:
                        wx += self_weight[0]
                        wy += self_weight[1]
                        wz += self_weight[2]
                    if case_self_weight is not None:
                        wx += case_self_weight[0]
                        wy += case_self_weight[1]
                        wz += case_self_weight[2]
                    return wx, wy, wz

                def _append_uniform(tag: int, start: float, end: float) -> None:
                    wx0, wy0, wz0 = _uniform_at(start)
                    wx1, wy1, wz1 = _uniform_at(end)
                    if load is None and self_weight is None and case_self_weight is None:
                        return
                    analysis_loads.append(
                        UniformElementLoad(
                            tag,
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

                if split_fraction is None:
                    analysis_elements[segment_tag] = Element(
                        segment_tag,
                        node_i,
                        node_j,
                        element.element_type,
                        dict(element.properties),
                        moment_release_i=release_i,
                        moment_release_j=release_j,
                    )
                    _append_uniform(segment_tag, start_fraction, end_fraction)
                else:
                    start_node = self.nodes.get(node_i) or extra_nodes[node_i]
                    end_node = self.nodes.get(node_j) or extra_nodes[node_j]
                    mid_tag = next_node_tag
                    next_node_tag += 1
                    extra_nodes[mid_tag] = Node(
                        mid_tag,
                        start_node.x + (end_node.x - start_node.x) * split_fraction,
                        start_node.y + (end_node.y - start_node.y) * split_fraction,
                        start_node.z + (end_node.z - start_node.z) * split_fraction,
                        ndf=3 if self.ndm == 2 else 6,
                    )
                    second_tag = next_tag
                    next_tag += 1
                    mid_global_fraction = start_fraction + split_fraction * segment_span
                    analysis_elements[segment_tag] = Element(
                        segment_tag,
                        node_i,
                        mid_tag,
                        element.element_type,
                        dict(element.properties),
                        moment_release_i=release_i,
                        moment_release_j=False,
                    )
                    analysis_elements[second_tag] = Element(
                        second_tag,
                        mid_tag,
                        node_j,
                        element.element_type,
                        dict(element.properties),
                        moment_release_i=False,
                        moment_release_j=release_j,
                    )
                    _append_uniform(segment_tag, start_fraction, mid_global_fraction)
                    _append_uniform(second_tag, mid_global_fraction, end_fraction)

                    moment_entry, _split_position_fraction = split_moment
                    self._apply_moment_nodal_load(moment_entry, mid_tag, axes, analysis_nodal_loads)

            # The chain's very last node (element.node_j) can never be a
            # segment's own start_fraction, so a moment landing there never
            # matches the boundary check inside the loop above - handle it
            # once here instead of splitting a zero-length sliver off the
            # last segment.
            if axes is not None:
                for moment_entry in element_moments:
                    payload = moment_entry.payload
                    position_fraction = _position_fraction(
                        payload.position, payload.position_unit, member_length
                    )
                    if abs(position_fraction - 1.0) <= 1e-9:
                        self._apply_moment_nodal_load(moment_entry, chain[-1], axes, analysis_nodal_loads)
                    # Any other un-applied moment (axes is None case, or a
                    # position outside 0..1) is silently dropped - should not
                    # happen given _position_fraction already clamps to 0..1.

                if axes is None or segment_span <= 0.0:
                    continue

                for point_entry in element_points:
                    payload = point_entry.payload
                    position_fraction = _position_fraction(
                        payload.position, payload.position_unit, member_length
                    )
                    if not (start_fraction - 1e-9 <= position_fraction <= end_fraction + 1e-9):
                        continue
                    local_xL = min(max((position_fraction - start_fraction) / segment_span, 0.0), 1.0)
                    n, py, pz = _resolve_local_load_components(
                        payload.direction, payload.coordinate_system, payload.value, *axes
                    )
                    if split_fraction is None:
                        target_tag = segment_tag
                    elif local_xL <= split_fraction:
                        target_tag = segment_tag
                        local_xL = local_xL / split_fraction if split_fraction > 0.0 else 0.0
                    else:
                        target_tag = second_tag
                        remaining = 1.0 - split_fraction
                        local_xL = (local_xL - split_fraction) / remaining if remaining > 0.0 else 1.0
                    analysis_point_loads.append(
                        PointElementLoad(
                            target_tag,
                            position=local_xL,
                            py=py,
                            pz=pz,
                            n=n,
                            case_type=LoadCaseKind.OTHER,
                        )
                    )

                for partial_entry in element_partials:
                    payload = partial_entry.payload
                    if payload.start_value != payload.end_value:
                        # Linearly-varying partial-span loads are not yet
                        # supported (deferred - see plan) - only a genuinely
                        # constant partial load maps onto OpenSeesPy's native
                        # -beamUniform xL1/xL2 without sub-element splitting.
                        continue
                    load_xL1 = _position_fraction(
                        payload.start_position, payload.position_unit, member_length
                    )
                    load_xL2 = _position_fraction(
                        payload.end_position, payload.position_unit, member_length
                    )
                    if load_xL1 > load_xL2:
                        load_xL1, load_xL2 = load_xL2, load_xL1
                    n, py, pz = _resolve_local_load_components(
                        payload.direction, payload.coordinate_system, payload.start_value, *axes
                    )
                    sub_segments = (
                        [(segment_tag, start_fraction, end_fraction)]
                        if split_fraction is None
                        else [
                            (segment_tag, start_fraction, mid_global_fraction),
                            (second_tag, mid_global_fraction, end_fraction),
                        ]
                    )
                    for sub_tag, sub_start, sub_end in sub_segments:
                        overlap_start = max(load_xL1, sub_start)
                        overlap_end = min(load_xL2, sub_end)
                        if overlap_start >= overlap_end:
                            continue
                        sub_span = sub_end - sub_start
                        local_xL1 = (overlap_start - sub_start) / sub_span
                        local_xL2 = (overlap_end - sub_start) / sub_span
                        analysis_loads.append(
                            UniformElementLoad(
                                sub_tag,
                                wx=n,
                                wy=py,
                                wz=pz,
                                xL1=local_xL1,
                                xL2=local_xL2,
                                case_type=LoadCaseKind.OTHER,
                            )
                        )

        # Floor loads are a per-*original*-member (wx0,wy0,wz0,wx1,wy1,wz1)
        # contribution, keyed by the same element tags convert_floor_entry
        # always used (self.elements, never a segment tag) - applied onto
        # ``segment_tags[0]`` (always == element_tag, see above) without
        # further interpolation across embedded-node segments, matching the
        # exact precedent this replaces (the old combination-bridge's floor
        # branch in _activate_generated_case_for_analysis did the same).
        for floor_entry in floor_entries:
            for target_tag, values in convert_floor_entry(floor_entry, self.nodes, self.elements).items():
                if target_tag not in analysis_elements:
                    continue
                wx0, wy0, wz0, wx1, wy1, wz1 = values
                analysis_loads.append(
                    UniformElementLoad(
                        target_tag,
                        wx=wx0,
                        wy=wy0,
                        wz=wz0,
                        wx_j=wx1,
                        wy_j=wy1,
                        wz_j=wz1,
                        case_type=LoadCaseKind.OTHER,
                    )
                )

        model = StructuralModel(
            ndm=self.ndm,
            ndf=3 if self.ndm == 2 else 6,
            nodes={**self.nodes, **extra_nodes},
            elements=self._apply_hinge_releases(analysis_elements),
            boundaries=list(self.boundaries.values()),
            nodal_loads=analysis_nodal_loads,
            element_loads=analysis_loads,
            point_loads=analysis_point_loads,
            rigid_diaphragms=tuple(self._build_rigid_diaphragms()),
        )
        model.metadata["hinge_nodes"] = ",".join(str(tag) for tag in sorted(self.hinge_nodes))
        model.metadata["logical_member_count"] = str(len(self.elements))
        model.metadata["embedded_nodes"] = ",".join(
            f"{node_tag}:{host_tag}:{position:g}"
            for node_tag, (host_tag, position) in sorted(self.embedded_nodes.items())
        )
        return model

    def _build_rigid_diaphragms(self) -> list[RigidDiaphragm]:
        """One ``RigidDiaphragm`` per Story with its checkbox on - see
        ``core.domain.model.RigidDiaphragm`` for why the master is one of
        the story's own nodes (the lowest tag) rather than a synthetic
        centroid node. A story with fewer than 2 nodes at its elevation has
        nothing to tie together and is silently skipped, same as a Story
        Manager entry created before any node was drawn at that level."""
        if self.ndm != 3:
            return []
        diaphragms: list[RigidDiaphragm] = []
        for story in self.stories.values():
            if not story.rigid_diaphragm:
                continue
            node_tags = self.nodes_at_story(story.id)
            if len(node_tags) < 2:
                continue
            master = min(node_tags)
            slaves = tuple(tag for tag in node_tags if tag != master)
            diaphragms.append(RigidDiaphragm(perp_dirn=3, master_tag=master, slave_tags=slaves))
        return diaphragms

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
