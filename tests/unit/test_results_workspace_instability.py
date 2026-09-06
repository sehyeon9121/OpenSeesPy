"""ResultsWorkspace.show_result() auto-selecting the mechanism_modes result
type - only when a failed result actually diagnosed a mechanism, never for
a clean completed result, a diagnostic that could not run, or one that ran
but found no mechanism."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Element,
    InstabilityDiagnosticResult,
    MechanismMode,
    Node,
    StructuralModel,
)
from openframe.features.results.presentation.results_workspace import ResultsWorkspace


def _model() -> StructuralModel:
    return StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )


def _workspace() -> ResultsWorkspace:
    QApplication.instance() or QApplication([])
    workspace = ResultsWorkspace()
    workspace.set_model(_model())
    return workspace


def _mechanism_diagnostic() -> InstabilityDiagnosticResult:
    return InstabilityDiagnosticResult(
        mechanism_count=1,
        modes=(
            MechanismMode(
                mode_number=1,
                eigenvalue=1e-15,
                mode_shape={1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)},
                dominant_dofs=("n2:Ux=+1.00",),
                residual=1e-14,
            ),
        ),
        message="구조가 불안정합니다 - 강성행렬에서 메커니즘 1개가 감지되었습니다.",
        matrix_size=6,
        diagnostic_success=True,
    )


def test_mechanism_result_auto_selects_mechanism_modes() -> None:
    workspace = _workspace()
    workspace.show_result(
        AnalysisResult(status=AnalysisStatus.FAILED, instability_diagnostic=_mechanism_diagnostic())
    )
    assert workspace.result_types.buttons["mechanism_modes"].isChecked()
    assert not workspace.result_types.sections["instability"].isHidden()


def test_completed_result_does_not_select_mechanism_modes() -> None:
    workspace = _workspace()
    workspace.show_result(AnalysisResult(status=AnalysisStatus.COMPLETED))
    assert not workspace.result_types.buttons["mechanism_modes"].isChecked()
    assert workspace.result_types.sections["instability"].isHidden()


def test_failed_result_without_diagnostic_does_not_select_mechanism_modes() -> None:
    workspace = _workspace()
    workspace.show_result(AnalysisResult(status=AnalysisStatus.FAILED))
    assert not workspace.result_types.buttons["mechanism_modes"].isChecked()
    assert workspace.result_types.sections["instability"].isHidden()


def test_diagnostic_that_could_not_run_does_not_select_mechanism_modes() -> None:
    workspace = _workspace()
    unsuccessful = InstabilityDiagnosticResult(
        message="불안정 진단 자체가 실패했습니다: test", diagnostic_success=False
    )
    workspace.show_result(
        AnalysisResult(status=AnalysisStatus.FAILED, instability_diagnostic=unsuccessful)
    )
    assert not workspace.result_types.buttons["mechanism_modes"].isChecked()
    assert workspace.result_types.sections["instability"].isHidden()


def test_diagnostic_with_zero_mechanisms_does_not_select_mechanism_modes() -> None:
    workspace = _workspace()
    zero_mechanism = InstabilityDiagnosticResult(
        mechanism_count=0,
        message="강성행렬에서 메커니즘이 확인되지 않았습니다.",
        matrix_size=6,
        diagnostic_success=True,
    )
    workspace.show_result(
        AnalysisResult(status=AnalysisStatus.FAILED, instability_diagnostic=zero_mechanism)
    )
    assert not workspace.result_types.buttons["mechanism_modes"].isChecked()
    assert workspace.result_types.sections["instability"].isHidden()


def test_clear_result_hides_stale_instability_section() -> None:
    workspace = _workspace()
    workspace.show_result(
        AnalysisResult(status=AnalysisStatus.FAILED, instability_diagnostic=_mechanism_diagnostic())
    )
    assert not workspace.result_types.sections["instability"].isHidden()

    workspace.clear_result()
    assert workspace.result_types.sections["instability"].isHidden()


def test_set_model_clears_stale_instability_section() -> None:
    workspace = _workspace()
    workspace.show_result(
        AnalysisResult(status=AnalysisStatus.FAILED, instability_diagnostic=_mechanism_diagnostic())
    )
    assert not workspace.result_types.sections["instability"].isHidden()

    workspace.set_model(_model())
    assert workspace.result_types.sections["instability"].isHidden()
