"""Modal (eigenvalue) analysis for hand-drawn 2D frame models.

Unlike ``MaterialFreeStaticsSolver``, a natural frequency genuinely depends on
real stiffness and mass - there is no unit-placeholder shortcut the way there is
for a determinate structure's reactions and member forces. Every element must
therefore carry real E/A/I, and nodal mass is lumped from the same density (unit
weight) property the self-weight load already uses (see canvas_model_build.py's
``_self_weight_local``), converted to a true mass via ``m = W / g``.
"""

import math

import openseespy.opensees as ops

from openframe.core.domain.model import StructuralModel
from openframe.core.domain.results import AnalysisResult, AnalysisStatus, ModeShape, NodeResult
from openframe.features.analysis.statics.solver import (
    _INCLINED_SUPPORT_MATERIAL_TAG,
    _INCLINED_SUPPORT_STIFFNESS,
    MaterialFreeStaticsSolver,
    _element_family,
)

#: Standard gravity by length unit - the app's own unit-system combos
#: (core/domain/units.py LENGTH_UNITS) never include a gravity constant, since
#: nothing before this needed one: self-weight is applied as a force (density is
#: already a unit *weight*), and the imported-script modal solver requires the
#: user's own script to define ``ops.mass(...)`` directly. Converting a lumped
#: unit-weight mass to a true mass (consistent with whatever force/length units
#: the rest of the model uses) needs this, so it is introduced here.
_GRAVITY_BY_LENGTH_UNIT: dict[str, float] = {
    "m": 9.81,
    "mm": 9810.0,
    "cm": 981.0,
    "ft": 32.174,
    "in": 386.09,
}


