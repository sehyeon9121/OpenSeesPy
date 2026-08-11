"""Run an analysis without coupling the caller to OpenSees infrastructure."""

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.common import AnalysisModule


class RunAnalysisService:
    def __init__(self, modules: dict[AnalysisKind, AnalysisModule]) -> None:
        self._modules = modules

    def validate(self, request: AnalysisRequest) -> list[str]:
        """User-facing blocking errors for ``request`` - the same check
        :meth:`execute` runs before calling the module, exposed on its own so a
        SETUP pre-check can show them without actually running the analysis."""
        module = self._modules.get(request.kind)
        if module is None:
            return [f"지원하지 않는 해석 종류입니다: {request.kind}"]
        return module.validate(request)

    def execute(self, request: AnalysisRequest) -> AnalysisResult:
        errors = self.validate(request)
        if errors:
            return AnalysisResult(status=AnalysisStatus.FAILED, messages=errors)

        module = self._modules[request.kind]
        return module.run(request)
