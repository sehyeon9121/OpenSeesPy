"""Linear static analysis module placeholder."""

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class LinearStaticAnalysis(AnalysisModule):
    kind = AnalysisKind.LINEAR_STATIC

    def validate(self, request: AnalysisRequest) -> list[str]:
        return [] if request.source_path.suffix.lower() == ".py" else ["Python 파일이 필요합니다."]

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        raise NotImplementedError("OpenSees worker 연결 후 구현합니다.")

