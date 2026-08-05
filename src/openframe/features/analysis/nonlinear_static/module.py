"""Nonlinear static analysis module: incremental LoadControl pushover, delegated to
an AnalysisRunner exactly like LinearStaticAnalysis - the kind/options on the request
tell OpenSeesProcessRunner which solver the worker subprocess should run."""

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class NonlinearStaticAnalysis(AnalysisModule):
    kind = AnalysisKind.NONLINEAR_STATIC

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def validate(self, request: AnalysisRequest) -> list[str]:
        errors: list[str] = []
        if request.source_path.suffix.lower() != ".py":
            errors.append("Python 파일이 필요합니다.")
        if request.options.get("control_node") is None:
            errors.append("비선형 정적해석에는 CONTROL NODE 지정이 필요합니다.")
        return errors

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        return self._runner.run(request)

