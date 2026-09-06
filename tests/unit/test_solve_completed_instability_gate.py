"""3D-only gate on _solve_completed() surfacing a diagnosed mechanism into
the results workspace.

Project policy: the 2D canvas page must never be touched by this feature -
shared code (ModelingInterfacePage, used by both dimensions) gates the new
behaviour behind self._start_in_3d rather than branching in solver.py or the
results-presentation widgets themselves (those stay dimension-agnostic, as
they already were before this feature).
"""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    InstabilityDiagnosticResult,
    MechanismMode,
)
from openframe.features.analysis.statics.solver import check_determinacy
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _page(*, start_in_3d: bool) -> ModelingInterfacePage:
    return ModelingInterfacePage(start_in_3d=start_in_3d, run_analysis_service=None)


def _mechanism_result() -> AnalysisResult:
    diagnostic = InstabilityDiagnosticResult(
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
    return AnalysisResult(
        status=AnalysisStatus.FAILED,
        messages=["정역학 계산에 실패했습니다: 선형정적해석이 수렴하지 않았습니다.", diagnostic.message],
        instability_diagnostic=diagnostic,
    )


def test_3d_mechanism_failure_pushes_result_into_results_workspace(app) -> None:
    page = _page(start_in_3d=True)
    page.results.show_result = MagicMock()
    page.results.set_model = MagicMock()
    model = page.canvas.build_model()

    page._solve_completed(model, check_determinacy(model), _mechanism_result())

    page.results.set_model.assert_called_once_with(model)
    page.results.show_result.assert_called_once()
    assert page.view_results_button.isEnabled()


def test_2d_mechanism_failure_does_not_touch_results_workspace(app) -> None:
    """Pinning the "2D untouched" guarantee as a regression test, not just a
    comment - the same shared _solve_completed() must be a no-op for 2D even
    when handed the exact same mechanism-carrying result."""
    page = _page(start_in_3d=False)
    page.results.show_result = MagicMock()
    page.results.set_model = MagicMock()
    model = page.canvas.build_model()

    page._solve_completed(model, check_determinacy(model), _mechanism_result())

    page.results.set_model.assert_not_called()
    page.results.show_result.assert_not_called()
    assert not page.view_results_button.isEnabled()


def test_3d_failure_without_mechanism_does_not_push_results(app) -> None:
    """A non-instability failure (e.g. missing material) must not force the
    results workspace open - only a genuinely diagnosed mechanism does."""
    page = _page(start_in_3d=True)
    page.results.show_result = MagicMock()
    page.results.set_model = MagicMock()
    model = page.canvas.build_model()
    result = AnalysisResult(status=AnalysisStatus.FAILED, messages=["재료가 없습니다."])

    page._solve_completed(model, check_determinacy(model), result)

    page.results.set_model.assert_not_called()
    page.results.show_result.assert_not_called()
    assert not page.view_results_button.isEnabled()


def test_3d_failure_with_unsuccessful_diagnostic_does_not_push_results(app) -> None:
    page = _page(start_in_3d=True)
    page.results.show_result = MagicMock()
    page.results.set_model = MagicMock()
    model = page.canvas.build_model()
    unsuccessful = InstabilityDiagnosticResult(
        message="불안정 진단 자체가 실패했습니다: test", diagnostic_success=False
    )
    result = AnalysisResult(status=AnalysisStatus.FAILED, instability_diagnostic=unsuccessful)

    page._solve_completed(model, check_determinacy(model), result)

    page.results.set_model.assert_not_called()
    page.results.show_result.assert_not_called()
    assert not page.view_results_button.isEnabled()
