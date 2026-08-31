import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    UNIT_STIFFNESS_DISPLACEMENT_WARNING,
    AnalysisResult,
    AnalysisStatus,
    DisplacementStiffnessKind,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.presentation.result_summary_panel import ResultSummaryPanel
from openframe.features.results.presentation.results_workspace import ResultsWorkspace


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


def test_inspector_shows_only_metrics_for_the_active_result_type() -> None:
    panel = _panel()
    panel.set_result_type("moment")

    assert not panel.metric_rows["moment"].isHidden()
    assert panel.metric_rows["displacement"].isHidden()
    assert panel.metric_rows["reaction"].isHidden()
    assert not panel.member_selector.isHidden()
    assert panel.learning_hint.isHidden()


def test_results_workspace_uses_a_narrow_context_inspector_shell() -> None:
    QApplication.instance() or QApplication([])
    workspace = ResultsWorkspace()

    assert workspace.result_types.minimumWidth() >= 200
    assert workspace.result_types.maximumWidth() <= 232
    assert workspace.summary.maximumWidth() <= 280
    workspace.set_result_type("reaction")
    assert not workspace.summary.metric_rows["reaction"].isHidden()
    assert workspace.summary.metric_rows["moment"].isHidden()


def test_unit_stiffness_warning_banner_appears_and_clears_on_rerun() -> None:
    QApplication.instance() or QApplication([])
    workspace = ResultsWorkspace()
    result_unit = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        displacement_stiffness=DisplacementStiffnessKind.UNIT_STIFFNESS,
        node_results={1: NodeResult(1, displacement=(0.02, 0.0, 0.0))},
    )
    result_physical = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        displacement_stiffness=DisplacementStiffnessKind.PHYSICAL,
        node_results={1: NodeResult(1, displacement=(0.001, 0.0, 0.0))},
    )

    workspace.show_result(result_unit)
    assert not workspace.stiffness_warning.isHidden()
    assert workspace.stiffness_warning.text() == UNIT_STIFFNESS_DISPLACEMENT_WARNING
    assert not workspace.viewport.relative_shape_badge.isHidden()
    assert "상대" in workspace.summary.metric_values["displacement"].text()

    workspace.show_result(result_physical)
    assert workspace.stiffness_warning.isHidden()
    assert workspace.viewport.relative_shape_badge.isHidden()
    assert "상대" not in workspace.summary.metric_values["displacement"].text()

    workspace.clear_result()
    assert workspace.stiffness_warning.isHidden()
