"""Solve statically determinate 2D textbook problems without material data.

For a stable determinate structure, reactions and member forces follow from
equilibrium and do not depend on EA or EI.  OpenSees is therefore given normalized
positive stiffness solely as a numerical mechanism.  Indeterminate structures are
rejected because their force distribution genuinely depends on member stiffness.
"""

import math
from dataclasses import dataclass

import openseespy.opensees as ops

from openframe.core.domain.model import StructuralModel
from openframe.core.domain.results import (
    AnalysisResult,
    AnalysisStatus,
    ElementResult,
    NodeResult,
)


@dataclass(frozen=True, slots=True)
class DeterminacyCheck:
    system: str
    degree: int
    message: str

    @property
    def can_solve_without_materials(self) -> bool:
        return self.degree == 0


def check_determinacy(model: StructuralModel) -> DeterminacyCheck:
    """Return the classical plane-frame or plane-truss determinacy count."""
    if model.ndm != 2:
        return DeterminacyCheck("unsupported", 1, "재료 없는 정역학 풀이는 현재 2D만 지원합니다.")
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
        reactions = sum(sum(condition.restraints[:2]) for condition in model.boundaries)
        degree = members + reactions - 2 * joints
    else:
        reactions = sum(sum(condition.restraints[:3]) for condition in model.boundaries)
        releases = sum(element.release_count for element in model.elements.values())
        degree = 3 * members + reactions - 3 * joints - releases

    if degree == 0:
        message = "정정구조입니다. 재료 및 단면 물성 없이 반력과 부재력을 계산할 수 있습니다."
    elif degree > 0:
        message = f"{degree}차 부정정 구조입니다. 재료 및 단면 강성을 정의해야 합니다."
    else:
        message = f"정정차수가 {degree}이므로 불안정 구조일 가능성이 있습니다. 지점 조건을 확인하세요."
    return DeterminacyCheck(system, degree, message)


class MaterialFreeStaticsSolver:
    """Calculate reactions and N/V/M forces for determinate planar structures."""

    def solve(self, model: StructuralModel) -> AnalysisResult:
        check = check_determinacy(model)
        if not check.can_solve_without_materials:
            return AnalysisResult(status=AnalysisStatus.FAILED, messages=[check.message])

        ops.wipe()
        try:
            self._build(model, check.system)
            self._apply_loads(model, check.system)
            self._analyze()
            return self._collect(model, check.system, check.message)
        except (RuntimeError, ValueError, ops.OpenSeesError) as error:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"정역학 계산에 실패했습니다: {error}"],
            )
        finally:
            ops.wipe()

    @staticmethod
    def _build(model: StructuralModel, system: str) -> None:
        ndf = 2 if system == "truss" else 3
        ops.model("basic", "-ndm", 2, "-ndf", ndf)
        for node in model.nodes.values():
            ops.node(node.tag, node.x, node.y)
        for condition in model.boundaries:
            restraints = tuple(int(value) for value in condition.restraints[:ndf])
            restraints += (0,) * (ndf - len(restraints))
            ops.fix(condition.node_tag, *restraints)

        if system == "truss":
            for element in model.elements.values():
                ops.element("truss", element.tag, element.node_i, element.node_j, 1.0, 1.0)
            return

        ops.geomTransf("Linear", 1)
        for element in model.elements.values():
            arguments: list[object] = [
                "elasticBeamColumn",
                element.tag,
                element.node_i,
                element.node_j,
                1.0,
                1.0,
                1.0,
                1,
            ]
            release_code = int(element.moment_release_i) + 2 * int(element.moment_release_j)
            if release_code:
                arguments += ["-release", release_code]
            ops.element(*arguments)

    @staticmethod
    def _apply_loads(model: StructuralModel, system: str) -> None:
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ndf = 2 if system == "truss" else 3
        for load in model.nodal_loads:
            values = tuple(load.values[:ndf]) + (0.0,) * max(0, ndf - len(load.values))
            ops.load(load.node_tag, *values)
        if system == "truss" and model.element_loads:
            raise ValueError("트러스 부재의 등분포하중은 절점하중으로 변환해 입력하세요.")
        for load in model.element_loads:
            ops.eleLoad("-ele", load.element_tag, "-type", "-beamUniform", load.wy, load.wx)

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
    def _collect(model: StructuralModel, system: str, message: str) -> AnalysisResult:
        node_results = {
            tag: NodeResult(
                node_tag=tag,
                displacement=tuple(float(value) for value in ops.nodeDisp(tag)),
                reaction=tuple(float(value) for value in ops.nodeReaction(tag)),
            )
            for tag in model.nodes
        }
        uniform_loads = {
            load.element_tag: (load.wx, load.wy) for load in model.element_loads
        }
        element_results: dict[int, ElementResult] = {}
        for tag, element in model.elements.items():
            node_i = model.nodes[element.node_i]
            node_j = model.nodes[element.node_j]
            length = math.hypot(node_j.x - node_i.x, node_j.y - node_i.y)
            if system == "truss":
                axial_response = ops.eleResponse(tag, "axialForce")
                axial = float(axial_response[0]) if axial_response else 0.0
                local_force = (-axial, 0.0, 0.0, axial, 0.0, 0.0)
            else:
                local_force = ops.eleResponse(tag, "localForce")
                if not local_force:
                    local_force = ops.eleForce(tag)
            element_results[tag] = ElementResult(
                element_tag=tag,
                local_forces=tuple(float(value) for value in local_force),
                length=length,
                uniform_load=uniform_loads.get(tag, (0.0, 0.0)),
            )
        return AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            node_results=node_results,
            element_results=element_results,
            messages=[message, "반력과 부재력은 평형조건으로 계산되었습니다."],
        )


def _element_family(element_type: str) -> str:
    return "truss" if "truss" in element_type.lower() else "frame"
