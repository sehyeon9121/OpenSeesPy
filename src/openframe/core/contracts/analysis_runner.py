"""Contract for executing an analysis request."""

from collections.abc import Callable
from typing import Protocol

from openframe.core.domain import AnalysisRequest, AnalysisResult

ProgressCallback = Callable[[int | None, str], None]
CancellationCheck = Callable[[], bool]


class AnalysisRunner(Protocol):
    def run(
        self,
        request: AnalysisRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        cancellation_requested: CancellationCheck | None = None,
    ) -> AnalysisResult: ...
