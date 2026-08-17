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
        """Minimal "can we even attempt a run" gate - directly what SETUP's
        bottom precheck bar shows (see setup_workspace.py's own
        ``_refresh_precheck``). Deeper validation (direction/DOF range,
        Rayleigh mode validity, dt ordering, ...) lives in
        ``AnalysisSettingsPanel._update_precheck_th`` (live, as the user
        types) and ``time_history_solver.py`` (authoritative, at run time) -
        duplicating all of it here would just be a second place to drift out
        of sync with the options shape those two already own.
        """
        errors: list[str] = []
        options = request.options
        if request.source_path.suffix.lower() != ".py":
            errors.append("Python 파일이 필요합니다.")
        directions = options.get("directions") or []
        if not directions:
            errors.append("시간이력해석에는 활성화된 지진파 방향이 1개 이상 필요합니다.")
        elif any(not direction.get("path") for direction in directions):
            errors.append("지진파(가속도) 파일이 선택되지 않은 방향이 있습니다.")
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
