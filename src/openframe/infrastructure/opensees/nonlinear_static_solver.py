"""Run an incremental nonlinear static (pushover) analysis for an OpenSeesPy source."""

import math
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.element_load_collector import ElementLoadCollector
from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script


def _local_forces(element_tag: int) -> list[float]:
    """Return end forces along the member's own axes (see linear_static_solver)."""
    response = ops.eleResponse(element_tag, "localForce")
    return [float(value) for value in response]


def _element_length(element_tag: int) -> float:
    nodes = ops.eleNodes(element_tag)
    if len(nodes) < 2:
        return 0.0
    start = ops.nodeCoord(int(nodes[0]))
    end = ops.nodeCoord(int(nodes[1]))
    if len(start) < 2 or len(end) < 2:
        return 0.0
    deltas = [float(b) - float(a) for a, b in zip(start, end, strict=False)]
    return math.sqrt(sum(value * value for value in deltas))


def _flexural_rigidity(collector: ModelCommandCollector, element_tag: int) -> float:
    properties = collector.elements.get(element_tag, {}).get("properties", {})
    try:
        inertia = properties.get("I", properties.get("Iz"))
        return float(properties["E"]) * float(inertia)
    except (KeyError, TypeError, ValueError):
        return 0.0


def _load_warnings(collector: ElementLoadCollector, element_tags: list[int]) -> list[str]:
    unsupported = sorted(collector.unsupported.intersection(element_tags))
    if not unsupported:
        return []
    listed = ", ".join(str(tag) for tag in unsupported)
    return [
        (
            f"부재 {listed}에 등분포하중이 아닌 구간하중이 적용되어, "
            "해당 부재의 다이어그램은 양단값만으로 표시됩니다."
        )
    ]


def run_nonlinear_static_analysis(
    source: Path,
    *,
    control_node: int,
    control_dof: int = 1,
    num_steps: int = 10,
    tolerance: float = 1.0e-6,
    max_iterations: int = 25,
    algorithm: str = "Newton",
    test_type: str = "NormDispIncr",
    system: str = "BandGeneral",
) -> dict[str, Any]:
    """Build the model by executing ``source``, then push it in ``num_steps`` equal
    load increments (LoadControl), tracking base shear vs. ``control_node``'s
    ``control_dof`` displacement at every converged step for a load-displacement
    (pushover) curve.

    Stops at the first step that fails to converge rather than raising: the curve up
    to that point, and the last converged state, are still meaningful results - a
    structure that stops converging partway through is telling you something real.
    """
    load_collector = ElementLoadCollector()
    # The section properties are only knowable from the element() call itself, and the
    # deflected shape between two nodes cannot be rebuilt without EI.
    property_collector = ModelCommandCollector()
    load_collector.install()
    property_collector.install()
    try:
        run_model_script(source)
    finally:
        load_collector.restore()
        property_collector.restore()

    node_tags = [int(tag) for tag in ops.getNodeTags()]
    element_tags = [int(tag) for tag in ops.getEleTags()]
    if not node_tags or not element_tags:
        raise RuntimeError(
            "해석할 모델이 비어 있습니다. 스크립트 끝에서 ops.wipe()로 모델을 지우고 "
            "있지 않은지 확인하세요."
        )
    if control_node not in node_tags:
        raise RuntimeError(f"CONTROL NODE {control_node}가 모델에 존재하지 않습니다.")
    if num_steps <= 0:
        raise RuntimeError("LOAD STEPS는 1 이상이어야 합니다.")

    fixed_nodes = [int(tag) for tag in ops.getFixedNodes()]

    ops.wipeAnalysis()
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system(system)
    ops.test(test_type, tolerance, max_iterations)
    ops.algorithm(algorithm)
    ops.integrator("LoadControl", 1.0 / num_steps)
    ops.analysis("Static")

    messages: list[str] = []
    curve: list[dict[str, float | int]] = []
    for step in range(1, num_steps + 1):
        if ops.analyze(1) != 0:
            messages.append(
                f"{step}번째 스텝에서 수렴하지 않았습니다 (총 {num_steps}스텝 중). "
                "그 이전까지 수렴한 결과만 표시됩니다."
            )
            break
        ops.reactions()
        # Reactions oppose the applied load (Newton's third law); base shear is read
        # as the resistance the structure develops, so the sign is flipped to grow
        # positive with the push instead of growing more negative.
        base_shear = -sum(
            float(ops.nodeReaction(tag)[control_dof - 1]) for tag in fixed_nodes
        )
        displacement = float(ops.nodeDisp(control_node, control_dof))
        curve.append(
            {"step": step, "control_displacement": displacement, "base_shear": base_shear}
        )

    if not curve:
        raise RuntimeError("첫 하중 스텝부터 수렴하지 않았습니다. 해석 설정을 조정해 보세요.")

    messages.extend(_load_warnings(load_collector, element_tags))

    return {
        "status": "completed",
        "node_results": [
            {
                "node_tag": tag,
                "displacement": [float(value) for value in ops.nodeDisp(tag)],
                "reaction": [float(value) for value in ops.nodeReaction(tag)],
            }
            for tag in node_tags
        ],
        "element_results": [
            {
                "element_tag": tag,
                "local_forces": _local_forces(tag),
                "length": _element_length(tag),
                "uniform_load": list(load_collector.uniform_loads.get(tag, (0.0, 0.0))),
                "flexural_rigidity": _flexural_rigidity(property_collector, tag),
            }
            for tag in element_tags
        ],
        "load_displacement_curve": curve,
        "messages": messages,
    }
