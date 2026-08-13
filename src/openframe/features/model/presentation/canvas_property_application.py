"""Apply-to-selection methods for StaticsDrawingCanvas (support/load/section).

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

import math
from dataclasses import replace

from openframe.core.domain import BoundaryCondition, NodalLoad, UniformElementLoad

#: Every key apply_full_section_to_selection ever writes - cleared before
#: writing a fresh set so a shape switch (e.g. H/I Section, which has tw/tf,
#: back to Rectangle, which does not) can never leave a stale dimension key
#: behind from the member's previous section.
_SECTION_PROPERTY_KEYS = frozenset(
    {
        "E",
        "A",
        "I",
        "Iz",
        "J",
        "width",
        "height",
        "density",
        "section_shape",
        "section_source",
        "section_id",
        "material_id",
        "material_category",
        "material_grade",
    }
)


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

    def apply_full_section_to_selection(
        self,
        *,
        shape: str,
        source: str,
        dimensions: dict[str, float],
        area: float,
        iy: float,
        iz: float,
        j: float,
        elastic: float,
        density: float = 0.0,
        section_id: str | None = None,
        material_id: str | None = None,
        material_category: str | None = None,
        material_grade: str | None = None,
    ) -> None:
        """General section+material application - any of the seven supported
        shapes (Rectangle/Circle/H-I/Box/Pipe/Channel/Angle) or a fully
        user-defined section, Custom (computed via
        ``core.domain.section_properties``) or Database (read straight from
        the Master DB's ``SectionRecord``/``MaterialRecord``, already
        converted to this model's own unit system by the caller - this mixin
        never converts units itself, matching ``apply_section_to_selection``).

        ``element.properties`` keeps ``A``/``I`` as the exact keys every 2D
        solver already reads (``I`` is Iy in this app's established
        convention - see ``section_properties.py``'s module docstring). A
        Rectangle also gets ``width``/``height`` so the existing section
        preview widget keeps working unchanged; every other shape's
        dimensions are dropped (no solver reads them) rather than invented
        under a key that would look like it means something it does not.

        Unlike ``apply_section_to_selection``, this *replaces* every section-
        related key instead of merging - switching shape (or from a Database
        section back to Custom) must not leave a stale key from what the
        member carried before.
        """
        if not self.selected_elements:
            return
        self._record_history()
        new_properties: dict[str, float | str] = {
            "E": elastic,
            "A": area,
            "I": iy,
            "Iz": iz,
            "J": j,
            "density": density,
            "section_shape": shape,
            "section_source": source,
        }
        if shape == "Rectangle":
            new_properties["width"] = dimensions.get("b", 0.0)
            new_properties["height"] = dimensions.get("h", 0.0)
        if section_id is not None:
            new_properties["section_id"] = section_id
        if material_id is not None:
            new_properties["material_id"] = material_id
        if material_category is not None:
            new_properties["material_category"] = material_category
        if material_grade is not None:
            new_properties["material_grade"] = material_grade
        for element_tag in self.selected_elements:
            element = self.elements.get(element_tag)
            if element is None:
                continue
            retained = {
                key: value
                for key, value in element.properties.items()
                if key not in _SECTION_PROPERTY_KEYS and not key.startswith("dim_")
            }
            merged = {
                **retained,
                **new_properties,
                **{f"dim_{key}": value for key, value in dimensions.items()},
            }
            self.elements[element_tag] = replace(element, properties=merged)
        self._changed()

    def apply_uniform_load_to_selection(
        self,
        values: tuple[float, float] | tuple[float, float, float, float],
        *,
        coordinate_system: str = "local",
    ) -> None:
        """Apply a 2D member load in local or global coordinates.

        ``values`` is ``(qx, qy)`` for a plain uniform load, or
        ``(qx_i, qy_i, qx_j, qy_j)`` for a linearly-varying one. Local input
        is stored unchanged. Global X/Y input is resolved separately for each
        selected member, so one wind load can be applied to horizontal,
        vertical and diagonal members together without sharing the wrong
        local components.
        """
        if not self.selected_elements:
            return
        if coordinate_system not in {"local", "global"}:
            raise ValueError(f"Unsupported load coordinate system: {coordinate_system}")
        if coordinate_system == "global" and self.ndm != 2:
            raise ValueError("Global member-load conversion is currently supported in 2D only.")
        qx_i, qy_i = values[0], values[1]
        qx_j, qy_j = (
            (values[2], values[3]) if len(values) >= 4 else (qx_i, qy_i)
        )
        self._record_history()
        for element_tag in self.selected_elements:
            wx_i, wy_i, wx_j, wy_j = qx_i, qy_i, qx_j, qy_j
            if coordinate_system == "global":
                element = self.elements.get(element_tag)
                if element is None:
                    continue
                node_i = self.nodes[element.node_i]
                node_j = self.nodes[element.node_j]
                dx, dy = node_j.x - node_i.x, node_j.y - node_i.y
                length = math.hypot(dx, dy)
                if length <= 0.0:
                    continue
                cosine, sine = dx / length, dy / length
                wx_i, wy_i = self._global_to_local_load(
                    qx_i, qy_i, cosine, sine
                )
                wx_j, wy_j = self._global_to_local_load(
                    qx_j, qy_j, cosine, sine
                )
            self.element_loads[element_tag] = UniformElementLoad(
                element_tag, wx=wx_i, wy=wy_i, wx_j=wx_j, wy_j=wy_j
            )
        self._changed()

    @staticmethod
    def _global_to_local_load(
        qx: float, qy: float, cosine: float, sine: float
    ) -> tuple[float, float]:
        return (
            qx * cosine + qy * sine,
            -qx * sine + qy * cosine,
        )
