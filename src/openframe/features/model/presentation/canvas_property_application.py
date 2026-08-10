"""Apply-to-selection methods for StaticsDrawingCanvas (support/load/section).

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from dataclasses import replace

from openframe.core.domain import BoundaryCondition, NodalLoad, UniformElementLoad


class _PropertyApplicationMixin:
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
        self.set_pending_load_preview(None)
        self._changed()

    def set_pending_load_preview(self, values: tuple[float, ...] | None) -> None:
        """A dashed preview of the load bar's *current field values*, shown at
        the selected node(s) before 적용 is clicked — so typing a magnitude
        and angle (or Fx/Fy directly) shows the arrow immediately instead of
        only after committing, letting the direction be checked/corrected
        before it is actually saved. ``None`` (or every component being 0,
        or nothing selected) clears it. This never touches ``nodal_loads``
        itself — only ``apply_nodal_load_to_selection`` does that.
        """
        if not values or not any(values) or not self.selected_nodes:
            if self._pending_load_preview is None:
                return
            self._pending_load_preview = None
        else:
            self._pending_load_preview = (frozenset(self.selected_nodes), values)
        self._redraw()

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
