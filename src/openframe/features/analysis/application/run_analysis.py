"""Run an analysis without coupling the caller to OpenSees infrastructure."""

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisRequest, AnalysisResult


class RunAnalysisService:
    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def execute(self, request: AnalysisRequest) -> AnalysisResult:
        return self._runner.run(request)

