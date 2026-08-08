from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees.linear_static_solver import run_linear_static_analysis

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "portal_frame_2d.py"


def test_solves_portal_frame_and_balances_reactions() -> None:
    try:
        results = run_linear_static_analysis(EXAMPLE_MODEL)
    finally:
        ops.wipe()

    assert results["status"] == "completed"
    assert len(results["node_results"]) == 4
    assert len(results["element_results"]) == 3

    total_rx = sum(node["reaction"][0] for node in results["node_results"])
    total_ry = sum(node["reaction"][1] for node in results["node_results"])
    assert total_rx == pytest.approx(-20.0, abs=1e-6)
    assert total_ry == pytest.approx(30.0, abs=1e-6)

    element_forces = {item["element_tag"]: item["local_forces"] for item in results["element_results"]}
    assert len(element_forces[1]) == 6
