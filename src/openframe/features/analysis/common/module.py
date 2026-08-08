"""Contract implemented independently by every analysis type."""

from abc import ABC, abstractmethod

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult


class AnalysisModule(ABC):
    kind: AnalysisKind

    @abstractmethod
    def validate(self, request: AnalysisRequest) -> list[str]:
        """Return user-facing validation errors."""

    @abstractmethod
    def run(self, request: AnalysisRequest) -> AnalysisResult:
        """Execute the analysis through the OpenSees infrastructure."""

