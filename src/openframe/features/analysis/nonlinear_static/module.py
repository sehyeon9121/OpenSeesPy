"""Reserved module for material and geometric nonlinear static analysis."""

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class NonlinearStaticAnalysis(AnalysisModule):
    kind = AnalysisKind.NONLINEAR_STATIC

    def validate(self, request: AnalysisRequest) -> list[str]:
        return []

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        raise NotImplementedError("비선형 정적해석 단계에서 구현합니다.")

