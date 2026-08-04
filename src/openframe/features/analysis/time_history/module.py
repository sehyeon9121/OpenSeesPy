"""Reserved module for transient time-history analysis."""

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class TimeHistoryAnalysis(AnalysisModule):
    kind = AnalysisKind.TIME_HISTORY

    def validate(self, request: AnalysisRequest) -> list[str]:
        return []

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        raise NotImplementedError("시간이력해석 단계에서 구현합니다.")

