"""A script's own analysis block must never run instead of the application's."""

from pathlib import Path

import openseespy.opensees as ops
import pytest

from openframe.infrastructure.opensees.linear_static_solver import run_linear_static_analysis
from openframe.infrastructure.opensees.script_execution import run_model_script

EXAMPLES = Path(__file__).parents[2] / "examples"
PLAIN_MODEL = EXAMPLES / "portal_frame_2d.py"
SELF_SOLVING_MODEL = EXAMPLES / "portal_frame_with_analysis_2d.py"


def _node_result(results: dict, node_tag: int) -> dict:
    return next(item for item in results["node_results"] if item["node_tag"] == node_tag)


def test_importing_a_self_solving_script_builds_without_solving() -> None:
    run_model_script(SELF_SOLVING_MODEL)

    assert [int(tag) for tag in ops.getNodeTags()] == [1, 2, 3, 4]
    assert [int(tag) for tag in ops.getEleTags()] == [1, 2, 3]
    # Every displacement stays zero because the script's analyze() call was inert.
    assert all(value == 0.0 for tag in ops.getNodeTags() for value in ops.nodeDisp(int(tag)))


def test_self_solving_script_is_analysed_exactly_once() -> None:
    plain = run_linear_static_analysis(PLAIN_MODEL)
    self_solving = run_linear_static_analysis(SELF_SOLVING_MODEL)

    for node_tag in (1, 2, 3, 4):
        expected = _node_result(plain, node_tag)
        actual = _node_result(self_solving, node_tag)
        assert actual["displacement"] == pytest.approx(expected["displacement"], rel=1e-9)
        assert actual["reaction"] == pytest.approx(expected["reaction"], rel=1e-9, abs=1e-9)

    # Reactions must balance the applied load; a doubled run reports them as zero.
    support_fx = sum(_node_result(self_solving, tag)["reaction"][0] for tag in (1, 2))
    support_fy = sum(_node_result(self_solving, tag)["reaction"][1] for tag in (1, 2))
    assert support_fx == pytest.approx(-20.0, abs=1e-6)
    assert support_fy == pytest.approx(30.0, abs=1e-6)


def test_script_that_wipes_at_the_end_reports_an_empty_model(tmp_path: Path) -> None:
    source = tmp_path / "wiped_model.py"
    source.write_text(
        SELF_SOLVING_MODEL.read_text(encoding="utf-8") + "\nops.wipe()\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="비어 있습니다"):
        run_linear_static_analysis(source)
