"""Compile domain loads once for solver/export consumers; no OpenSees or Qt import.

Inputs are additive, already selected/factored by the caller. Do not pass the
same authored entry both here and pre-expanded in StructuralModel.element_loads.
LoadEntry.hidden is visual state, never an instruction to omit a physical load.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal

from openframe.core.domain.load_entry import (
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoadEntry,
    SelfWeightEntry,
)
from openframe.core.domain.model import Element, NodalLoad, StructuralModel
from openframe.core.domain.surfaces import ShellQuad

from .geometry import (
    finite,
    integrate_two_node_load,
    member_length,
    member_local_axes,
    rectangular_quad_nodal_areas,
    to_global,
    to_local,
)
from .plan import (
    ZERO,
    CompiledElementLoad,
    CompiledLoadPlan,
    CompiledNodalLoad,
    ElementLoadTarget,
    LoadCompileError,
    LoadCompileWarning,
    LoadHandling,
    LoadSource,
    Vector3,
)

# Existing solver/export contract: forty midpoint-uniform segments in 2D.
# No synthetic OpenSees tags are allocated here; the target describes the mesh.
LEGACY_BEAM_SEGMENTS = 40
_BEAM_TYPES = frozenset({"frame", "beam", "elasticbeamcolumn", "forcebeamcolumn", "dispbeamcolumn"})
_PARTIAL_BEAM_TYPES = _BEAM_TYPES - {"dispbeamcolumn"}
_POLICY = {
    ("beam", "distributed"): LoadHandling.NATIVE_ELEMENT,
    ("beam", "point"): LoadHandling.NATIVE_ELEMENT,
    ("beam", "self_weight"): LoadHandling.NATIVE_ELEMENT,
    ("truss", "distributed"): LoadHandling.EQUIVALENT_NODAL,
    ("truss", "point"): LoadHandling.EQUIVALENT_NODAL,
    ("truss", "self_weight"): LoadHandling.EQUIVALENT_NODAL,
    ("shell", "self_weight"): LoadHandling.EQUIVALENT_NODAL,
}


def element_load_handling(element: Element | ShellQuad, load_kind: str) -> LoadHandling:
    """Conservative element/load capabilities; unknown combinations are unsupported.

    The truss test intentionally matches solver._element_family: behaviors such
    as cable/tension_only/compression_only are properties on a truss-type member,
    not independent engine element names. Never inherit its arbitrary frame
    fallback for unknown element types when deciding native-load support.
    """
    if isinstance(element, ShellQuad):
        family = "shell"
    elif "truss" in element.element_type.lower():
        family = "truss"
    elif element.element_type.lower() in _BEAM_TYPES:
        family = "beam"
    else:
        return LoadHandling.UNSUPPORTED
    return _POLICY.get((family, load_kind), LoadHandling.UNSUPPORTED)


@dataclass(frozen=True, slots=True)
class _MemberLoad:
    element: Element
    kind: Literal["distributed", "point"]
    start: Vector3
    end: Vector3
    a: float
    b: float
    source: LoadSource


def _vector(values: Iterable[object], label: str) -> Vector3:
    result = tuple(finite(value, label) for value in values)
    if len(result) != 3:
        raise LoadCompileError("invalid_vector", f"{label} must have three components")
    return result


def _in_plane(vector: Vector3, ndm: int) -> Vector3:
    if ndm == 2 and vector[2] != 0.0:
        raise LoadCompileError("out_of_plane_load", "A 2D force must have zero z component")
    return vector


def _fraction(value: float, unit: str, length: float) -> float:
    if unit not in {"ratio", "length"}:
        raise LoadCompileError("invalid_position_unit", repr(unit))
    result = finite(value, "load position") / (length if unit == "length" else 1.0)
    if not 0.0 <= result <= 1.0:
        raise LoadCompileError("invalid_span", f"Load position {result} must be within [0,1]")
    return result


def _entry_vector(payload, value: float, model: StructuralModel, element: Element) -> Vector3:
    if payload.direction not in {"x", "y", "z"}:
        raise LoadCompileError("invalid_direction", repr(payload.direction))
    vector = _in_plane(
        _vector(
            (value if axis == payload.direction else 0.0 for axis in ("x", "y", "z")), "intensity"
        ),
        model.ndm,
    )
    if payload.coordinate_system == "local":
        return vector
    if payload.coordinate_system != "global":
        raise LoadCompileError("invalid_coordinates", repr(payload.coordinate_system))
    return to_local(vector, member_local_axes(model, element))


class _Compiler:
    def __init__(self, model: StructuralModel, gravity_acceleration: float | None):
        self.model = model
        self.gravity = gravity_acceleration
        self.nodal: list[CompiledNodalLoad] = []
        self.native: list[CompiledElementLoad] = []
        self.warnings: list[LoadCompileWarning] = []
        self.members: list[_MemberLoad] = []

    def element(self, tag: int, kind: str) -> Element | ShellQuad:
        element = self.model.elements.get(tag) or self.model.shell_quads.get(tag)
        if element is None:
            raise LoadCompileError("missing_element", f"Load target {tag} does not exist")
        if element_load_handling(element, kind) == LoadHandling.UNSUPPORTED:
            raise LoadCompileError(
                "unsupported_load", f"Target {tag}: {kind} on {type(element).__name__}"
            )
        return element

    def nodal_load(self, load: NodalLoad, source: LoadSource) -> None:
        if load.node_tag not in self.model.nodes:
            raise LoadCompileError("missing_node", f"Nodal load target {load.node_tag}", source)
        values = tuple(finite(value, "nodal load") for value in load.values)
        count = 3 if self.model.ndm == 2 else 6
        if any(values[count:]):
            raise LoadCompileError(
                "extra_components", "Nonzero nodal components would be discarded", source
            )
        values = (values + (0.0,) * count)[:count]
        if self.model.ndm == 2:
            force, moment = (values[0], values[1], 0.0), (0.0, 0.0, values[2])
        else:
            force, moment = values[:3], values[3:]
        self.nodal.append(CompiledNodalLoad(load.node_tag, force, moment, source))

    def member_load(self, element, start, end, a, b, source, kind="distributed") -> None:
        member_length(self.model, element)  # Validate geometry even for native loads.
        start = _in_plane(_vector(start, "start load"), self.model.ndm)
        end = _in_plane(_vector(end, "end load"), self.model.ndm)
        a, b = _fraction(a, "ratio", 1), _fraction(b, "ratio", 1)
        if (kind == "distributed" and a >= b) or a > b:
            raise LoadCompileError("invalid_span", "Load start must precede load end", source)
        self.members.append(_MemberLoad(element, kind, start, end, a, b, source))

    def entry(self, entry: LoadEntry) -> None:
        source = LoadSource(entry.kind, entry_id=entry.id, case_id=entry.case_id)
        payload = entry.payload
        if entry.kind == "self_weight" and isinstance(payload, SelfWeightEntry):
            self.self_weight(payload, source)
            return
        if not entry.target:
            raise LoadCompileError("missing_target", "Load entry has no targets", source)
        if entry.kind == "nodal" and isinstance(payload, NodalLoadEntry):
            if payload.coordinate_system != "global":
                raise LoadCompileError(
                    "nodal_local_axes", "A nodal local frame is not defined", source
                )
            if self.model.ndm == 2:
                if any((payload.fz, payload.mx, payload.my)):
                    raise LoadCompileError(
                        "out_of_plane_load", "2D nodal entry has out-of-plane components", source
                    )
                values = (payload.fx, payload.fy, payload.mz)
            else:
                values = (payload.fx, payload.fy, payload.fz, payload.mx, payload.my, payload.mz)
            for tag in dict.fromkeys(entry.target):
                self.nodal_load(NodalLoad(tag, values), source)
            return
        distributed = entry.kind in {"member_uniform", "member_linear", "member_partial"}
        if not (
            (distributed and isinstance(payload, MemberDistributedLoadEntry))
            or (entry.kind == "member_point" and isinstance(payload, MemberPointLoadEntry))
        ):
            raise LoadCompileError(
                "unsupported_entry", f"{entry.kind}: lower floor/moment loads upstream", source
            )
        for tag in dict.fromkeys(entry.target):
            element = self.element(tag, "distributed" if distributed else "point")
            length = member_length(self.model, element)
            target_source = replace(source, element_tag=tag)
            if distributed:
                a = _fraction(payload.start_position, payload.position_unit, length)
                b = _fraction(payload.end_position, payload.position_unit, length)
                start = _entry_vector(payload, payload.start_value, self.model, element)
                end = _entry_vector(payload, payload.end_value, self.model, element)
                self.member_load(element, start, end, a, b, target_source)
            else:
                position = _fraction(payload.position, payload.position_unit, length)
                value = _entry_vector(payload, payload.value, self.model, element)
                self.member_load(element, value, value, position, position, target_source, "point")

    def self_weight(self, payload: SelfWeightEntry, source: LoadSource) -> None:
        factors = _in_plane(
            _vector((payload.factor_x, payload.factor_y, payload.factor_z), "self weight factors"),
            self.model.ndm,
        )
        if payload.apply_to_all:
            tags = sorted(set(self.model.elements) | set(self.model.shell_quads))
            meshed = {quad.wall_tag for quad in self.model.shell_quads.values()}
            if any(wall.tag not in meshed for wall in self.model.walls.values()):
                raise LoadCompileError(
                    "unmeshed_wall", "Mesh all wall panels before compiling self weight", source
                )
        else:
            tags = sorted(set(payload.target_elements))
            if not tags:
                raise LoadCompileError(
                    "missing_target", "Targeted self weight has no elements", source
                )
        for tag in tags:
            element = self.element(tag, "self_weight")
            current = replace(source, element_tag=tag)
            if isinstance(element, ShellQuad):
                self.shell_weight(element, factors, current)
                continue
            try:
                density = finite(element.properties["density"], "member unit weight")
                area = finite(element.properties["A"], "member area")
            except KeyError as exc:
                raise LoadCompileError(
                    "missing_weight_property", f"Member {tag}: {exc}", current
                ) from exc
            if density < 0 or area <= 0:
                raise LoadCompileError(
                    "invalid_weight_property", "Require density >= 0 and A > 0", current
                )
            if density == 0 or factors == ZERO:
                continue
            # Member density is FORCE/VOLUME. No additional g multiplication.
            global_load = tuple(density * area * value for value in factors)
            local = to_local(global_load, member_local_axes(self.model, element))
            self.member_load(element, local, local, 0.0, 1.0, current)

    def shell_weight(self, quad: ShellQuad, factors: Vector3, source: LoadSource) -> None:
        if self.model.ndm != 3:
            raise LoadCompileError(
                "shell_dimension", "ShellQuad self weight requires ndm=3", source
            )
        wall = self.model.walls.get(quad.wall_tag)
        if wall is None:
            raise LoadCompileError("missing_wall", f"Shell {quad.tag} has no parent wall", source)
        density, thickness = (
            finite(wall.density, "shell mass density"),
            finite(wall.thickness, "thickness"),
        )
        if density < 0 or thickness <= 0:
            raise LoadCompileError(
                "invalid_weight_property", "Require shell density >= 0 and t > 0", source
            )
        areas = rectangular_quad_nodal_areas(self.model, quad)
        if density == 0 or factors == ZERO:
            return
        # surfaces._section_command sends wall.density unchanged as MASS/VOLUME
        # to ElasticMembranePlateSection. Unlike line-member density it needs g.
        if self.gravity is None or finite(self.gravity, "gravity_acceleration") <= 0:
            raise LoadCompileError(
                "gravity_required",
                "Supply positive g in MODEL length/time² units for shell mass density",
                source,
            )
        for node, area in zip(quad.node_tags(), areas):
            force = _vector(
                (density * thickness * area * self.gravity * v for v in factors), "shell weight"
            )
            self.nodal.append(CompiledNodalLoad(node, force, source=source))

    def lower(self) -> CompiledLoadPlan:
        subdivided: set[int] = set()
        for load in self.members:
            if element_load_handling(load.element, load.kind) != LoadHandling.NATIVE_ELEMENT:
                continue
            transform = self.model.geometric_transforms.get(load.element.transf_tag)
            if load.element.transf_tag is not None and transform is None:
                raise LoadCompileError(
                    "missing_transform", str(load.element.transf_tag), load.source
                )
            if transform and (
                transform.transform_type not in {"Linear", "PDelta", "Corotational"}
                or (self.model.ndm == 3 and transform.transform_type == "Corotational")
            ):
                raise LoadCompileError(
                    "unsupported_transform_load",
                    "Native beam loads cannot be guaranteed for this transform",
                    load.source,
                )
            if load.kind == "distributed" and load.start != load.end:
                if self.model.ndm != 2 or (load.a, load.b) != (0.0, 1.0):
                    raise LoadCompileError(
                        "unsupported_beam_trapezoid",
                        "Legacy beam subdivision supports only 2D full-span trapezoids",
                        load.source,
                    )
                if any((*load.element.offset_i, *load.element.offset_j)):
                    raise LoadCompileError(
                        "offset_subdivision",
                        "Offset beam subdivision is not supported",
                        load.source,
                    )
                subdivided.add(load.element.tag)
        for load in self.members:
            if element_load_handling(load.element, load.kind) == LoadHandling.EQUIVALENT_NODAL:
                self.truss_load(load)
            else:
                self.beam_load(load, load.element.tag in subdivided)
        return CompiledLoadPlan(tuple(self.nodal), tuple(self.native), tuple(self.warnings))

    def truss_load(self, load: _MemberLoad) -> None:
        axes = member_local_axes(self.model, load.element)
        start, end = to_global(load.start, axes), to_global(load.end, axes)
        if load.kind == "point":
            forces = (tuple((1 - load.a) * v for v in start), tuple(load.a * v for v in start))
        else:
            forces = integrate_two_node_load(
                member_length(self.model, load.element), load.a, load.b, start, end
            )
        for node, force in zip((load.element.node_i, load.element.node_j), forces):
            self.nodal.append(
                CompiledNodalLoad(node, _vector(force, "equivalent force"), source=load.source)
            )
        if load.element.properties.get("behavior") in {"cable", "tension_only"}:
            self.warnings.append(
                LoadCompileWarning(
                    "cable_sag_not_represented",
                    "Two-node equivalent forces preserve resultant/moment but do not reproduce cable sag or distributed-load shape.",
                    load.source,
                )
            )

    def beam_load(self, load: _MemberLoad, subdivided: bool) -> None:
        count = LEGACY_BEAM_SEGMENTS if subdivided else 1
        if subdivided and load.start != load.end:
            self.warnings.append(
                LoadCompileWarning(
                    "beam_trapezoid_midpoint_approximation",
                    "Legacy 40-segment midpoint load: resultant is exact; first moment/within-segment response are approximate.",
                    load.source,
                )
            )
        if load.kind == "point":
            index = min(int(load.a * count), count - 1)
            target = ElementLoadTarget(load.element.tag, index if subdivided else None, count)
            self.native.append(
                CompiledElementLoad(
                    target, "point", load.start, load.source, position=load.a * count - index
                )
            )
            return
        for index in range(count):
            left, right = max(load.a, index / count), min(load.b, (index + 1) / count)
            if right <= left:
                continue
            position = ((left + right) / 2 - load.a) / (load.b - load.a)
            intensity = tuple(
                (1 - position) * a + position * b for a, b in zip(load.start, load.end)
            )
            # Exact segment boundaries must stay 0/1 despite floating-point
            # cancellation, including for beams that reject partial loading.
            a = 0.0 if left == index / count else left * count - index
            b = 1.0 if right == (index + 1) / count else right * count - index
            if (a, b) != (
                0.0,
                1.0,
            ) and load.element.element_type.lower() not in _PARTIAL_BEAM_TYPES:
                raise LoadCompileError(
                    "unsupported_partial_beam",
                    "Partial native load is not supported by this beam type",
                    load.source,
                )
            self.native.append(
                CompiledElementLoad(
                    ElementLoadTarget(load.element.tag, index if subdivided else None, count),
                    "uniform",
                    _vector(intensity, "native intensity"),
                    load.source,
                    a,
                    b,
                )
            )


def compile_loads(
    model: StructuralModel,
    *,
    entries: Iterable[LoadEntry] = (),
    self_weight: SelfWeightEntry | None = None,
    gravity_acceleration: float | None = None,
) -> CompiledLoadPlan:
    """Compile additive model loads + selected/factored entries + optional self weight.

    Compiler does not mesh walls, filter cases, apply combination factors, change
    units, or call an engine. Shell density is mass/volume as currently passed to
    the shell section: specify g in model units. Line density is unit weight.
    See docs/load_compiler.md for native segment resolution and pattern handling.
    """
    if model.ndm not in {2, 3}:
        raise LoadCompileError("unsupported_dimension", f"ndm={model.ndm}")
    if set(model.elements) & set(model.shell_quads):
        raise LoadCompileError(
            "element_tag_collision", "Line and shell element tags must be distinct"
        )
    compiler = _Compiler(model, gravity_acceleration)
    for load in model.nodal_loads:
        compiler.nodal_load(
            load, LoadSource("nodal", pattern_tag=load.pattern_tag, case_type=load.case_type)
        )
    for load in model.element_loads:
        element = compiler.element(load.element_tag, "distributed")
        source = LoadSource(
            "distributed", load.element_tag, pattern_tag=load.pattern_tag, case_type=load.case_type
        )
        compiler.member_load(
            element,
            (load.wx, load.wy, load.wz),
            (load.wx_j, load.wy_j, load.wz_j),
            load.xL1,
            load.xL2,
            source,
        )
    for load in model.point_loads:
        element = compiler.element(load.element_tag, "point")
        source = LoadSource(
            "point", load.element_tag, pattern_tag=load.pattern_tag, case_type=load.case_type
        )
        vector = (load.n, load.py, load.pz)
        compiler.member_load(element, vector, vector, load.position, load.position, source, "point")
    for entry in entries:
        compiler.entry(entry)
    if self_weight is not None:
        compiler.self_weight(self_weight, LoadSource("self_weight"))
    return compiler.lower()