class ModalStaticsSolver:
    """Eigenvalue analysis for a hand-drawn 2D frame with real section/material
    properties and lumped self-weight-derived nodal mass."""

    def solve(
        self,
        model: StructuralModel,
        *,
        num_modes: int = 3,
        length_unit: str = "m",
    ) -> AnalysisResult:
        if model.ndm != 2:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=["모드해석은 현재 2D 모델만 지원합니다."],
            )
        if not model.nodes or not model.elements:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=["절점과 부재를 먼저 작성하세요."],
            )
        if any(
            _element_family(element.element_type) != "frame"
            for element in model.elements.values()
        ):
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=["모드해석은 현재 트러스가 아닌 프레임 모델만 지원합니다."],
            )
        missing = sorted(
            tag
            for tag, element in model.elements.items()
            if MaterialFreeStaticsSolver._element_material(element) is None
        )
        if missing:
            listed = ", ".join(str(tag) for tag in missing)
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[
                    f"부재 {listed}에 재료·단면(E/A/I)이 입력되지 않았습니다. "
                    "모드해석에는 정정성과 무관하게 모든 부재의 실제 강성이 필요합니다."
                ],
            )
        if num_modes <= 0:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=["계산할 모드 수는 1 이상이어야 합니다."],
            )

        ops.wipe()
        try:
            self._build(model)
            gravity = _GRAVITY_BY_LENGTH_UNIT.get(length_unit, 9.81)
            total_mass = self._apply_mass(model, gravity)
            if total_mass <= 0.0:
                return AnalysisResult(
                    status=AnalysisStatus.FAILED,
                    messages=[
                        "절점 질량이 없습니다. 모드해석에는 부재의 단위중량(밀도)이 "
                        "필요합니다 - 부재 속성에서 밀도를 입력하세요."
                    ],
                )
            return self._analyze(model, num_modes)
        except (RuntimeError, ValueError, ops.OpenSeesError) as error:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"모드해석에 실패했습니다: {error}"],
            )
        finally:
            ops.wipe()

    @staticmethod
    def _build(model: StructuralModel) -> None:
        """Real-material-only 2D frame build: the loadless subset of
        ``MaterialFreeStaticsSolver._build`` - no trapezoid-load discretization
        (modal analysis carries no loads), real E/A/I only (no unit-placeholder
        fallback - already validated present for every element by ``solve``)."""
        ndf = 3
        ops.model("basic", "-ndm", 2, "-ndf", ndf)
        for node in model.nodes.values():
            ops.node(node.tag, node.x, node.y)

        inclined = [condition for condition in model.boundaries if condition.is_inclined]
        for condition in model.boundaries:
            if condition.is_inclined:
                continue
            restraints = tuple(int(value) for value in condition.restraints[:ndf])
            restraints += (0,) * (ndf - len(restraints))
            ops.fix(condition.node_tag, *restraints)
        if inclined:
            ops.uniaxialMaterial(
                "Elastic", _INCLINED_SUPPORT_MATERIAL_TAG, _INCLINED_SUPPORT_STIFFNESS
            )
            for condition in inclined:
                MaterialFreeStaticsSolver._fix_inclined(condition, ndf, model)

        ops.geomTransf("Linear", 1)
        for element in model.elements.values():
            elastic, area, inertia = MaterialFreeStaticsSolver._element_material(element)
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

    @staticmethod
    def _apply_mass(model: StructuralModel, gravity: float) -> float:
        """Lump each element's self-weight (density * A * length) half to each of
        its two nodes, converted to mass via m = W / g, translational dofs only
        (Ux, Uy) - the same "no rotational mass" convention as a standard lumped-
        mass frame model. Returns the total mass applied, so the caller can tell
        "no mass anywhere" (density/area never entered) from a real, if small,
        model."""
        node_mass: dict[int, float] = {}
        for element in model.elements.values():
            try:
                density = float(element.properties["density"])
                area = float(element.properties["A"])
            except (KeyError, TypeError, ValueError):
                continue
            if density == 0.0 or area == 0.0:
                continue
            start = model.nodes[element.node_i]
            end = model.nodes[element.node_j]
            length = math.hypot(end.x - start.x, end.y - start.y)
            if length <= 0.0:
                continue
            half_mass = (density * area * length / 2.0) / gravity
            node_mass[element.node_i] = node_mass.get(element.node_i, 0.0) + half_mass
            node_mass[element.node_j] = node_mass.get(element.node_j, 0.0) + half_mass

        for tag, mass in node_mass.items():
            if mass > 0.0:
                ops.mass(tag, mass, mass, 0.0)
        return sum(node_mass.values())

    @staticmethod
    def _analyze(model: StructuralModel, num_modes: int) -> AnalysisResult:
        node_tags = [int(tag) for tag in ops.getNodeTags()]
        ops.wipeAnalysis()
        ops.constraints("Transformation")
        ops.numberer("RCM")
        ops.system("BandGeneral")
        ops.algorithm("Linear")
        ops.integrator("LoadControl", 0.0)
        ops.analysis("Static")
        try:
            # See infrastructure/opensees/modal_solver.py for why the fallback
            # exists: the default ARPACK-based solver fails outright once the
            # requested mode count approaches the system's free-dof count, which
            # a small hand-drawn frame hits easily; -fullGenLapack has no such
            # constraint (just markedly slower, immaterial at this app's scale).
            eigenvalues = ops.eigen(num_modes)
        except Exception:  # noqa: BLE001 - OpenSeesPy's own C++-backed exceptions.
            try:
                eigenvalues = ops.eigen("-fullGenLapack", num_modes)
            except Exception as error:  # noqa: BLE001
                return AnalysisResult(
                    status=AnalysisStatus.FAILED,
                    messages=[
                        f"고유치 해석이 수렴하지 않았습니다: {error}. 모드 수를 줄이거나 "
                        "질량/지점 조건을 확인하세요."
                    ],
                )

        node_masses = {tag: [float(value) for value in ops.nodeMass(tag)] for tag in node_tags}
        ndf = 3
        total_mass_per_dof = [
            sum(masses[dof] if dof < len(masses) else 0.0 for masses in node_masses.values())
            for dof in range(ndf)
        ]

        mode_shapes: list[ModeShape] = []
        for index, raw_eigenvalue in enumerate(eigenvalues, start=1):
            eigenvalue = float(raw_eigenvalue)
            if eigenvalue <= 0.0:
                continue
            angular_frequency = math.sqrt(eigenvalue)
            frequency_hz = angular_frequency / (2.0 * math.pi)
            period = 1.0 / frequency_hz if frequency_hz > 0.0 else 0.0
            node_eigenvectors = {
                tag: [float(v) for v in ops.nodeEigenvector(tag, index)] for tag in node_tags
            }
            mode_shapes.append(
                ModeShape(
                    mode_number=index,
                    eigenvalue=eigenvalue,
                    angular_frequency=angular_frequency,
                    frequency_hz=frequency_hz,
                    period=period,
                    node_results={
                        tag: NodeResult(node_tag=tag, displacement=tuple(vector))
                        for tag, vector in node_eigenvectors.items()
                    },
                    mass_participation_ratio=tuple(
                        _mass_participation_ratios(
                            node_masses, node_eigenvectors, ndf, total_mass_per_dof
                        )
                    ),
                )
            )

        if not mode_shapes:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=["유효한 고유모드를 찾지 못했습니다. 질량과 지점 조건을 확인하세요."],
            )

        return AnalysisResult(status=AnalysisStatus.COMPLETED, mode_shapes=tuple(mode_shapes))


def _mass_participation_ratios(
    node_masses: dict[int, list[float]],
    node_eigenvectors: dict[int, list[float]],
    ndf: int,
    total_mass_per_dof: list[float],
) -> list[float]:
    """Same closed-form approach as infrastructure/opensees/modal_solver.py's
    identically-named helper: generalized modal mass m* = phi^T*M*phi,
    participation factor L_d = phi_d^T*M_d per direction, effective mass
    L_d^2/m* - computed straight from the lumped mass and raw eigenvector rather
    than assumed from the solver's own normalization convention."""
    modal_mass = 0.0
    participation = [0.0] * ndf
    for tag, masses in node_masses.items():
        vector = node_eigenvectors.get(tag, [])
        for dof in range(ndf):
            mass = masses[dof] if dof < len(masses) else 0.0
            value = vector[dof] if dof < len(vector) else 0.0
            modal_mass += mass * value * value
            participation[dof] += mass * value
    if modal_mass <= 0.0:
        return [0.0] * ndf
    ratios: list[float] = []
    for dof in range(ndf):
        total = total_mass_per_dof[dof]
        if total <= 0.0:
            ratios.append(0.0)
            continue
        effective_mass = participation[dof] ** 2 / modal_mass
        ratios.append(effective_mass / total)
    return ratios
