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
        "Iy",
        "Iz",
        "J",
        "G",
        "width",
        "height",
        "density",
        "section_shape",
        "section_source",
        "section_id",
        "material_id",
        "material_category",
        "material_grade",
        "Fy",
        "StrainHardeningRatio",
        "Zy",
        "Zz",
    }
)

#: Default Poisson's ratio used to derive a shear modulus (G = E / (2*(1+v)))
#: when the caller does not supply one - close enough for steel (~0.3) to be a
#: reasonable placeholder. Public (not module-private) because
#: ``SectionMaterialPanel`` also needs it as the initial value of its own
#: Poisson's-ratio field and as the fallback when reversing G back to v for a
#: re-selected member that predates that field - both must agree with this
#: module's own fallback, or a member never explicitly given a v would show a
#: different value than what actually got solved.
DEFAULT_POISSON_RATIO = 0.3


class _PropertyApplicationMixin:
    def apply_support_to_selection(
        self,
        restraints: tuple[bool, ...],
        angle: float = 0.0,
        spring_stiffnesses: tuple[float | None, ...] = (),
        angle_axis: str = "z",
    ) -> None:
        """Assign a support, or remove it entirely when nothing is restrained
        and no DOF is sprung either."""
        if not self.selected_nodes:
            return
        self._record_history()
        for node_tag in self.selected_nodes:
            if any(restraints) or any(spring_stiffnesses):
                self.boundaries[node_tag] = BoundaryCondition(
                    node_tag, restraints, angle, spring_stiffnesses, angle_axis
                )
            else:
                self.boundaries.pop(node_tag, None)
        self._changed()

    def apply_nodal_load_to_selection(
        self, values: tuple[float, ...], *, mode: str = "replace"
    ) -> None:
        """``mode`` mirrors MIDAS' Add/Replace/Delete Options group:
        "replace" (default, the only behaviour this ever had) overwrites
        whatever load tag already carries; "add" sums ``values`` onto it
        component-wise instead; "delete" drops the tag's load entirely and
        ignores ``values``. ``values`` itself is never mutated in the loop -
        each node computes its own ``applied`` from its own prior value, so
        a multi-node "add" selection never double-counts one node's sum onto
        the next."""
        if not self.selected_nodes:
            return
        self._record_history()
        for node_tag in self.selected_nodes:
            if mode == "delete":
                self.nodal_loads.pop(node_tag, None)
                continue
            applied = values
            if mode == "add":
                existing = self.nodal_loads.get(node_tag)
                if existing is not None:
                    applied = tuple(a + b for a, b in zip(existing.values, values))
            self.nodal_loads[node_tag] = NodalLoad(node_tag, applied)
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

    def apply_local_axis_angle_to_selection(self, angle: float) -> None:
        """Rotate every selected 3D member's local y/z axes about its own
        axis by ``angle`` degrees (``Element.local_axis_angle``) — the escape
        hatch for a member whose auto-picked orientation
        (``_reference_vector`` in the statics solver) does not match its
        section's actual strong/weak axis as drawn. ``angle=0`` is a no-op
        for 2D and truss members, which never read this field.
        """
        if not self.selected_elements:
            return
        self._record_history()
        for element_tag in self.selected_elements:
            element = self.elements.get(element_tag)
            if element is None:
                continue
            self.elements[element_tag] = replace(element, local_axis_angle=angle)
        self._changed()

    def apply_rigid_offset_lengths_to_selection(self, length_i: float, length_j: float) -> None:
        """Rigid end-zone (panel zone) length at each end of every selected
        member, along that member's own axis - see ``Element.offset_i``/
        ``offset_j`` and solver.py's ``-jntOffset`` wiring.

        Takes a plain length per end rather than a raw (x, y, z) vector so
        one call works correctly across a multi-member selection of members
        pointing in different directions - each member's own direction is
        computed here, not asked of the caller. ``length_i``/``length_j`` of
        ``0`` (the default) is a no-op, same as every member drawn before
        this feature existed.
        """
        if not self.selected_elements:
            return
        self._record_history()
        for element_tag in self.selected_elements:
            element = self.elements.get(element_tag)
            if element is None:
                continue
            start = self.nodes.get(element.node_i)
            end = self.nodes.get(element.node_j)
            if start is None or end is None:
                continue
            dx, dy, dz = end.x - start.x, end.y - start.y, end.z - start.z
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if length <= 0.0:
                continue
            direction = (dx / length, dy / length, dz / length)
            offset_i = tuple(component * length_i for component in direction)
            offset_j = tuple(-component * length_j for component in direction)
            self.elements[element_tag] = replace(element, offset_i=offset_i, offset_j=offset_j)
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
        shear_modulus: float | None = None,
        section_id: str | None = None,
        material_id: str | None = None,
        material_category: str | None = None,
        material_grade: str | None = None,
        fy: float = 0.0,
        strain_hardening_ratio: float = 0.02,
        zy: float | None = None,
        zz: float | None = None,
    ) -> None:
        """General section+material application - any of the seven supported
        shapes (Rectangle/Circle/H-I/Box/Pipe/Channel/Angle) or a fully
        user-defined section, Custom (computed via
        ``core.domain.section_properties``) or Database (read straight from
        the Master DB's ``SectionRecord``/``MaterialRecord``, already
        converted to this model's own unit system by the caller - this mixin
        never converts units itself, matching ``apply_section_to_selection``).

        ``element.properties`` keeps ``A``/``I`` as the exact keys the 2D
        solver reads (``I`` is Iy in this app's established convention - see
        ``section_properties.py``'s module docstring), and also writes ``Iy``
        under its own name plus ``G`` (shear modulus) - the
        ``"E"/"A"/"G"/"J"/"Iy"/"Iz"`` set a 3D indeterminate solve needs (see
        ``MaterialFreeStaticsSolver._element_material_3d``) and
        ``model_inspector_panel.py``'s readiness check already expects.
        ``shear_modulus`` defaults to ``elastic / (2 * (1 + DEFAULT_POISSON_
        RATIO))`` when not given - a real per-material value (e.g.
        ``SectionMaterialPanel``'s own Poisson's-ratio field, itself seeded
        from the Master DB's ``poisson_ratio`` when a Database material is
        selected) can be threaded through by callers that have one, without
        changing this default for callers that do not. A
        Rectangle also gets ``width``/``height`` so the existing section
        preview widget keeps working unchanged; every other shape's
        dimensions are dropped (no solver reads them) rather than invented
        under a key that would look like it means something it does not.

        Unlike ``apply_section_to_selection``, this *replaces* every section-
        related key instead of merging - switching shape (or from a Database
        section back to Custom) must not leave a stale key from what the
        member carried before.

        ``fy``/``strain_hardening_ratio``/``zy``/``zz`` feed the 3D pushover
        (Nonlinear Static) solve's lumped-plasticity hinges (see solver.py's
        ``_build_plastic_hinge``): a member only gets a hinge there when
        ``fy`` is positive AND at least one of ``zy``/``zz`` (the section's
        plastic modulus - ``None`` for Channel/Angle, see
        ``SectionProperties``) is given, so "Fy"/"Zy"/"Zz" are only ever
        written when actually usable rather than as a placeholder zero that
        would silently mean something different (0 capacity) if ever read.
        """
        if not self.selected_elements:
            return
        self._record_history()
        shear = (
            shear_modulus
            if shear_modulus is not None
            else elastic / (2.0 * (1.0 + DEFAULT_POISSON_RATIO))
        )
        new_properties: dict[str, float | str] = {
            "E": elastic,
            "A": area,
            "I": iy,
            "Iy": iy,
            "Iz": iz,
            "J": j,
            "G": shear,
            "density": density,
            "section_shape": shape,
            "section_source": source,
        }
        if fy > 0.0:
            new_properties["Fy"] = fy
            new_properties["StrainHardeningRatio"] = strain_hardening_ratio
        if zy is not None:
            new_properties["Zy"] = zy
        if zz is not None:
            new_properties["Zz"] = zz
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

    def apply_behavior_settings_to_selection(
        self, *, gap: float | None = None, prestress: float | None = None
    ) -> None:
        """Write tension/compression/cable extras onto the current selection.

        Section/material apply already retains ``properties["behavior"]`` and
        ``properties["gap"]`` (they are not in ``_SECTION_PROPERTY_KEYS``),
        but prestress lives on ``Element.prestress`` - a separate field that
        ``apply_full_section_to_selection`` never touches. Without this, the
        Create Element 설정창 could only affect members drawn *after* the
        values changed, never ones already on the canvas.
        """
        if not self.selected_elements:
            return
        self._record_history()
        for element_tag in self.selected_elements:
            element = self.elements.get(element_tag)
            if element is None:
                continue
            properties = dict(element.properties)
            behavior = properties.get("behavior", "truss")
            if gap is not None and behavior in ("tension_only", "cable"):
                if gap:
                    properties["gap"] = gap
                else:
                    properties.pop("gap", None)
            next_prestress = element.prestress
            if prestress is not None and behavior == "cable":
                next_prestress = prestress
            self.elements[element_tag] = replace(
                element, properties=properties, prestress=next_prestress
            )
        self._changed()

    def apply_uniform_load_to_selection(
        self,
        values: tuple[float, float] | tuple[float, float, float, float],
        *,
        coordinate_system: str = "local",
        mode: str = "replace",
    ) -> None:
        """Apply a 2D member load in local or global coordinates.

        ``values`` is ``(qx, qy)`` for a plain uniform load, or
        ``(qx_i, qy_i, qx_j, qy_j)`` for a linearly-varying one. Local input
        is stored unchanged. Global X/Y input is resolved separately for each
        selected member, so one wind load can be applied to horizontal,
        vertical and diagonal members together without sharing the wrong
        local components.

        ``mode`` mirrors ``apply_nodal_load_to_selection``'s Add/Replace/
        Delete Options group - see its docstring. "add" sums onto the
        existing *local* wx/wy/wx_j/wy_j (i.e. after any global->local
        conversion below), since that is what is actually stored.
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
            if mode == "delete":
                self.element_loads.pop(element_tag, None)
                continue
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
            if mode == "add":
                existing = self.element_loads.get(element_tag)
                if existing is not None:
                    wx_i += existing.wx
                    wy_i += existing.wy
                    wx_j += existing.wx_j
                    wy_j += existing.wy_j
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
