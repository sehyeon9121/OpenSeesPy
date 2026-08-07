"""Solve statically determinate 2D textbook problems without material data.

For a stable determinate structure, reactions and member forces follow from
equilibrium and do not depend on EA or EI.  OpenSees is therefore given normalized
positive stiffness solely as a numerical mechanism.  Indeterminate structures are
rejected because their force distribution genuinely depends on member stiffness.
"""

import math
from dataclasses import dataclass

import openseespy.opensees as ops

from openframe.core.domain.model import BoundaryCondition, Element, StructuralModel
from openframe.core.domain.results import (
    AnalysisResult,
    AnalysisStatus,
    ElementResult,
    NodeResult,
)

# Ground node and zero-length element tags for inclined supports are offset well
# past any tag a hand-drawn model would ever reach, so they never collide with a
# real node or element.
_INCLINED_SUPPORT_TAG_OFFSET = 9_000_000
_INCLINED_SUPPORT_MATERIAL_TAG = 9_000_001
# Large enough to make the modelled incline effectively rigid, small enough that it
# does not swamp the unit member stiffness used everywhere else and spoil the solve's
# numerical conditioning; verified against hand-calculated inclined-roller reactions.
_INCLINED_SUPPORT_STIFFNESS = 1.0e8
# `element Truss` takes a *material* tag, not a raw modulus — one shared linear-
# elastic material (E=1, matching every other unit-stiffness placeholder here)
# covers every truss member in the model.
_TRUSS_MATERIAL_TAG = 9_000_002

# OpenSeesPy's own eleLoad has no linearly-varying ("trapezoidal") transverse load
# type - only a constant -beamUniform. A member carrying one (wx != wx_j or
# wy != wy_j) is therefore chained together from many short, rigidly-connected
# elasticBeamColumn sub-elements instead of built as one OpenSees element, each
# sub-element carrying OpenSees' own constant -beamUniform at the true w(x) value
# sampled at its own midpoint. This is invisible outside the solver: the domain
# model, check_determinacy and every other feature still see exactly one Element
# per member. Offsets are well past any tag a hand-drawn model or the inclined-
# support machinery above would ever reach.
_TRAPEZOID_NODE_TAG_OFFSET = 7_000_000
_TRAPEZOID_ELEMENT_TAG_OFFSET = 7_500_000
#: Sub-elements per trapezoidally-loaded member. A midpoint sample reproduces the
#: exact resultant force of a *linear* w(x) over each sub-segment regardless of
#: this count (the only error left is the within-segment uniform-shape
#: approximation), and that error shrinks fast as this grows - verified in
#: tests/unit/test_material_free_statics.py against the closed-form
#: simply-supported triangular-load case (wL^2/(9*sqrt(3)) at x=L/sqrt(3)).
_TRAPEZOID_SEGMENTS = 40


@dataclass(frozen=True, slots=True)
class DeterminacyCheck:
    system: str
    degree: int
    message: str

    @property
    def can_solve_without_materials(self) -> bool:
        return self.degree == 0


def check_determinacy(model: StructuralModel) -> DeterminacyCheck:
    """Return the classical determinacy count for a plane or space frame/truss.

    A truss joint has ``ndm`` equilibrium equations (2 in the plane, 3 in space);
    a rigid frame joint has ``ndm`` translations plus the rotations that make
    sense in that many dimensions — 1 (Mz) in 2D, 3 (Mx, My, Mz) in 3D — so a
    frame joint contributes 3 equations in 2D and 6 in 3D. Everything else is the
    same formula the 2D solver always used; this is a strict generalisation.
    """
    if model.ndm not in (2, 3):
        return DeterminacyCheck("unsupported", 1, "재료 없는 정역학 풀이는 2D 또는 3D 모델만 지원합니다.")
    if not model.nodes or not model.elements:
        return DeterminacyCheck("empty", -1, "절점과 부재를 먼저 작성하세요.")

    kinds = {_element_family(element.element_type) for element in model.elements.values()}
    if len(kinds) != 1:
        return DeterminacyCheck(
            "mixed",
            1,
            "프레임과 트러스가 혼합된 모델은 재료 및 단면 강성이 필요합니다.",
        )

    system = kinds.pop()
    members = len(model.elements)
    active_nodes = {
        node_tag
        for element in model.elements.values()
        for node_tag in (element.node_i, element.node_j)
    }
    active_nodes.update(
        condition.node_tag for condition in model.boundaries if any(condition.restraints)
    )
    active_nodes.update(load.node_tag for load in model.nodal_loads)
    joints = len(active_nodes)
    if system == "truss":
        reactions = sum(sum(condition.restraints[: model.ndm]) for condition in model.boundaries)
        degree = members + reactions - model.ndm * joints
    else:
        dof = 3 if model.ndm == 2 else 6
        reactions = sum(sum(condition.restraints[:dof]) for condition in model.boundaries)
        # A drawn end release only reaches the solver in 2D (see _build): a 3D
        # frame member has two independent bending planes, and OpenSees' -release
        # flag is not unambiguous about which one it frees, so 3D releases are not
        # yet realised. Counting them here without applying them in _build would
        # tell a Gerber-beam-shaped 3D model it is solvable when it silently is not.
        releases = (
            sum(element.release_count for element in model.elements.values())
            if model.ndm == 2
            else 0
        )
        degree = dof * members + reactions - dof * joints - releases

    if degree == 0:
        message = "정정구조입니다. 재료 및 단면 물성 없이 반력과 부재력을 계산할 수 있습니다."
    elif degree > 0:
        message = f"{degree}차 부정정 구조입니다. 재료 및 단면 강성을 정의해야 합니다."
    else:
        message = f"정정차수가 {degree}이므로 불안정 구조일 가능성이 있습니다. 지점 조건을 확인하세요."
    return DeterminacyCheck(system, degree, message)


