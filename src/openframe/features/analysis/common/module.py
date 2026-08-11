"""Contract implemented independently by every analysis type."""

from abc import ABC, abstractmethod
from collections.abc import Callable

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult


class AnalysisModule(ABC):
    kind: AnalysisKind

    @abstractmethod
    def validate(self, request: AnalysisRequest) -> list[str]:
        """Return user-facing validation errors."""

    @abstractmethod
    def run(
        self,
        request: AnalysisRequest,
        *,
        progress_callback: Callable[[int | None, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> AnalysisResult:
        """Execute the analysis through the OpenSees infrastructure."""
