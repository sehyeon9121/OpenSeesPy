"""Solve statically determinate textbook problems without material data, plus
indeterminate 2D and 3D frames, and indeterminate *pure* trusses once every
member carries real section/material properties.

For a stable determinate structure, reactions and member forces follow from
equilibrium and do not depend on EA or EI.  OpenSees is therefore given normalized
positive stiffness solely as a numerical mechanism - but that placeholder must
never be presented as a physical displacement.  An indeterminate structure's
force distribution genuinely depends on member stiffness, so it is rejected unless
every element carries real properties - (E, A, I) for a 2D frame, (E, A, G, J, Iy,
Iz) for a 3D one, (E, A) for a truss/cable/tension-only/compression-only member
(all of which share the "truss" element family - see ``_element_family``), the
same key convention model_inspector_panel.py's readiness check already expects.

A mixed frame+truss model is still rejected: this solver has no combined
stiffness assembly for that case. Pure trusses (2D and 3D) with a valid E and A
on every member are solved with that real EA, including 1+ degree indeterminate
ones.
"""

import math
from dataclasses import dataclass

import openseespy.opensees as ops

from openframe.core.domain.geometric_transform import (
    auto_reference_vector,
    boundary_local_axes,
    rotate_about_axis,
)
from openframe.core.domain.model import BoundaryCondition, Element, StructuralModel
from openframe.core.domain.results import (
    UNIT_STIFFNESS_DISPLACEMENT_WARNING,
    AnalysisResult,
    AnalysisStatus,
    DisplacementStiffnessKind,
    ElementResult,
    LoadDisplacementPoint,
    NodeResult,
    NonlinearConvergence,
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
# covers every truss member that carries no real E/A of its own.
_TRUSS_MATERIAL_TAG = 9_000_002
# A truss member that DOES carry real (E, A) needs its own material tag (E
# varies per element, unlike the unit placeholder above) - offset by the
# element's own tag, same scheme as every other *_TAG_OFFSET here.
_TRUSS_ELEMENT_MATERIAL_TAG_OFFSET = 9_600_000

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

# A 3D member end release (see _build_hinge_zeroLength) needs a duplicate node at
# the same point plus a zeroLength element tying them together in every direction
# except the two local bending rotations - offsets kept clear of every other
# dummy-tag range above.
_HINGE_NODE_TAG_OFFSET = 8_000_000
_HINGE_MATERIAL_TAG = 8_000_001
#: Same magnitude as _INCLINED_SUPPORT_STIFFNESS and for the same reason: rigid
#: enough that the released end's translation/torsion behave as continuous, small
#: enough not to spoil the solve's numerical conditioning against the unit member
#: stiffness used everywhere else in this solver.
_HINGE_STIFFNESS = 1.0e8

# An elastic spring support (Story Manager's neighbour feature) needs the same
# ground-node + zeroLength trick as an inclined support, but with a real,
# user-chosen stiffness per DOF instead of one shared rigid constant - so each
# sprung DOF gets its own uniaxialMaterial tag, minted sequentially from this
# offset instead of one shared tag. Kept clear of every other dummy-tag range
# above.
_SPRING_TAG_OFFSET = 9_500_000

# A lumped-plasticity (pushover) hinge reuses the exact same duplicate-node +
# zeroLength technique as an ordinary moment release (_build_hinge) - rigid in
# translation/torsion (dofs 1-4, the same _HINGE_MATERIAL_TAG) but, unlike a
# release, dofs 5/6 (local My/Mz bending) get a real Steel01 moment-rotation
# material instead of being left unassigned (= perfectly free) - so this needs
# its own node/material tag ranges, kept clear of _HINGE_NODE_TAG_OFFSET's own
# range (a given element end only ever gets one or the other - see _build's
# "elif" between the two - but a distinct range avoids ever having to prove
# that if the two features' scopes drift apart later).
_PLASTIC_HINGE_NODE_TAG_OFFSET = 8_600_000
_PLASTIC_HINGE_MATERIAL_TAG_OFFSET = 8_700_000


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
            "프레임과 트러스가 혼합된 모델은 이 솔버에서 강성해석을 지원하지 않습니다. "
            "프레임만 또는 트러스만으로 모델을 구성하세요.",
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
        # A 2D frame joint has one rotation (Mz) to release; a 3D one has two
        # independent bending planes (My, Mz) - a drawn release frees both at once
        # (see _build's hinge zeroLength, which drops both bending dofs and keeps
        # axial/shear/torsion rigid), so each released end removes two equations
        # in 3D instead of one.
        released_dof_per_end = 1 if model.ndm == 2 else 2
        releases = _hinge_condition_equations(model) * released_dof_per_end
        degree = dof * members + reactions - dof * joints - releases

    if degree == 0:
        message = "정정구조입니다. 재료 및 단면 물성 없이 반력과 부재력을 계산할 수 있습니다."
    elif degree > 0:
        message = f"{degree}차 부정정 구조입니다. 재료 및 단면 강성을 정의해야 합니다."
    else:
        message = f"정정차수가 {degree}이므로 불안정 구조일 가능성이 있습니다. 지점 조건을 확인하세요."
    return DeterminacyCheck(system, degree, message)


class MaterialFreeStaticsSolver:
    """Calculate reactions and N/V/M forces for determinate structures (2D or 3D).

    Given real (E, A, I) - per element via ``Element.properties["E"/"A"/"I"]``,
    or a uniform fallback via ``solve(model, material=...)`` - it can also
    solve *indeterminate* 2D frames: determinate results never depend on
    stiffness, but an indeterminate structure's internal forces genuinely do,
    so equilibrium alone (unit placeholder stiffness) cannot give a physically
    meaningful answer for one. Every existing caller that never sets either
    keeps the exact original unit-stiffness, determinate-only behaviour
    unchanged.

    Indeterminate 3D frames are solved the same way, per element via
    ``Element.properties["E"/"A"/"G"/"J"/"Iy"/"Iz"]`` - there is deliberately
    no solve-wide fallback for the 3D case the way ``material`` is one for 2D
    (every 3D member must carry its own full property set), and geometric
    nonlinearity (P-Delta) stays 2D-only for now - a 3D member's ``geomTransf``
    is always built ``"Linear"`` regardless of what is requested, so
    ``solve()`` rejects a 3D request for anything else up front rather than
    silently ignoring it.
    """

    def solve(
        self,
        model: StructuralModel,
        material: tuple[float, float, float] | None = None,
        geometric_nonlinearity: str = "Linear",
    ) -> AnalysisResult:
        """``material`` is a (E, A, I) fallback applied to any 2D frame member
        that doesn't carry its own E/A/I in ``properties`` - real values here
        (per element or as this fallback) also give real (not unit-normalised)
        deflection for determinate structures, since deflection, unlike
        reactions and N/V/M, does scale with EI even when it is determinate.

        ``geometric_nonlinearity`` ("Linear" or "PDelta") switches every
        member's ``geomTransf`` between the ordinary linear one and OpenSees'
        native P-Delta transformation, which is the second-order (P-Delta)
        effect: unlike a determinate structure's *first-order* reactions and
        member forces (equilibrium alone, independent of stiffness), a P-Delta
        amplification is intrinsically stiffness-dependent even on an
        otherwise-determinate structure, so it always needs real E/A/I - there
        is no unit-placeholder shortcut for it the way there is for the
        first-order case.
        """
        if geometric_nonlinearity not in ("Linear", "PDelta"):
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"지원하지 않는 기하비선형 설정입니다: {geometric_nonlinearity}"],
            )
        if geometric_nonlinearity != "Linear" and model.ndm != 2:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=["3D 모델의 P-Delta(기하비선형) 해석은 아직 지원하지 않습니다."],
            )
        check = check_determinacy(model)
        needs_material = not check.can_solve_without_materials or geometric_nonlinearity != "Linear"
        truss_unit_stiffness = False
        displacement_stiffness = DisplacementStiffnessKind.PHYSICAL
        if check.system == "truss":
            # Pure truss policy (2D and 3D share this): real E/A on every
            # member → physical stiffness, including indeterminate systems.
            # Any missing/invalid E/A on a determinate truss still allows
            # equilibrium forces, but every member is built with the shared
            # unit placeholder so a mix of real and fake EA cannot produce
            # a displacement field that looks physical. An indeterminate
            # truss without a complete E/A set is refused, with the missing
            # members named, rather than solved under E=1, A=1.
            gaps = self._truss_stiffness_gaps(model)
            if geometric_nonlinearity != "Linear":
                return AnalysisResult(
                    status=AnalysisStatus.FAILED,
                    messages=[
                        check.message,
                        "트러스·케이블 모델의 P-Delta(기하비선형) 해석은 아직 지원하지 않습니다.",
                    ],
                )
            if gaps:
                if not check.can_solve_without_materials:
                    return AnalysisResult(
                        status=AnalysisStatus.FAILED,
                        messages=[
                            check.message,
                            "다음 부재에 유효한 재료·단면(E>0, A>0)이 필요합니다.",
                            *gaps,
                        ],
                    )
                truss_unit_stiffness = True
                displacement_stiffness = DisplacementStiffnessKind.UNIT_STIFFNESS
        elif needs_material:
            if check.system != "frame":
                # empty / unsupported / mixed: still no silent unit-stiffness
                # shortcut. Mixed is rejected even when every member happens
                # to carry properties - this solver has no combined frame+
                # truss stiffness path.
                if geometric_nonlinearity != "Linear":
                    return AnalysisResult(
                        status=AnalysisStatus.FAILED,
                        messages=[
                            check.message,
                            "트러스·케이블 모델의 P-Delta(기하비선형) 해석은 아직 지원하지 않습니다.",
                        ],
                    )
                return AnalysisResult(status=AnalysisStatus.FAILED, messages=[check.message])
            else:
                # ``material`` is a 2D-shaped (E, A, I) fallback - meaningless for a
                # 3D member's (E, A, G, J, Iy, Iz), so it can never stand in for a
                # missing per-element 3D property set the way it can in 2D.
                has_fallback = material is not None and model.ndm != 3
                if not has_fallback and not self._has_material_everywhere(model, check.system, model.ndm):
                    messages = [] if check.can_solve_without_materials else [check.message]
                    if geometric_nonlinearity != "Linear":
                        messages.append(
                            "P-Delta(기하비선형) 해석에는 모든 부재의 실제 재료·단면(E/A/I)이 "
                            "필요합니다 - 정정구조라도 2차효과는 강성에 좌우됩니다."
                        )
                    elif model.ndm == 3:
                        messages.append(
                            "부정정 3D 모델은 모든 부재에 실제 재료·단면(E/A/G/J/Iy/Iz)이 "
                            "필요합니다."
                        )
                    return AnalysisResult(status=AnalysisStatus.FAILED, messages=messages)

        ops.wipe()
        try:
            self._build(
                model,
                check.system,
                material,
                geometric_nonlinearity,
                truss_unit_stiffness=truss_unit_stiffness,
            )
            self._apply_loads(model, check.system)
            self._analyze(geometric_nonlinearity, has_multipoint_constraints=bool(model.rigid_diaphragms))
            return self._collect(
                model,
                check.system,
                check.message,
                material,
                displacement_stiffness=displacement_stiffness,
            )
        except (RuntimeError, ValueError, ops.OpenSeesError) as error:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"정역학 계산에 실패했습니다: {error}"],
            )
        finally:
            ops.wipe()

    def solve_nonlinear_static(
        self,
        model: StructuralModel,
        *,
        control_node: int,
        control_dof: int = 1,
        num_steps: int = 10,
        tolerance: float = 1.0e-6,
        max_iterations: int = 25,
        integrator_type: str = "LoadControl",
    ) -> AnalysisResult:
        """3D lumped-plasticity pushover: every beam-column element carrying a
        yield strength and a plastic section modulus (see
        ``apply_full_section_to_selection``'s "Fy"/"Zy"/"Zz" - only ever set
        for Rectangle/Circle/Pipe/Box/H-I Section, never Channel/Angle/
        Database/User Defined, see ``SectionProperties``) gets a Steel01
        moment-rotation hinge at both ends (``_build_plastic_hinge``); every
        other member stays purely elastic. This is intentionally the
        simplest real form of material nonlinearity, not full-spectrum
        fibre-section plasticity or concrete/RC support - see the feature
        audit that scoped it this way.

        Only ``integrator_type="LoadControl"`` (the settings dialog's own
        default) actually runs - Displacement Control and Arc-Length are
        collected by that dialog for a future step but have no target
        displacement/arc-length-radius field yet to drive them correctly, so
        this refuses rather than silently running the wrong increment shape.
        Pushes the model's own currently-defined loads to full scale (load
        factor 1.0) over ``num_steps`` Newton-Raphson increments, stopping
        early (without discarding the steps already converged) the moment
        one fails - typically because a hinge has driven the frame into a
        collapse mechanism.
        """
        if model.ndm != 3:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=["비선형 정적(Pushover) 해석은 현재 3D 모델만 지원합니다."],
            )
        if integrator_type != "LoadControl":
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[
                    f"{integrator_type} 적분법은 아직 실행에 연결되지 않았습니다 - "
                    "Load Control을 사용하세요."
                ],
            )
        check = check_determinacy(model)
        if check.system != "frame":
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[check.message, "비선형 정적 해석은 골조(프레임) 모델만 지원합니다."],
            )
        if not self._has_material_everywhere(model, "frame", 3):
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=["모든 부재에 실제 재료·단면(E/A/G/J/Iy/Iz)이 필요합니다."],
            )
        ops.wipe()
        try:
            self._build(model, "frame", None, "Linear", material_nonlinearity=True)
            self._apply_loads(model, "frame")
            messages, curve, convergence = self._analyze_nonlinear_static(
                control_node,
                control_dof,
                num_steps,
                tolerance,
                max_iterations,
                has_multipoint_constraints=bool(model.rigid_diaphragms),
            )
            result = self._collect(
                model, "frame", "비선형 정적(Pushover) 해석 결과입니다 (마지막으로 수렴한 스텝).", None
            )
            if not any(
                MaterialFreeStaticsSolver._plastic_hinge_capacities(element) is not None
                for element in model.elements.values()
            ):
                messages.append(
                    "항복강도(fy)가 설정된 강재 부재가 없어 전 구간 탄성으로 거동했습니다."
                )
            return AnalysisResult(
                status=result.status,
                node_results=result.node_results,
                element_results=result.element_results,
                messages=[*result.messages, *messages],
                load_displacement_curve=curve,
                convergence=convergence,
            )
        except (RuntimeError, ValueError, ops.OpenSeesError) as error:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"비선형 정적 해석에 실패했습니다: {error}"],
            )
        finally:
            ops.wipe()

    @staticmethod
    def _analyze_nonlinear_static(
        control_node: int,
        control_dof: int,
        num_steps: int,
        tolerance: float,
        max_iterations: int,
        *,
        has_multipoint_constraints: bool = False,
    ) -> tuple[list[str], tuple[LoadDisplacementPoint, ...], NonlinearConvergence]:
        ops.system("BandGeneral")
        ops.numberer("RCM")
        ops.constraints("Transformation" if has_multipoint_constraints else "Plain")
        ops.test("NormDispIncr", tolerance, max_iterations)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.0 / num_steps)
        ops.analysis("Static")
        fixed_nodes = [int(tag) for tag in ops.getFixedNodes()]
        messages: list[str] = []
        points: list[LoadDisplacementPoint] = []
        completed_steps = 0
        failed_step: int | None = None
        for step in range(1, num_steps + 1):
            if ops.analyze(1) != 0:
                failed_step = step
                messages.append(
                    f"스텝 {step}/{num_steps}에서 수렴하지 않았습니다 - 힌지가 붕괴 메커니즘에 "
                    "도달했거나 하중이 구조의 소성 강도를 초과했을 수 있습니다."
                )
                break
            completed_steps = step
            ops.reactions()
            # Reactions oppose the applied load - flipped so base shear grows
            # positive with the push, matching the script-based pushover
            # engine's own convention (infrastructure/opensees/
            # nonlinear_static_solver.py's _base_shear).
            base_shear = -sum(
                float(ops.nodeReaction(tag)[control_dof - 1])
                for tag in fixed_nodes
                if len(ops.nodeReaction(tag)) >= control_dof
            )
            control_disp = float(ops.nodeDisp(control_node, control_dof))
            points.append(LoadDisplacementPoint(step, control_disp, base_shear))
        if completed_steps == 0:
            raise RuntimeError("첫 스텝부터 수렴하지 않았습니다 - 모델과 하중을 확인하세요.")
        convergence = NonlinearConvergence(
            requested_steps=num_steps, completed_steps=completed_steps, failed_step=failed_step
        )
        return messages, tuple(points), convergence

    @staticmethod
    def _element_material(element: Element) -> tuple[float, float, float] | None:
        """(E, A, I) from ``element.properties`` for a 2D frame member, or
        ``None`` if any of the three is missing or not a real number - a
        truss/cable member's own (E, A) is a different shape entirely, see
        ``_element_material_truss``."""
        try:
            return (
                float(element.properties["E"]),
                float(element.properties["A"]),
                float(element.properties["I"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _element_material_truss(element: Element) -> tuple[float, float] | None:
        """(E, A) from ``element.properties`` for a truss/cable/tension-only/
        compression-only member (all built as an OpenSees ``truss`` element -
        see ``_element_family``) - or ``None`` if either is missing, not a
        real number, non-finite, or not strictly positive.

        Zero / negative / NaN stiffness would either crash OpenSees or
        silently fall back to the unit placeholder; both look like a physical
        displacement. ``apply_full_section_to_selection``
        (``canvas_property_application.py``) writes "E"/"A" for every element
        regardless of its axial-only behaviour, so this reads the exact same
        keys ``_element_material`` does for a frame member.
        """
        if MaterialFreeStaticsSolver._truss_stiffness_gap(element) is not None:
            return None
        return (float(element.properties["E"]), float(element.properties["A"]))

    @staticmethod
    def _truss_stiffness_gap(element: Element) -> str | None:
        """Human-readable reason this truss member cannot use real EA, or None."""
        problems: list[str] = []
        for key in ("E", "A"):
            if key not in element.properties:
                problems.append(f"{key} 없음")
                continue
            raw = element.properties[key]
            try:
                number = float(raw)
            except (TypeError, ValueError):
                problems.append(f"{key}={raw!r} (숫자가 아님)")
                continue
            if not math.isfinite(number) or number <= 0.0:
                problems.append(f"{key}={raw!r} (양수여야 함)")
        if problems:
            return f"부재 {element.tag}: {', '.join(problems)}"
        return None

    @staticmethod
    def _truss_stiffness_gaps(model: StructuralModel) -> list[str]:
        return [
            problem
            for element in model.elements.values()
            if (problem := MaterialFreeStaticsSolver._truss_stiffness_gap(element)) is not None
        ]


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
    def _element_material_3d(
        element: Element,
    ) -> tuple[float, float, float, float, float, float] | None:
        """(E, A, G, J, Iy, Iz) from ``element.properties`` - the same key
        convention ``model_inspector_panel.py``'s readiness check already
        expects for a 3D ``elasticBeamColumn`` - or ``None`` if any of the
        six is missing or not a real number."""
        try:
            return (
                float(element.properties["E"]),
                float(element.properties["A"]),
                float(element.properties["G"]),
                float(element.properties["J"]),
                float(element.properties["Iy"]),
                float(element.properties["Iz"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _resolve_material_3d(
        element: Element,
    ) -> tuple[float, float, float, float, float, float]:
        """(E, A, G, J, Iy, Iz) for one 3D element: its own properties, or the
        unit placeholder every determinate 3D call already relied on. Unlike
        2D's ``_resolve_material``, there is no solve-wide fallback tuple to
        fall through to first - see ``solve()``'s ``has_fallback`` guard,
        which already requires every element to carry its own full property
        set before an indeterminate 3D model reaches this far."""
        return MaterialFreeStaticsSolver._element_material_3d(element) or (
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
            1.0,
        )

    @staticmethod
    def _has_material_everywhere(model: StructuralModel, system: str, ndm: int = 2) -> bool:
        if system == "truss":
            return all(
                MaterialFreeStaticsSolver._element_material_truss(element) is not None
                for element in model.elements.values()
            )
        if system != "frame":
            return False
        reader = (
            MaterialFreeStaticsSolver._element_material_3d
            if ndm == 3
            else MaterialFreeStaticsSolver._element_material
        )
        return all(reader(element) is not None for element in model.elements.values())

    @staticmethod
    def _build(
        model: StructuralModel,
        system: str,
        material: tuple[float, float, float] | None = None,
        geometric_nonlinearity: str = "Linear",
        material_nonlinearity: bool = False,
        truss_unit_stiffness: bool = False,
    ) -> None:
        ndm = model.ndm
        ndf = (2 if system == "truss" else 3) if ndm == 2 else (3 if system == "truss" else 6)
        ops.model("basic", "-ndm", ndm, "-ndf", ndf)
        for node in model.nodes.values():
            coordinates = (node.x, node.y) if ndm == 2 else (node.x, node.y, node.z)
            ops.node(node.tag, *coordinates)
        inclined = [condition for condition in model.boundaries if condition.is_inclined]
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
        MaterialFreeStaticsSolver._apply_springs(model, ndm, ndf)
        if ndm == 3:
            for diaphragm in model.rigid_diaphragms:
                ops.rigidDiaphragm(diaphragm.perp_dirn, diaphragm.master_tag, *diaphragm.slave_tags)

        if system == "truss":
            ops.uniaxialMaterial("Elastic", _TRUSS_MATERIAL_TAG, 1.0)
            for element in model.elements.values():
                # When any member is missing E/A we deliberately ignore the
                # ones that do have it: mixing real EA with the unit
                # placeholder on a determinate truss still yields the right
                # forces (equilibrium) but a displacement field that is
                # physical on some members and fake on others.
                real_material = (
                    None
                    if truss_unit_stiffness
                    else MaterialFreeStaticsSolver._element_material_truss(element)
                )
                if real_material is None:
                    ops.element(
                        "truss",
                        element.tag,
                        element.node_i,
                        element.node_j,
                        1.0,
                        _TRUSS_MATERIAL_TAG,
                    )
                    continue
                elastic, area = real_material
                element_material_tag = _TRUSS_ELEMENT_MATERIAL_TAG_OFFSET + element.tag
                ops.uniaxialMaterial("Elastic", element_material_tag, elastic)
                ops.element(
                    "truss",
                    element.tag,
                    element.node_i,
                    element.node_j,
                    area,
                    element_material_tag,
                )
            return

        if ndm == 2:
            ops.geomTransf(geometric_nonlinearity, 1)
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

        plastic_hinge_capacities = (
            {
                tag: capacities
                for tag, element in model.elements.items()
                if (capacities := MaterialFreeStaticsSolver._plastic_hinge_capacities(element))
                is not None
            }
            if material_nonlinearity
            else {}
        )
        if any(element.release_count for element in model.elements.values()) or plastic_hinge_capacities:
            ops.uniaxialMaterial("Elastic", _HINGE_MATERIAL_TAG, _HINGE_STIFFNESS)
            # A node where every touching element releases there (a true shared
            # hinge - see _hinge_condition_equations) ends up with no element or
            # support giving its OWN bending rotations any stiffness at all: each
            # released element connects to its own dummy node instead (see
            # _build_hinge), never to this node's rotation directly. Left alone
            # that is a zero-pivot in the global stiffness matrix. The value is
            # physically meaningless either way (nothing reads it - the real
            # hinge rotations live on the dummy nodes), so pinning it to zero
            # only removes the singularity; it does not constrain the actual
            # bending behaviour, which the dummy nodes still carry freely.
            _released_ends_by_node, _rigid_nodes = _released_and_rigid_nodes(model)
            for node_tag in _orphan_joint_nodes_for_rotation_pin(model):
                ops.fix(node_tag, *_orphan_joint_rotation_fix_pattern(ndf))
        for element in model.elements.values():
            node_i = model.nodes[element.node_i]
            node_j = model.nodes[element.node_j]
            transf_tag = element.tag
            transf_args: list[object] = list(
                _reference_vector(node_i, node_j, element.local_axis_angle)
            )
            if any(element.offset_i) or any(element.offset_j):
                transf_args += ["-jntOffset", *element.offset_i, *element.offset_j]
            ops.geomTransf("Linear", transf_tag, *transf_args)
            end_i_tag = element.node_i
            end_j_tag = element.node_j
            hinge_capacities = plastic_hinge_capacities.get(element.tag)
            if element.moment_release_i:
                end_i_tag = MaterialFreeStaticsSolver._build_hinge(
                    element.tag, "i", node_i, node_j, element.local_axis_angle
                )
            elif hinge_capacities is not None:
                my_capacity, mz_capacity, hardening_ratio = hinge_capacities
                end_i_tag = MaterialFreeStaticsSolver._build_plastic_hinge(
                    element.tag, "i", node_i, node_j, my_capacity, mz_capacity, hardening_ratio,
                    element.local_axis_angle,
                )
            if element.moment_release_j:
                end_j_tag = MaterialFreeStaticsSolver._build_hinge(
                    element.tag, "j", node_i, node_j, element.local_axis_angle
                )
            elif hinge_capacities is not None:
                my_capacity, mz_capacity, hardening_ratio = hinge_capacities
                end_j_tag = MaterialFreeStaticsSolver._build_plastic_hinge(
                    element.tag, "j", node_i, node_j, my_capacity, mz_capacity, hardening_ratio,
                    element.local_axis_angle,
                )
            elastic, area, shear, torsion, inertia_y, inertia_z = (
                MaterialFreeStaticsSolver._resolve_material_3d(element)
            )
            ops.element(
                "elasticBeamColumn",
                element.tag,
                end_i_tag,
                end_j_tag,
                area,
                elastic,
                shear,
                torsion,
                inertia_y,
                inertia_z,
                transf_tag,
            )

    @staticmethod
    def _hinge_node_tag(element_tag: int, end: str) -> int:
        return _HINGE_NODE_TAG_OFFSET + element_tag * 10 + (0 if end == "i" else 1)

    @staticmethod
    def _build_hinge(
        element_tag: int, end: str, node_i, node_j, local_axis_angle: float = 0.0
    ) -> int:
        """Insert a duplicate node at the given end plus a zeroLength element that
        ties it back to the real end node in translation and torsion (both rigid)
        but leaves the two local bending rotations free - the 3D equivalent of a
        2D moment release. Returns the duplicate node's tag, to be used as this
        end's node in the real ``elasticBeamColumn`` call instead of the original.

        A plain ``equalDOF`` on global rotation dofs would be wrong for any member
        not aligned with a global axis: it would release whatever global rotation
        happens to be unconstrained rather than the member's own local bending
        directions, and could accidentally release torsion instead of bending. A
        ``-orient``ed zeroLength (the same technique already used for inclined
        supports in ``_fix_inclined``) rigidly ties translation (local dofs 1-3)
        and torsion (local dof 4) while leaving local dofs 5-6 (bending about the
        member's own y/z axes) with no assigned material - and therefore free -
        regardless of how the member is oriented in space.
        """
        real_node = node_i if end == "i" else node_j
        dummy_tag = MaterialFreeStaticsSolver._hinge_node_tag(element_tag, end)
        ops.node(dummy_tag, real_node.x, real_node.y, real_node.z)
        vector_x, vector_y = _hinge_local_axes(node_i, node_j, local_axis_angle)
        real_tag = node_i.tag if end == "i" else node_j.tag
        ops.element(
            "zeroLength",
            dummy_tag,
            real_tag,
            dummy_tag,
            "-mat",
            _HINGE_MATERIAL_TAG,
            _HINGE_MATERIAL_TAG,
            _HINGE_MATERIAL_TAG,
            _HINGE_MATERIAL_TAG,
            "-dir",
            1,
            2,
            3,
            4,
            "-orient",
            *vector_x,
            *vector_y,
        )
        return dummy_tag

    @staticmethod
    def _plastic_hinge_node_tag(element_tag: int, end: str) -> int:
        return _PLASTIC_HINGE_NODE_TAG_OFFSET + element_tag * 10 + (0 if end == "i" else 1)

    @staticmethod
    def _plastic_hinge_material_tags(element_tag: int, end: str) -> tuple[int, int]:
        base = _PLASTIC_HINGE_MATERIAL_TAG_OFFSET + (element_tag * 10 + (0 if end == "i" else 1)) * 2
        return base, base + 1

    @staticmethod
    def _plastic_hinge_capacities(element: Element) -> tuple[float, float, float] | None:
        """(My capacity, Mz capacity, strain-hardening ratio) for a lumped-
        plasticity hinge, or ``None`` when this element cannot get one -
        missing/non-positive yield strength, or a section with no plastic
        modulus recorded (Channel/Angle, Database, User Defined - see
        ``SectionProperties``' own docstring and
        ``apply_full_section_to_selection``'s "Fy"/"Zy"/"Zz" keys). Every
        element without a hinge here just keeps its ordinary elastic
        ``elasticBeamColumn`` behaviour, unchanged."""
        try:
            fy = float(element.properties["Fy"])
            zy = float(element.properties["Zy"])
            zz = float(element.properties["Zz"])
        except (KeyError, TypeError, ValueError):
            return None
        if fy <= 0.0 or zy <= 0.0 or zz <= 0.0:
            return None
        hardening_ratio = float(element.properties.get("StrainHardeningRatio", 0.02))
        return fy * zy, fy * zz, hardening_ratio

    @staticmethod
    def _build_plastic_hinge(
        element_tag: int,
        end: str,
        node_i,
        node_j,
        my_capacity: float,
        mz_capacity: float,
        hardening_ratio: float,
        local_axis_angle: float = 0.0,
    ) -> int:
        """Same duplicate-node + zeroLength construction as ``_build_hinge``,
        except local bending dofs 5 (My) and 6 (Mz) get a real ``Steel01``
        moment-rotation material (``Fy=capacity``, ``E0=_HINGE_STIFFNESS`` so
        the hinge stays effectively rigid - all the pre-yield flexibility
        comes from the elastic beam-column itself - ``b=hardening_ratio``)
        instead of being left unassigned. This is the whole of this
        solver's "material nonlinearity": a concentrated plastic hinge at
        each end of a qualifying steel member, not a fibre section - see the
        feature's own scoping note in solve_nonlinear_static's docstring.
        """
        real_node = node_i if end == "i" else node_j
        dummy_tag = MaterialFreeStaticsSolver._plastic_hinge_node_tag(element_tag, end)
        ops.node(dummy_tag, real_node.x, real_node.y, real_node.z)
        vector_x, vector_y = _hinge_local_axes(node_i, node_j, local_axis_angle)
        real_tag = node_i.tag if end == "i" else node_j.tag
        my_material_tag, mz_material_tag = MaterialFreeStaticsSolver._plastic_hinge_material_tags(
            element_tag, end
        )
        ops.uniaxialMaterial("Steel01", my_material_tag, my_capacity, _HINGE_STIFFNESS, hardening_ratio)
        ops.uniaxialMaterial("Steel01", mz_material_tag, mz_capacity, _HINGE_STIFFNESS, hardening_ratio)
        ops.element(
            "zeroLength",
            dummy_tag,
            real_tag,
            dummy_tag,
            "-mat",
            _HINGE_MATERIAL_TAG,
            _HINGE_MATERIAL_TAG,
            _HINGE_MATERIAL_TAG,
            _HINGE_MATERIAL_TAG,
            my_material_tag,
            mz_material_tag,
            "-dir",
            1,
            2,
            3,
            4,
            5,
            6,
            "-orient",
            *vector_x,
            *vector_y,
        )
        return dummy_tag

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
        zero-length element whose local axes are rotated to the support's angle
        about ``condition.angle_axis``. Giving that element a material only in the
        restrained local direction(s) restrains exactly that direction and leaves
        the others free to slide, which is what a roller resting on an inclined
        surface actually does.

        ``restraints[i]`` maps straight onto zeroLength local direction ``i + 1``
        for every ``i`` up to ``ndf`` - direction 1-3 are the rotated local
        x'/y'/z' translations, 4-6 (3D only) the same local frame's rotations,
        since a single ``-orient`` applies to all six uniformly. This is a strict
        generalisation of the old 2D-only ``min(2, ndf)`` + separate "index 2 is
        always global direction 3" special case: for ndf in {2, 3} the two are
        identical (verify: index 0,1 -> directions 1,2 either way; ndf == 3's
        index 2 -> direction 3 either way), so no existing 2D model's behaviour
        changes.
        """
        node = model.nodes[condition.node_tag]
        ground_tag = _INCLINED_SUPPORT_TAG_OFFSET + condition.node_tag
        ground_coordinates = (node.x, node.y) if model.ndm == 2 else (node.x, node.y, node.z)
        ops.node(ground_tag, *ground_coordinates)
        ops.fix(ground_tag, *((1,) * ndf))
        vector_x, vector_y = boundary_local_axes(condition.angle, condition.angle_axis)
        materials: list[int] = []
        directions: list[int] = []
        for index in range(min(len(condition.restraints), ndf)):
            if condition.restraints[index]:
                materials.append(_INCLINED_SUPPORT_MATERIAL_TAG)
                directions.append(index + 1)
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
    def _apply_springs(model: StructuralModel, ndm: int, ndf: int) -> None:
        """Elastic (finite-stiffness) supports: the same fully-fixed ground
        node + zeroLength trick ``_fix_inclined`` uses, but axis-aligned (no
        ``-orient`` needed - a spring is always defined along the global
        axes) and with a real stiffness per DOF instead of one shared rigid
        constant, so every sprung DOF mints its own ``uniaxialMaterial``.
        """
        material_tag = _SPRING_TAG_OFFSET
        for condition in model.boundaries:
            active = [
                (dof_index, stiffness)
                for dof_index, stiffness in enumerate(condition.spring_stiffnesses[:ndf])
                if stiffness
                and not (dof_index < len(condition.restraints) and condition.restraints[dof_index])
            ]
            if not active:
                continue
            node = model.nodes[condition.node_tag]
            ground_tag = _SPRING_TAG_OFFSET + condition.node_tag
            coordinates = (node.x, node.y) if ndm == 2 else (node.x, node.y, node.z)
            ops.node(ground_tag, *coordinates)
            ops.fix(ground_tag, *((1,) * ndf))
            materials: list[int] = []
            directions: list[int] = []
            for dof_index, stiffness in active:
                material_tag += 1
                ops.uniaxialMaterial("Elastic", material_tag, stiffness)
                materials.append(material_tag)
                directions.append(dof_index + 1)
            ops.element(
                "zeroLength", ground_tag, ground_tag, condition.node_tag,
                "-mat", *materials, "-dir", *directions,
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
        if system == "truss" and (model.element_loads or model.point_loads):
            raise ValueError("트러스 부재의 등분포하중은 절점하중으로 변환해 입력하세요.")
        if ndm == 3 and any(not load.is_uniform for load in model.element_loads):
            # A linearly-varying (trapezoidal) load needs _build's discretized-
            # member sub-elements (see _build_discretized_member), which only
            # ever builds 2D (x, y) sub-nodes - there is nothing to eleLoad a
            # 3D trapezoidal load's sub-tags onto. A plain uniform 3D load
            # needs no such discretization (OpenSees' own -beamUniform already
            # handles it directly on the one real element), so only the
            # trapezoidal case is still rejected here.
            raise ValueError(
                "3D 모델의 선형 변화(사다리꼴) 분포하중은 아직 지원하지 않습니다. "
                "등분포하중으로 입력하거나 절점하중으로 변환하세요."
            )
        for load in model.element_loads:
            if load.is_uniform:
                # A partial-span constant load (member_partial, confined to
                # xL1..xL2 rather than the whole member) maps directly onto
                # OpenSeesPy's own native -beamUniform trailing xL1/xL2
                # arguments (confirmed against the installed openseespy, both
                # 2D and 3D) - full-span loads (the overwhelming majority,
                # xL1/xL2 left at their (0.0, 1.0) default) omit them
                # entirely so this call is unchanged from before these two
                # fields existed.
                span_args = () if load.is_full_span else (load.xL1, load.xL2)
                if ndm == 3:
                    # wy/wz are the member's own local transverse axes (the
                    # same ones _reference_vector already fixed when the
                    # element was built - see its own docstring for how they
                    # are chosen), wx is local axial - OpenSeesPy's own 3D
                    # -beamUniform argument order.
                    ops.eleLoad(
                        "-ele", load.element_tag, "-type", "-beamUniform",
                        load.wy, load.wz, load.wx, *span_args,
                    )
                else:
                    ops.eleLoad(
                        "-ele", load.element_tag, "-type", "-beamUniform",
                        load.wy, load.wx, *span_args,
                    )
                continue
            # No native linearly-varying eleLoad exists (see _TRAPEZOID_SEGMENTS) -
            # _build already split this member into that many sub-elements, so
            # each sub-element gets OpenSees' own constant -beamUniform sampled at
            # the true w(x) value at its own midpoint. A midpoint sample equals
            # the segment's exact average for a linear w(x), so this reproduces
            # the exact resultant force per segment; only the within-segment
            # shape is approximated. 2D only - see the ndm == 3 rejection above.
            sub_tags = MaterialFreeStaticsSolver._trapezoid_sub_element_tags(load.element_tag)
            for segment, sub_tag in enumerate(sub_tags):
                midpoint = (segment + 0.5) / _TRAPEZOID_SEGMENTS
                wx_mid = load.wx + (load.wx_j - load.wx) * midpoint
                wy_mid = load.wy + (load.wy_j - load.wy) * midpoint
                ops.eleLoad("-ele", sub_tag, "-type", "-beamUniform", wy_mid, wx_mid)
        for point_load in model.point_loads:
            # Concentrated (member_point) force, native OpenSeesPy -beamPoint
            # (confirmed against the installed openseespy) - py/pz are the
            # member's own local transverse axes (same convention as the
            # -beamUniform call above), n is local axial, position is the
            # xL fraction (0..1) along whichever element/segment actually
            # carries this load (build_model() already resolved which one).
            # 2D has no out-of-plane pz component to pass. The 3D argument
            # order is (Py, Pz, xL, N) - confirmed by reproducing OpenSeesPy's
            # own "invalid xDivL" rejection independently of this solver: an
            # earlier version of this call passed (py, position, pz, n)
            # instead, silently swapping position/pz (see
            # tests/unit/test_solver_beam_point_argument_order.py, which pins
            # this order down with a monkeypatched ops.eleLoad so a future
            # edit can't reintroduce the swap without a failing test).
            if ndm == 3:
                ops.eleLoad(
                    "-ele", point_load.element_tag, "-type", "-beamPoint",
                    point_load.py, point_load.pz, point_load.position, point_load.n,
                )
            else:
                ops.eleLoad(
                    "-ele", point_load.element_tag, "-type", "-beamPoint",
                    point_load.py, point_load.position, point_load.n,
                )

    @staticmethod
    def _analyze(
        geometric_nonlinearity: str = "Linear", has_multipoint_constraints: bool = False
    ) -> None:
        ops.system("BandGeneral")
        ops.numberer("Plain")
        # "Plain" cannot express a multi-point constraint (rigidDiaphragm's
        # constraint equations tying several nodes together) at all - it
        # silently drops it and warns, which reproduces the exact numbers a
        # model with no diaphragm would have given (confirmed the hard way:
        # see tests/unit/test_material_free_statics_diaphragm.py). Every
        # other model here only ever has single-point ``fix`` constraints,
        # which "Transformation" handles identically, so switching is only
        # ever exercised - never risked - by a model with no diaphragm.
        ops.constraints("Transformation" if has_multipoint_constraints else "Plain")
        ops.integrator("LoadControl", 1.0)
        if geometric_nonlinearity == "Linear":
            ops.algorithm("Linear")
        else:
            # P-Delta is a genuine geometric nonlinearity - unlike the ordinary
            # linear case, equilibrium depends on the (unknown) deformed shape,
            # so a single un-iterated pass is not enough; Newton needs to
            # actually converge on it, even for a "single step" analysis.
            ops.test("NormDispIncr", 1.0e-8, 30)
            ops.algorithm("Newton")
        ops.analysis("Static")
        if ops.analyze(1) != 0:
            message = "구조가 불안정하거나 지점 조건이 충분하지 않습니다."
            if geometric_nonlinearity != "Linear":
                message += " P-Delta 해석이 수렴하지 않았다면 축력이 좌굴하중에 가까울 수 있습니다."
            raise RuntimeError(message)
        ops.reactions()

    @staticmethod
    def _collect(
        model: StructuralModel,
        system: str,
        message: str,
        material: tuple[float, float, float] | None = None,
        displacement_stiffness: DisplacementStiffnessKind = DisplacementStiffnessKind.PHYSICAL,
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
        messages = [message, "반력과 부재력은 평형조건으로 계산되었습니다."]
        if displacement_stiffness is DisplacementStiffnessKind.UNIT_STIFFNESS:
            # Forces remain equilibrium-correct; the enum (not this string) is
            # what the result UI keys off so a later Korean copy edit cannot
            # silently drop the banner.
            messages.append(UNIT_STIFFNESS_DISPLACEMENT_WARNING)
        return AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            node_results=node_results,
            element_results=element_results,
            messages=messages,
            displacement_stiffness=displacement_stiffness,
        )


def _element_family(element_type: str) -> str:
    return "truss" if "truss" in element_type.lower() else "frame"


def _released_and_rigid_nodes(model: StructuralModel) -> tuple[dict[int, int], set[int]]:
    """For every node: how many element-ends release there, and whether its
    rotation is otherwise anchored - either an unreleased element touches it, or
    its own support already restrains that rotation directly (a FIXED support
    has a real moment reaction; a PIN/roller does not, so a release there is
    genuinely uninformative, but a release at an otherwise-FIXED node still means
    something: the wall could resist a moment, the member just never delivers
    one). Shared by the determinacy count below and ``_build``'s
    orphaned-rotation fix, since both need exactly this same partition."""
    released_ends_by_node: dict[int, int] = {}
    rigid_nodes: set[int] = set()
    for element in model.elements.values():
        for node_tag, released in (
            (element.node_i, element.moment_release_i),
            (element.node_j, element.moment_release_j),
        ):
            if released:
                released_ends_by_node[node_tag] = released_ends_by_node.get(node_tag, 0) + 1
            else:
                rigid_nodes.add(node_tag)
    rotation_dof_indices = (2,) if model.ndm == 2 else (4, 5)
    for condition in model.boundaries:
        if any(
            index < len(condition.restraints) and condition.restraints[index]
            for index in rotation_dof_indices
        ):
            rigid_nodes.add(condition.node_tag)
    return released_ends_by_node, rigid_nodes


def _hinge_condition_equations(model: StructuralModel) -> int:
    """Classic hinge-counting rule: a joint where ``k`` members are ALL released
    there (a true shared hinge, e.g. the fixed-hinge-roller Gerber beam) adds
    ``k - 1`` condition equations, not ``k`` - the members share one collective
    relative-rotation freedom, not one each. A joint where at least one member
    stays rigid there still adds a full 1 per release: the rigid member anchors
    a well-defined node rotation, and each released member is independently free
    relative to it. A lone release at a node nothing else touches (e.g. a
    redundant release at an already-pinned support) adds 0 - that fact is
    already reflected in the support's own reaction count, and double-subtracting
    it would be wrong."""
    released_ends_by_node, rigid_nodes = _released_and_rigid_nodes(model)
    return sum(
        (count - 1) if node_tag not in rigid_nodes else count
        for node_tag, count in released_ends_by_node.items()
    )


def _reference_vector(node_i, node_j, angle_deg: float = 0.0) -> tuple[float, float, float]:
    """A ``vecxz`` for ``geomTransf`` that is never parallel to the member axis.

    The base vector is auto-picked (``auto_reference_vector`` - global Z works
    for every member except a vertical one, which falls back to global X) so
    a determinate 3D member (placeholder Iy=Iz=1.0) needs no further input:
    reactions and member forces never depend on which way "local y" versus
    "local z" actually points. Once an indeterminate 3D frame gives a member
    its own real, possibly asymmetric Iy/Iz (see ``_resolve_material_3d``),
    the auto-picked orientation is no longer guaranteed to match the
    section's actual strong/weak axis as drawn - ``angle_deg``
    (``Element.local_axis_angle``) is the escape hatch: it rotates the
    auto-picked vector about the member's own axis (``rotate_about_axis`` -
    Rodrigues' formula), letting a student dial in the orientation
    deliberately. ``angle_deg=0`` reproduces the old auto-picked vector
    exactly, so every caller that never sets it keeps behaving identically.
    The same rotation is what a 3D element load's wy/wz components (see
    ``_apply_loads``) end up local to - and what the 3D viewport's
    local-axis gizmo (``Quick3DSceneBridge``) previews, via the same two
    functions imported from ``core.domain.geometric_transform`` so the
    preview can never drift from what this actually solves.
    """
    dx = node_j.x - node_i.x
    dy = node_j.y - node_i.y
    dz = node_j.z - node_i.z
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    axis = (dx / length, dy / length, dz / length)
    reference = auto_reference_vector(axis)
    if angle_deg == 0.0:
        return reference
    return rotate_about_axis(reference, axis, math.radians(angle_deg))


def _orphan_joint_nodes_for_rotation_pin(model: StructuralModel) -> list[int]:
    """Joint-side nodes whose own rotational DOFs never enter any element stiffness.

    Every released end connects its ``elasticBeamColumn`` to a duplicate node
    instead of the original joint node, so a joint where *all* touching ends
    release there (and nothing else anchors rotation there) would otherwise
    carry three global rotations that no element reads - a zero pivot. The
    duplicate node still carries the real hinge through the zeroLength's free
    local bending directions 5-6, so pinning the joint node's rotations here
    removes only numerical orphans, not the physical release.
    """
    released_ends_by_node, rigid_nodes = _released_and_rigid_nodes(model)
    return sorted(tag for tag in released_ends_by_node if tag not in rigid_nodes)


def _orphan_joint_rotation_fix_pattern(ndf: int) -> tuple[int, ...]:
    """Restraints applied to orphan *joint-side* nodes only (never duplicate nodes).

    Translations stay free so zeroLength elements can still transfer axial and
    shear. All three global rotations are pinned because none of them receive
    stiffness from any frame element once every end there releases to its own
    duplicate - the old (0,0,0,0,1,1) pattern left one rotation free on members
    not aligned with global Y/Z (e.g. vertical columns left global Rx dangling).
    """
    if ndf == 6:
        return (0, 0, 0, 1, 1, 1)
    if ndf == 3:
        return (0, 0, 1)
    return (0,) * ndf


def _hinge_local_axes(
    node_i, node_j, angle_deg: float = 0.0
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """``(vecx, vecy)`` for a hinge zeroLength's ``-orient``: vecx is the member's
    own axial direction (so the rigid-material dofs 1-4 line up with axial, the two
    shears, and torsion), vecy is any unit vector exactly perpendicular to it (its
    exact direction within the cross-section doesn't matter here, since both
    bending dofs 5-6 are released together rather than one-at-a-time).

    Uses the same ``_reference_vector(..., angle_deg)`` input as the member's own
    ``geomTransf`` vecxz so the released bending directions cannot drift away from
    the beam's local y/z when ``local_axis_angle`` is non-zero."""
    dx = node_j.x - node_i.x
    dy = node_j.y - node_i.y
    dz = node_j.z - node_i.z
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    vecx = (dx / length, dy / length, dz / length)
    reference = _reference_vector(node_i, node_j, angle_deg)
    cross = (
        reference[1] * vecx[2] - reference[2] * vecx[1],
        reference[2] * vecx[0] - reference[0] * vecx[2],
        reference[0] * vecx[1] - reference[1] * vecx[0],
    )
    cross_length = math.sqrt(sum(component * component for component in cross)) or 1.0
    vecy = tuple(component / cross_length for component in cross)
    return vecx, vecy
