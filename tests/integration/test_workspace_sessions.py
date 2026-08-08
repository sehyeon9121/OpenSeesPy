import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.features.model.application.open_model import OpenModelService
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLES = Path(__file__).parents[2] / "examples"


def _load_model(window: MainWindow, source: Path, application: QApplication) -> None:
    window._start_model_load(source)
    thread = window._model_load_thread
    assert thread is not None
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(5_000, loop.quit)
    loop.exec()
    application.processEvents()


def test_recent_workspace_button_restores_the_selected_model() -> None:
    application = QApplication.instance() or QApplication([])
    service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    window = MainWindow(open_model_service=service)
    first = EXAMPLES / "portal_frame_2d.py"
    second = EXAMPLES / "simply_supported_beam_2d.py"

    _load_model(window, first, application)
    _load_model(window, second, application)
    window._show_start_workspace()

    assert len(window._workspace_sessions) == 2
    assert window.start_workspace._session_names[0].text() == second.name
    assert window.start_workspace._session_names[1].text() == first.name

    window.start_workspace._session_buttons[1].click()
    application.processEvents()

    assert window._current_model_source == first.resolve()
    assert window.workspace_stack.currentWidget() is window.workspace
    assert window.start_workspace._session_names[0].text() == first.name
    window.close()
