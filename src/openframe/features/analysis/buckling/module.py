"""Elastic eigenvalue buckling analysis module: two linear static solves plus a
SciPy generalized eigenproblem, delegated to an AnalysisRunner exactly like
ModalAnalysis - the kind/options on the request tell OpenSeesProcessRunner which
solver the worker subprocess should run."""

from collections.abc import Callable

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule

#: Mirrors buckling_solver.py's own allowed set exactly - officially restricted
#: to P-Delta for now (Corotational/"From Model" have not been separately
#: validated - see that module's _GEOMETRIC_TRANSFORM_TYPES comment). "Linear"
#: is excluded for a different, permanent reason (produces zero geometric
#: stiffness by construction, so it can only ever fail with a much less clear
#: reason) and gets its own message below.
_GEOMETRIC_TRANSFORM_TYPES = {"PDelta"}
_NOT_YET_SUPPORTED_TRANSFORM_TYPES = {"Corotational", "UseModelDefinition"}


class BucklingAnalysis(AnalysisModule):
    kind = AnalysisKind.BUCKLING

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def validate(self, request: AnalysisRequest) -> list[str]:
        errors: list[str] = []
        options = request.options
        if request.source_path.suffix.lower() != ".py":
            errors.append("Python 파일이 필요합니다.")
        num_modes = options.get("num_modes")
        if num_modes is not None and int(num_modes) <= 0:
            errors.append("NUMBER OF MODES 값은 0보다 커야 합니다.")
        reference_load_scale = options.get("reference_load_scale")
        if reference_load_scale is not None and float(reference_load_scale) == 0:
            errors.append("REFERENCE LOAD SCALE은 0이 될 수 없습니다.")
        eigenvalue_tolerance = options.get("eigenvalue_tolerance")
        if eigenvalue_tolerance is not None and float(eigenvalue_tolerance) <= 0:
            errors.append("EIGENVALUE TOLERANCE 값은 0보다 커야 합니다.")
        geometric_transform_type = options.get("geometric_transform_type")
        if geometric_transform_type is not None:
            if geometric_transform_type == "Linear":
                errors.append(
                    "GEOMETRIC TRANSFORMATION에 Linear는 사용할 수 없습니다 - 기하강성을 "
                    "만들지 않아 좌굴해석이 성립하지 않습니다."
                )
            elif geometric_transform_type in _NOT_YET_SUPPORTED_TRANSFORM_TYPES:
                errors.append(
                    f"GEOMETRIC TRANSFORMATION은 현재 P-Delta만 정식 지원합니다. "
                    f"'{geometric_transform_type}'은(는) 추가 검증 후 지원 예정입니다."
                )
            elif geometric_transform_type not in _GEOMETRIC_TRANSFORM_TYPES:
                errors.append(
                    f"지원하지 않는 geometric_transform_type 설정입니다: {geometric_transform_type}"
                )
        return errors

    def run(
        self,
        request: AnalysisRequest,
        *,
        progress_callback: Callable[[int | None, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> AnalysisResult:
        if progress_callback is None and cancellation_requested is None:
            return self._runner.run(request)
        return self._runner.run(
            request,
            progress_callback=progress_callback,
            cancellation_requested=cancellation_requested,
        )
