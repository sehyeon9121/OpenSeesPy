import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisResult, AnalysisStatus, NodeResult, StructuralModel
from openframe.features.results.presentation.result_summary_panel import ResultSummaryPanel


def _panel() -> ResultSummaryPanel:
    QApplication.instance() or QApplication([])
    return ResultSummaryPanel()


def test_max_rotation_reads_rz_directly_in_2d() -> None:
    """처짐각 for a 2D node is just its third DOF (Rz) - the biggest |Rz|
    among all nodes, converted from the solver's radians to degrees."""
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(1, displacement=(0.0, 0.0, 0.01)),
            2: NodeResult(2, displacement=(0.0, -0.02, -0.05)),
        },
    )

    panel.show_result(result)

    expected_degrees = math.degrees(0.05)
    assert panel.metric_values["rotation"].text() == f"{expected_degrees:.4g}  °"


def test_max_rotation_combines_three_rotational_dof_in_3d() -> None:
    """A 3D node has Rx/Ry/Rz (indices 3..5) - no single one of them is "the"
    deflection angle, so the combined magnitude is used, the same way MAX
    DISPLACEMENT already combines Ux/Uy/Uz."""
    panel = _panel()
    panel.set_model(StructuralModel(ndm=3))
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.03, 0.04, 0.0)),
        },
    )

    panel.show_result(result)

    expected_degrees = math.degrees(math.hypot(0.03, 0.04, 0.0))
    assert panel.metric_values["rotation"].text() == f"{expected_degrees:.4g}  °"


def test_partial_nonlinear_result_remains_visible_and_is_not_labeled_completed() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(
        AnalysisResult(
            status=AnalysisStatus.PARTIAL,
            node_results={1: NodeResult(1, displacement=(0.02, 0.0, 0.0))},
        )
    )

    assert panel.status_badge.text() == "PARTIAL"
    assert panel.metric_values["displacement"].text().startswith("0.02")


def test_max_rotation_placeholder_before_any_result() -> None:
    panel = _panel()
    assert panel.metric_values["rotation"].text() == "—  °"
