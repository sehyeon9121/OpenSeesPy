"""Run an analysis without coupling the caller to OpenSees infrastructure."""

from collections.abc import Callable

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.common import AnalysisModule


class RunAnalysisService:
    def __init__(self, modules: dict[AnalysisKind, AnalysisModule]) -> None:
        self._modules = modules

    def execute(
        self,
        request: AnalysisRequest,
        *,
        progress_callback: Callable[[int | None, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> AnalysisResult:
        module = self._modules.get(request.kind)
        if module is None:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"지원하지 않는 해석 종류입니다: {request.kind}"],
            )

        errors = module.validate(request)
        if errors:
            return AnalysisResult(status=AnalysisStatus.FAILED, messages=errors)

        if progress_callback is None and cancellation_requested is None:
            return module.run(request)
        return module.run(
            request,
            progress_callback=progress_callback,
            cancellation_requested=cancellation_requested,
        )
