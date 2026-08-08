"""Contract for executing an analysis request."""

from typing import Protocol

from openframe.core.domain import AnalysisRequest, AnalysisResult


class AnalysisRunner(Protocol):
    def run(self, request: AnalysisRequest) -> AnalysisResult: ...

