"""Background ANALYSIS execution task that keeps the Qt interface responsive."""

import threading

from PySide6.QtCore import QThread, Signal

from openframe.core.domain import AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.application.run_analysis import RunAnalysisService


class AnalysisRunThread(QThread):
    completed = Signal(object)
    progress_changed = Signal(object, str)

    def __init__(self, service: RunAnalysisService, request: AnalysisRequest) -> None:
        super().__init__()
        self._service = service
        self._request = request
        self._cancellation_requested = threading.Event()

    def request_cancel(self) -> None:
        self._cancellation_requested.set()

    def _report_progress(self, value: int | None, stage: str) -> None:
        self.progress_changed.emit(value, stage)

    def run(self) -> None:
        try:
            result = self._service.execute(
                self._request,
                progress_callback=self._report_progress,
                cancellation_requested=self._cancellation_requested.is_set,
            )
        except Exception as error:  # noqa: BLE001 - never crash the GUI event loop.
            result = AnalysisResult(
                status=AnalysisStatus.FAILED,
                messages=[f"예상하지 못한 해석 오류: {error}"],
            )
        self.completed.emit(result)