class MaterialFreeStaticsSolver:
    """Calculate reactions and N/V/M forces for determinate planar structures.

    Given real (E, A, I) - per element via ``Element.properties["E"/"A"/"I"]``,
    or a uniform fallback via ``solve(model, material=...)`` - it can also
    solve *indeterminate* 2D frames: determinate results never depend on
    stiffness, but an indeterminate structure's internal forces genuinely do,
    so equilibrium alone (unit placeholder stiffness) cannot give a physically
    meaningful answer for one. Every existing caller that never sets either
    keeps the exact original unit-stiffness, determinate-only behaviour
    unchanged.
    """

    def solve(
        self, model: StructuralModel, material: tuple[float, float, float] | None = None
    ) -> AnalysisResult:
        """``material`` is a (E, A, I) fallback applied to any 2D frame member
        that doesn't carry its own E/A/I in ``properties`` - real values here
        (per element or as this fallback) also give real (not unit-normalised)
        deflection for determinate structures, since deflection, unlike
        reactions and N/V/M, does scale with EI even when it is determinate.
        """
        check = check_determinacy(model)
        if not check.can_solve_without_materials:
            if material is None and not self._has_material_everywhere(model, check.system):
                return AnalysisResult(status=AnalysisStatus.FAILED, messages=[check.message])
            if check.system != "frame" or model.ndm != 2:
                return AnalysisResult(
                    status=AnalysisStatus.FAILED,
                    messages=[
                        check.message,
                        "부정정 트러스·3D 모델의 강성 해석은 아직 지원하지 않습니다.",
                    ],
                )

        ops.wipe()
        try:
            self._build(model, check.system, material)
            self._apply_loads(model, check.system)
            self._analyze()
            return self._collect(model, check.system, check.message, material)
        except (RuntimeError, ValueError, ops.OpenSeesError) as error:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"정역학 계산에 실패했습니다: {error}"],
            )
        finally:
            ops.wipe()

    @staticmethod
    def _element_material(element: Element) -> tuple[float, float, float] | None:
        """(E, A, I) from ``element.properties``, or ``None`` if any of the
        three is missing or not a real number - e.g. a truss member's own
        "A"/"material_tag" pair, which is a different shape entirely."""
        try:
            return (
                float(element.properties["E"]),
                float(element.properties["A"]),
                float(element.properties["I"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _resolve_material(
        element: Element, fallback: tuple[float, float, float] | None
    ) -> tuple[float, float, float]:
        """(E, A, I) for one element: its own properties win, then the solve-
        wide fallback (if given), then the unit placeholder every determinate
        call already relied on."""
        return (
            MaterialFreeStaticsSolver._element_material(element)
            or fallback
            or (1.0, 1.0, 1.0)
        )

    @staticmethod
    def _has_material_everywhere(model: StructuralModel, system: str) -> bool:
        if system != "frame":
            return False
        return all(
            MaterialFreeStaticsSolver._element_material(element) is not None
            for element in model.elements.values()
        )

    @staticmethod
    def _build(
        model: StructuralModel,
        system: str,
        material: tuple[float, float, float] | None = None,
    ) -> None:
        ndm = model.ndm
        ndf = (2 if system == "truss" else 3) if ndm == 2 else (3 if system == "truss" else 6)
        ops.model("basic", "-ndm", ndm, "-ndf", ndf)
        for node in model.nodes.values():
            coordinates = (node.x, node.y) if ndm == 2 else (node.x, node.y, node.z)
            ops.node(node.tag, *coordinates)
        inclined = (
            [condition for condition in model.boundaries if condition.is_inclined]
            if ndm == 2
            else []
        )
        for condition in model.boundaries:
            if condition.is_inclined:
                continue
            restraints = tuple(int(value) for value in condition.restraints[:ndf])
            restraints += (0,) * (ndf - len(restraints))
            ops.fix(condition.node_tag, *restraints)
        if inclined:
            ops.uniaxialMaterial("Elastic", _INCLINED_SUPPORT_MATERIAL_TAG, _INCLINED_SUPPORT_STIFFNESS)
            for condition in inclined:
                MaterialFreeStaticsSolver._fix_inclined(condition, ndf, model)

        if system == "truss":
            ops.uniaxialMaterial("Elastic", _TRUSS_MATERIAL_TAG, 1.0)
            for element in model.elements.values():
                ops.element(
                    "truss", element.tag, element.node_i, element.node_j, 1.0, _TRUSS_MATERIAL_TAG
                )
            return

        if ndm == 2:
            ops.geomTransf("Linear", 1)
            trapezoid_loads = {
                load.element_tag: load for load in model.element_loads if not load.is_uniform
            }
            for element in model.elements.values():
                elastic, area, inertia = MaterialFreeStaticsSolver._resolve_material(
                    element, material
                )
                trapezoid = trapezoid_loads.get(element.tag)
                if trapezoid is not None:
                    MaterialFreeStaticsSolver._build_discretized_member(
                        model, element, area, elastic, inertia
                    )
                    continue
                arguments: list[object] = [
                    "elasticBeamColumn",
                    element.tag,
                    element.node_i,
                    element.node_j,
                    area,
                    elastic,
                    inertia,
                    1,
                ]
                release_code = int(element.moment_release_i) + 2 * int(element.moment_release_j)
                if release_code:
                    arguments += ["-release", release_code]
                ops.element(*arguments)
            return

        for element in model.elements.values():
            node_i = model.nodes[element.node_i]
            node_j = model.nodes[element.node_j]
            transf_tag = element.tag
            ops.geomTransf(
                "Linear", transf_tag, *_reference_vector(node_i, node_j)
            )
            ops.element(
                "elasticBeamColumn",
                element.tag,
                element.node_i,
                element.node_j,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                transf_tag,
            )

    @staticmethod
    def _trapezoid_sub_element_tags(element_tag: int) -> list[int]:
        """Deterministic from ``element_tag`` alone, so ``_apply_loads`` and
        ``_collect`` can each regenerate the same tags independently instead of
        threading shared state through this class's staticmethods."""
        return [
            _TRAPEZOID_ELEMENT_TAG_OFFSET + element_tag * 1000 + segment
            for segment in range(_TRAPEZOID_SEGMENTS)
        ]

    @staticmethod
    def _build_discretized_member(
        model: StructuralModel,
        element: Element,
        area: float = 1.0,
        elastic: float = 1.0,
        inertia: float = 1.0,
    ) -> None:
        node_i = model.nodes[element.node_i]
        node_j = model.nodes[element.node_j]
        segments = _TRAPEZOID_SEGMENTS
        node_tags = (
            [element.node_i]
            + [
                _TRAPEZOID_NODE_TAG_OFFSET + element.tag * 1000 + segment
                for segment in range(1, segments)
            ]
            + [element.node_j]
        )
        for segment in range(1, segments):
            ratio = segment / segments
            ops.node(
                node_tags[segment],
                node_i.x + (node_j.x - node_i.x) * ratio,
                node_i.y + (node_j.y - node_i.y) * ratio,
            )
        sub_tags = MaterialFreeStaticsSolver._trapezoid_sub_element_tags(element.tag)
        for segment, sub_tag in enumerate(sub_tags):
            arguments: list[object] = [
                "elasticBeamColumn",
                sub_tag,
                node_tags[segment],
                node_tags[segment + 1],
                area,
                elastic,
                inertia,
                1,
            ]
            # A release only ever belongs at the member's *true* ends - every
            # sub-node in between is an artefact of the discretization, not a
            # real joint, and must stay moment-continuous.
            release_i = element.moment_release_i if segment == 0 else False
            release_j = element.moment_release_j if segment == segments - 1 else False
            release_code = int(release_i) + 2 * int(release_j)
            if release_code:
                arguments += ["-release", release_code]
            ops.element(*arguments)

    @staticmethod
    def _fix_inclined(condition: BoundaryCondition, ndf: int, model: StructuralModel) -> None:
        """Ground a rotated support through a stiff zero-length spring.

        OpenSees can only ``fix`` a node's global degrees of freedom, so a support
        whose restrained direction is not along X or Y needs a small trick: a fully
        fixed dummy node at the same point, connected to the real node by a
        zero-length element whose local axes are rotated to the support's angle.
        Giving that element a material only in the restrained local direction(s)
        restrains exactly that direction and leaves the others free to slide, which
        is what a roller resting on an inclined surface actually does.
        """
        node = model.nodes[condition.node_tag]
        ground_tag = _INCLINED_SUPPORT_TAG_OFFSET + condition.node_tag
        ops.node(ground_tag, node.x, node.y)
        ops.fix(ground_tag, *((1,) * ndf))
        radians = math.radians(condition.angle)
        vector_x = (math.cos(radians), math.sin(radians), 0.0)
        vector_y = (-math.sin(radians), math.cos(radians), 0.0)
        materials: list[int] = []
        directions: list[int] = []
        for index in range(min(2, ndf)):
            if condition.restraints[index]:
                materials.append(_INCLINED_SUPPORT_MATERIAL_TAG)
                directions.append(index + 1)
        if ndf > 2 and len(condition.restraints) > 2 and condition.restraints[2]:
            materials.append(_INCLINED_SUPPORT_MATERIAL_TAG)
            directions.append(3)
        if not directions:
            return
        ops.element(
            "zeroLength",
            ground_tag,
            ground_tag,
            condition.node_tag,
            "-mat",
            *materials,
            "-dir",
            *directions,
            "-orient",
            *vector_x,
            *vector_y,
        )

    @staticmethod
    def _apply_loads(model: StructuralModel, system: str) -> None:
        ndm = model.ndm
        ndf = (2 if system == "truss" else 3) if ndm == 2 else (3 if system == "truss" else 6)
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        for load in model.nodal_loads:
            values = tuple(load.values[:ndf]) + (0.0,) * max(0, ndf - len(load.values))
            ops.load(load.node_tag, *values)
        if system == "truss" and model.element_loads:
            raise ValueError("트러스 부재의 등분포하중은 절점하중으로 변환해 입력하세요.")
        if ndm == 3 and model.element_loads:
            # A transverse load's direction depends on which way the member's local
            # y/z axes ended up facing, which this solver only chooses automatically
            # (see _reference_vector) — not something a student picked, so a wx/wy
            # UI value could silently land in the wrong physical direction. Until
            # there is a UI that lets the direction be chosen deliberately, nodal
            # loads are the honest way to load a 3D member.
            raise ValueError(
                "3D 모델의 부재 분포하중은 아직 지원하지 않습니다. 절점하중으로 입력하세요."
            )
        for load in model.element_loads:
            if load.is_uniform:
                ops.eleLoad("-ele", load.element_tag, "-type", "-beamUniform", load.wy, load.wx)
                continue
            # No native linearly-varying eleLoad exists (see _TRAPEZOID_SEGMENTS) -
            # _build already split this member into that many sub-elements, so
            # each sub-element gets OpenSees' own constant -beamUniform sampled at
            # the true w(x) value at its own midpoint. A midpoint sample equals
            # the segment's exact average for a linear w(x), so this reproduces
            # the exact resultant force per segment; only the within-segment
            # shape is approximated.
            sub_tags = MaterialFreeStaticsSolver._trapezoid_sub_element_tags(load.element_tag)
            for segment, sub_tag in enumerate(sub_tags):
                midpoint = (segment + 0.5) / _TRAPEZOID_SEGMENTS
                wx_mid = load.wx + (load.wx_j - load.wx) * midpoint
                wy_mid = load.wy + (load.wy_j - load.wy) * midpoint
                ops.eleLoad("-ele", sub_tag, "-type", "-beamUniform", wy_mid, wx_mid)

    @staticmethod
    def _analyze() -> None:
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Plain")
        ops.integrator("LoadControl", 1.0)
        ops.algorithm("Linear")
        ops.analysis("Static")
        if ops.analyze(1) != 0:
            raise RuntimeError("구조가 불안정하거나 지점 조건이 충분하지 않습니다.")
        ops.reactions()

    @staticmethod
    def _collect(
        model: StructuralModel,
        system: str,
        message: str,
        material: tuple[float, float, float] | None = None,
    ) -> AnalysisResult:
        # An inclined support's reaction was never fixed at the real node — it lives
        # on the dummy ground node the zero-length spring pushes against — so that is
        # where the reaction has to be read back from.
        reaction_source = {
            condition.node_tag: _INCLINED_SUPPORT_TAG_OFFSET + condition.node_tag
            for condition in model.boundaries
            if condition.is_inclined
        }
        node_results = {
            tag: NodeResult(
                node_tag=tag,
                displacement=tuple(float(value) for value in ops.nodeDisp(tag)),
                reaction=tuple(
                    float(value) for value in ops.nodeReaction(reaction_source.get(tag, tag))
                ),
            )
            for tag in model.nodes
        }
        uniform_loads = {
            load.element_tag: (load.wx, load.wy, load.wx_j, load.wy_j)
            for load in model.element_loads
        }
        trapezoid_tags = {load.element_tag for load in model.element_loads if not load.is_uniform}
        element_results: dict[int, ElementResult] = {}
        for tag, element in model.elements.items():
            node_i = model.nodes[element.node_i]
            node_j = model.nodes[element.node_j]
            length = math.sqrt(
                (node_j.x - node_i.x) ** 2
                + (node_j.y - node_i.y) ** 2
                + (node_j.z - node_i.z) ** 2
            )
            if system == "truss":
                axial_response = ops.eleResponse(tag, "axialForce")
                axial = float(axial_response[0]) if axial_response else 0.0
                local_force = (
                    (-axial, 0.0, 0.0, axial, 0.0, 0.0)
                    if model.ndm == 2
                    else (-axial, 0.0, 0.0, 0.0, 0.0, 0.0, axial, 0.0, 0.0, 0.0, 0.0, 0.0)
                )
            elif tag in trapezoid_tags:
                # This member was never built as one OpenSees element (see
                # _build_discretized_member) - its true end forces are the first
                # sub-element's i-end and the last sub-element's j-end.
                sub_tags = MaterialFreeStaticsSolver._trapezoid_sub_element_tags(tag)
                first = ops.eleResponse(sub_tags[0], "localForce") or ops.eleForce(sub_tags[0])
                last = ops.eleResponse(sub_tags[-1], "localForce") or ops.eleForce(sub_tags[-1])
                local_force = (first[0], first[1], first[2], last[3], last[4], last[5])
            else:
                local_force = ops.eleResponse(tag, "localForce")
                if not local_force:
                    local_force = ops.eleForce(tag)
            # Real EI, when given (per element or as the solve-wide fallback),
            # is what lets deflected_shape.py's clamped-sag correction produce
            # true absolute deflection instead of the flat (unit-normalised)
            # shape it falls back to at flexural_rigidity == 0 - see
            # ElementResult.flexural_rigidity's own docstring. Deliberately
            # NOT using _resolve_material's unit-placeholder fallback here:
            # that 1.0 exists only so OpenSees has a nonzero stiffness to
            # build with, not a real EI whose deflection would mean anything.
            real_material = MaterialFreeStaticsSolver._element_material(element) or material
            flexural_rigidity = (
                real_material[0] * real_material[2]
                if real_material is not None and system != "truss"
                else 0.0
            )
            element_results[tag] = ElementResult(
                element_tag=tag,
                local_forces=tuple(float(value) for value in local_force),
                length=length,
                uniform_load=uniform_loads.get(tag, (0.0, 0.0, 0.0, 0.0)),
                flexural_rigidity=flexural_rigidity,
            )
        return AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            node_results=node_results,
            element_results=element_results,
            messages=[message, "반력과 부재력은 평형조건으로 계산되었습니다."],
        )


def _element_family(element_type: str) -> str:
    return "truss" if "truss" in element_type.lower() else "frame"


def _reference_vector(node_i, node_j) -> tuple[float, float, float]:
    """A ``vecxz`` for ``geomTransf`` that is never parallel to the member axis.

    The reactions and member forces this solver reports never depend on which
    way "local y" versus "local z" actually points, because every 3D member here
    carries the same placeholder Iy=Iz=1.0 — a symmetric section is indifferent
    to which axis is which. All that is required is a vector not colinear with
    the member, so global Z works for every member except a vertical one, which
    falls back to global X.
    """
    dx = node_j.x - node_i.x
    dy = node_j.y - node_i.y
    dz = node_j.z - node_i.z
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    axis = (dx / length, dy / length, dz / length)
    global_z = (0.0, 0.0, 1.0)
    is_vertical = abs(axis[0] * global_z[0] + axis[1] * global_z[1] + axis[2] * global_z[2]) > 0.999
    return (1.0, 0.0, 0.0) if is_vertical else global_z
