"""build_model()/self-weight/delete methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from dataclasses import replace
from itertools import pairwise

from openframe.core.domain import Element, LoadCaseKind, StructuralModel, UniformElementLoad


def _lerp(start: float, end: float, fraction: float) -> float:
    return start + (end - start) * fraction


class _ModelBuildMixin:
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
