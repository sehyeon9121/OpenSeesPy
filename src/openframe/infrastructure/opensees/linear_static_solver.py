"""Run a linear static analysis for an OpenSeesPy source and collect results."""

import math
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.element_load_collector import ElementLoadCollector
from openframe.infrastructure.opensees.script_execution import run_model_script


def _local_forces(element_tag: int) -> list[float]:
    """Return end forces along the member's own axes.

    ``eleForce`` reports forces in global coordinates, which swaps N and V on any
    member that is not horizontal, so the local-axis response is used instead.
    Elements that do not implement it report no end forces rather than global ones
    being silently misread as local.
    """
    response = ops.eleResponse(element_tag, "localForce")
    return [float(value) for value in response]


def _element_length(element_tag: int) -> float:
    """Return the member length, needed to evaluate forces between its two ends."""
    nodes = ops.eleNodes(element_tag)
    if len(nodes) < 2:
        return 0.0
    start = ops.nodeCoord(int(nodes[0]))
    end = ops.nodeCoord(int(nodes[1]))
    if len(start) < 2 or len(end) < 2:
        return 0.0
    return math.hypot(float(end[0]) - float(start[0]), float(end[1]) - float(start[1]))


def run_linear_static_analysis(source: Path) -> dict[str, Any]:
    """Build the model by executing ``source``, solve it, and return raw results.

    The script only builds: any analysis block it carries is suppressed, so the load
    patterns are applied exactly once, by the single static step below.
    """
    load_collector = ElementLoadCollector()
    load_collector.install()
    try:
        run_model_script(source)
    finally:
        load_collector.restore()

    node_tags = [int(tag) for tag in ops.getNodeTags()]
    element_tags = [int(tag) for tag in ops.getEleTags()]
    if not node_tags or not element_tags:
        raise RuntimeError(
            "해석할 모델이 비어 있습니다. 스크립트 끝에서 ops.wipe()로 모델을 지우고 "
            "있지 않은지 확인하세요."
        )

    ops.wipeAnalysis()
    ops.system("BandGeneral")
    ops.numberer("Plain")
    ops.constraints("Plain")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    if ops.analyze(1) != 0:
        raise RuntimeError("선형정적해석이 수렴하지 않았습니다.")
    ops.reactions()

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
            }
            for tag in element_tags
        ],
        "messages": _load_warnings(load_collector, element_tags),
    }


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
