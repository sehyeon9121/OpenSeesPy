"""GUI-side controller for the isolated OpenSees worker process."""

from openframe.core.domain import AnalysisRequest, AnalysisResult


class OpenSeesProcessRunner:
    def run(self, request: AnalysisRequest) -> AnalysisResult:
        raise NotImplementedError("worker 프로세스와 JSON 통신을 연결한 뒤 구현합니다.")
