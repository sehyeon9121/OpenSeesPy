"""Run an analysis without coupling the caller to OpenSees infrastructure."""

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.common import AnalysisModule


class RunAnalysisService:
    def __init__(self, modules: dict[AnalysisKind, AnalysisModule]) -> None:
        self._modules = modules

    def execute(self, request: AnalysisRequest) -> AnalysisResult:
        module = self._modules.get(request.kind)
        if module is None:
            return AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"지원하지 않는 해석 종류입니다: {request.kind}"],
            )

        errors = module.validate(request)
        if errors:
            return AnalysisResult(status=AnalysisStatus.FAILED, messages=errors)

        return module.run(request)
