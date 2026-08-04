"""Background ANALYSIS execution task that keeps the Qt interface responsive."""

from PySide6.QtCore import QThread, Signal

from openframe.core.domain import AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.application.run_analysis import RunAnalysisService


class AnalysisRunThread(QThread):
    completed = Signal(object)

    def __init__(self, service: RunAnalysisService, request: AnalysisRequest) -> None:
        super().__init__()
        self._service = service
        self._request = request

    def run(self) -> None:
        try:
            result = self._service.execute(self._request)
        except Exception as error:  # noqa: BLE001 - never crash the GUI event loop.
            result = AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"예상하지 못한 해석 오류: {error}"],
            )
        self.completed.emit(result)
