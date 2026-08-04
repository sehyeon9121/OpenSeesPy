"""Background MODEL loading task that keeps the Qt interface responsive."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from openframe.core.errors import OpenFrameError
from openframe.features.model.application.open_model import OpenModelService


class ModelLoadThread(QThread):
    loaded = Signal(object, str)
    failed = Signal(str)

    def __init__(self, service: OpenModelService, source: Path) -> None:
        super().__init__()
        self._service = service
        self._source = source

    def run(self) -> None:
        try:
            model = self._service.execute(self._source)
        except OpenFrameError as error:
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 - never crash the GUI event loop.
            self.failed.emit(f"예상하지 못한 모델 가져오기 오류: {error}")
        else:
            self.loaded.emit(model, str(self._source))
