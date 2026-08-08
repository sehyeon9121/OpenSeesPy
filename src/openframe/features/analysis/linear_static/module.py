"""Linear static analysis module: delegates execution to an AnalysisRunner."""

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class LinearStaticAnalysis(AnalysisModule):
    kind = AnalysisKind.LINEAR_STATIC

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def validate(self, request: AnalysisRequest) -> list[str]:
        return [] if request.source_path.suffix.lower() == ".py" else ["Python 파일이 필요합니다."]

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        return self._runner.run(request)
