"""Response spectrum analysis module: eigen solve + per-mode equivalent
static force + SRSS combination, delegated to an AnalysisRunner exactly like
ModalAnalysis - the kind/options on the request tell OpenSeesProcessRunner
which solver the worker subprocess should run."""

from collections.abc import Callable

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class ResponseSpectrumAnalysis(AnalysisModule):
    kind = AnalysisKind.RESPONSE_SPECTRUM

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def validate(self, request: AnalysisRequest) -> list[str]:
        errors: list[str] = []
        if request.source_path.suffix.lower() != ".py":
            errors.append("Python 파일이 필요합니다.")
        periods = request.options.get("periods") or []
        spectral_accelerations = request.options.get("spectral_accelerations") or []
        if len(periods) < 2:
            errors.append("응답스펙트럼 표에는 (주기, Sa) 쌍이 2개 이상 필요합니다.")
        elif len(periods) != len(spectral_accelerations):
            errors.append("응답스펙트럼 표의 주기와 Sa 개수가 일치하지 않습니다.")
        elif len(set(periods)) != len(periods):
            errors.append("응답스펙트럼 표의 주기 값이 중복됩니다.")
        num_modes = request.options.get("num_modes")
        if num_modes is not None and int(num_modes) <= 0:
            errors.append("계산할 모드 수는 1 이상이어야 합니다.")
        if not request.options.get("directions"):
            errors.append("가진 방향을 하나 이상 선택하세요.")
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
