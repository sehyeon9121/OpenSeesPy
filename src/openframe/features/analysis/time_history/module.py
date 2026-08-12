"""Time-history analysis module: transient integration, delegated to an
AnalysisRunner exactly like the other analysis kinds - the kind/options on the
request tell OpenSeesProcessRunner which solver the worker subprocess should
run."""

from collections.abc import Callable

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class TimeHistoryAnalysis(AnalysisModule):
    kind = AnalysisKind.TIME_HISTORY

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def validate(self, request: AnalysisRequest) -> list[str]:
        errors: list[str] = []
        options = request.options
        if request.source_path.suffix.lower() != ".py":
            errors.append("Python 파일이 필요합니다.")
        if not options.get("ground_motion_path"):
            errors.append("시간이력해석에는 지진파(가속도) 파일이 필요합니다.")
        direction = options.get("direction")
        if direction is not None and int(direction) <= 0:
            errors.append("DIRECTION 값은 1 이상이어야 합니다.")
        damping_ratio = options.get("damping_ratio")
        if damping_ratio is not None and float(damping_ratio) < 0:
            errors.append("감쇠비는 0 이상이어야 합니다.")
        return errors

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
