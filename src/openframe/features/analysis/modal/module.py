"""Modal analysis module: eigenvalue solve, delegated to an AnalysisRunner exactly
like LinearStaticAnalysis - the kind/options on the request tell OpenSeesProcessRunner
which solver the worker subprocess should run."""

from collections.abc import Callable

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class ModalAnalysis(AnalysisModule):
    kind = AnalysisKind.MODAL

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def validate(self, request: AnalysisRequest) -> list[str]:
        errors: list[str] = []
        if request.source_path.suffix.lower() != ".py":
            errors.append("Python 파일이 필요합니다.")
        num_modes = request.options.get("num_modes")
        if num_modes is not None and int(num_modes) <= 0:
            errors.append("계산할 모드 수는 1 이상이어야 합니다.")
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
