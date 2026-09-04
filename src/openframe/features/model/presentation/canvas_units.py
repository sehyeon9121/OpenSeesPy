"""Rescale every stored value on StaticsDrawingCanvas when the app's own
force/length unit system changes - the counterpart to
``ModelingInterfacePage.set_unit_system``'s own label refresh, which by
itself only ever changed what a number was *labeled*, never the number
itself (see openframe-unit-system-label-audit.md's own finding: that used
to be the established behaviour everywhere in this app, on the reasoning
that nothing actually consumed the raw model data across a unit switch -
mid-session feedback overturned that once someone pointed out a live unit
toggle on an already-drawn model needs the numbers to actually mean the
same thing afterward, not just wear a different label).

Every physical dimension here traces back to just two conversion factors
(``UnitConversionFactors.length``/``.force``, see ``core.domain.units``) -
this module's whole job is mapping each field on ``Node``/``Element``/
``BoundaryCondition``/``NodalLoad``/``UniformElementLoad``/``LoadEntry``/
``FloorLoadType``/``Story``/``WorkPlane`` to the *right* derived factor
(area, inertia, stress, force_per_length, unit_weight, moment) rather than
inventing a new conversion path per field.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from dataclasses import replace

from openframe.core.domain import (
    BoundaryCondition,
    Element,
    FloorLoadEntry,
    FloorLoadType,
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoad,
    NodalLoadEntry,
    Node,
    SelfWeightEntry,
    Story,
    UniformElementLoad,
    UnitConversionFactors,
)

#: Element.properties keys and the UnitConversionFactors property that
#: converts them - every key ever written by apply_section_to_selection/
#: apply_full_section_to_selection (canvas_property_application.py), plus
#: "dim_*" (any Master-DB/Custom section's own raw dimensions), handled
#: separately below since its members vary per shape.
_LENGTH_PROPERTY_KEYS = frozenset({"width", "height", "gap"})
_AREA_PROPERTY_KEYS = frozenset({"A"})
_INERTIA_PROPERTY_KEYS = frozenset({"I", "Iy", "Iz", "J"})
_STRESS_PROPERTY_KEYS = frozenset({"E", "G"})
_UNIT_WEIGHT_PROPERTY_KEYS = frozenset({"density"})


def _convert_property_value(
    key: str, value: object, factors: UnitConversionFactors
) -> object:
    if not isinstance(value, (int, float)):
        return value  # section_shape/section_source/*_id/*_grade etc - strings
    if key.startswith("dim_"):
        return value * factors.length
    if key in _LENGTH_PROPERTY_KEYS:
        return value * factors.length
    if key in _AREA_PROPERTY_KEYS:
        return value * factors.area
    if key in _INERTIA_PROPERTY_KEYS:
        return value * factors.inertia
    if key in _STRESS_PROPERTY_KEYS:
        return value * factors.stress
    if key in _UNIT_WEIGHT_PROPERTY_KEYS:
        return value * factors.unit_weight
    # An unrecognized numeric key is left alone rather than guessed at - see
    # this module's own docstring on why every conversion here is explicit.
    return value


def _convert_element(element: Element, factors: UnitConversionFactors) -> Element:
    properties = {
        key: _convert_property_value(key, value, factors)
        for key, value in element.properties.items()
    }
    return replace(
        element,
        properties=properties,
        offset_i=tuple(component * factors.length for component in element.offset_i),
        offset_j=tuple(component * factors.length for component in element.offset_j),
        prestress=element.prestress * factors.force,
    )


def _convert_boundary(
    boundary: BoundaryCondition, factors: UnitConversionFactors, ndm: int
) -> BoundaryCondition:
    if not boundary.spring_stiffnesses:
        return boundary
    translational_count = 2 if ndm == 2 else 3
    spring_stiffnesses = tuple(
        None
        if stiffness is None
        else stiffness * (factors.force_per_length if index < translational_count else factors.moment)
        for index, stiffness in enumerate(boundary.spring_stiffnesses)
    )
    return replace(boundary, spring_stiffnesses=spring_stiffnesses)


def _convert_nodal_load(load: NodalLoad, factors: UnitConversionFactors, ndm: int) -> NodalLoad:
    # (Fx, Fy, [Mz]) for 2D, (Fx, Fy, Fz, [Mx, My, Mz]) for 3D - a truss
    # model's shorter, moment-free tuple falls entirely inside "< force_count"
    # either way, so this one rule covers both element families at once.
    force_count = 2 if ndm == 2 else 3
    values = tuple(
        value * (factors.force if index < force_count else factors.moment)
        for index, value in enumerate(load.values)
    )
    return replace(load, values=values)


def _convert_element_load(load: UniformElementLoad, factors: UnitConversionFactors) -> UniformElementLoad:
    scale = factors.force_per_length
    return replace(
        load,
        wx=load.wx * scale,
        wy=load.wy * scale,
        wz=load.wz * scale,
        wx_j=load.wx_j * scale,
        wy_j=load.wy_j * scale,
        wz_j=load.wz_j * scale,
    )


def _convert_load_entry(entry: LoadEntry, factors: UnitConversionFactors) -> LoadEntry:
    payload = entry.payload
    if isinstance(payload, NodalLoadEntry):
        payload = replace(
            payload,
            fx=payload.fx * factors.force,
            fy=payload.fy * factors.force,
            fz=payload.fz * factors.force,
            mx=payload.mx * factors.moment,
            my=payload.my * factors.moment,
            mz=payload.mz * factors.moment,
        )
    elif isinstance(payload, MemberPointLoadEntry):
        value_factor = factors.moment if entry.kind == "member_moment" else factors.force
        position = (
            payload.position * factors.length if payload.position_unit == "length" else payload.position
        )
        payload = replace(payload, value=payload.value * value_factor, position=position)
    elif isinstance(payload, MemberDistributedLoadEntry):
        by_length = payload.position_unit == "length"
        payload = replace(
            payload,
            start_value=payload.start_value * factors.force_per_length,
            end_value=payload.end_value * factors.force_per_length,
            start_position=payload.start_position * factors.length if by_length else payload.start_position,
            end_position=payload.end_position * factors.length if by_length else payload.end_position,
        )
    elif isinstance(payload, FloorLoadEntry):
        payload = replace(payload, magnitude=payload.magnitude * factors.stress)
    elif isinstance(payload, SelfWeightEntry):
        pass  # factor_x/y/z are dimensionless direction cosines - untouched.
    return replace(entry, payload=payload)


def _convert_floor_load_type(floor_type: FloorLoadType, factors: UnitConversionFactors) -> FloorLoadType:
    rows = tuple(replace(row, magnitude=row.magnitude * factors.stress) for row in floor_type.rows)
    return replace(floor_type, rows=rows)


class _UnitConversionMixin:
    def convert_units(self, factors: UnitConversionFactors) -> None:
        """Rescale every stored value in one undo step. A no-op factor
        (switching to the same units, or the very first call before a real
        change) is skipped entirely rather than round-tripping every value
        through a 1.0 multiply and risking floating-point noise for nothing.
        """
        if factors.length == 1.0 and factors.force == 1.0:
            return
        self._record_history()
        self.nodes = {
            tag: Node(node.tag, node.x * factors.length, node.y * factors.length, node.z * factors.length, node.ndf)
            for tag, node in self.nodes.items()
        }
        self.elements = {
            tag: _convert_element(element, factors) for tag, element in self.elements.items()
        }
        self.boundaries = {
            tag: _convert_boundary(boundary, factors, self.ndm) for tag, boundary in self.boundaries.items()
        }
        self.nodal_loads = {
            tag: _convert_nodal_load(load, factors, self.ndm) for tag, load in self.nodal_loads.items()
        }
        self.element_loads = {
            tag: _convert_element_load(load, factors) for tag, load in self.element_loads.items()
        }
        self.load_entries = {
            entry_id: _convert_load_entry(entry, factors) for entry_id, entry in self.load_entries.items()
        }
        self.floor_load_types = {
            type_id: _convert_floor_load_type(floor_type, factors)
            for type_id, floor_type in self.floor_load_types.items()
        }
        self.stories = {
            story_id: Story(story.id, story.name, story.elevation * factors.length, story.rigid_diaphragm)
            for story_id, story in self.stories.items()
        }
        active_index = self.levels.index(self.work_plane) if self.work_plane in self.levels else None
        self.levels = [level.moved_to(level.offset * factors.length) for level in self.levels]
        if active_index is not None:
            self.work_plane = self.levels[active_index]
        self.grid *= factors.length
        self._changed()
        self.load_state_changed.emit()
        self.story_state_changed.emit()
