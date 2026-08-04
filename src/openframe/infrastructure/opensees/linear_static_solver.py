"""Run a linear static analysis for an OpenSeesPy source and collect results."""

import runpy
from pathlib import Path
from typing import Any

import openseespy.opensees as ops


def _local_forces(element_tag: int) -> list[float]:
    """Return end forces along the member's own axes.

    ``eleForce`` reports forces in global coordinates, which swaps N and V on any
    member that is not horizontal, so the local-axis response is used instead.
    Elements that do not implement it report no end forces rather than global ones
    being silently misread as local.
    """
    response = ops.eleResponse(element_tag, "localForce")
    return [float(value) for value in response]


def run_linear_static_analysis(source: Path) -> dict[str, Any]:
    """Build the model by executing ``source``, solve it, and return raw results."""
    runpy.run_path(str(source), run_name="__main__")

    node_tags = [int(tag) for tag in ops.getNodeTags()]
    element_tags = [int(tag) for tag in ops.getEleTags()]

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
            }
            for tag in element_tags
        ],
    }
