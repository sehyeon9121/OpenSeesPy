"""Run a linear static analysis for an OpenSeesPy source and collect results."""

import runpy
from pathlib import Path
from typing import Any

import openseespy.opensees as ops


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
                "local_forces": [float(value) for value in ops.eleForce(tag)],
            }
            for tag in element_tags
        ],
    }
