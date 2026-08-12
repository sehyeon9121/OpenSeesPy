"""Linear static analysis module: delegates execution to an AnalysisRunner."""

from collections.abc import Callable

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class LinearStaticAnalysis(AnalysisModule):
    kind = AnalysisKind.LINEAR_STATIC

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def validate(self, request: AnalysisRequest) -> list[str]:
        return [] if request.source_path.suffix.lower() == ".py" else ["Python 파일이 필요합니다."]

    def run(
        self,
        request: AnalysisRequest,
        *,
        progress_callback: Callable[[int | None, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> AnalysisResult:
        if progress_callback is None and cancellation_requested is None:
            return self._runner.run(request)
        return self._runner.run(
            request,
            progress_callback=progress_callback,
            cancellation_requested=cancellation_requested,
        )
