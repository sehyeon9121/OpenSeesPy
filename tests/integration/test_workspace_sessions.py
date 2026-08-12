import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.core.domain import UnitSystem
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
    window = MainWindow(
        open_model_service=service,
        imported_unit_resolver=lambda _source: UnitSystem("kN", "m"),
    )
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
    assert window.workspace_stack.currentWidget() is window.model_workspace_page
    assert window.start_workspace._session_names[0].text() == first.name
    window.close()


def test_switching_workspaces_restores_each_imported_models_native_units() -> None:
    application = QApplication.instance() or QApplication([])
    service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    first = EXAMPLES / "portal_frame_2d.py"
    second = EXAMPLES / "simply_supported_beam_2d.py"

    def resolve_units(source: Path) -> UnitSystem:
        return UnitSystem("kip", "in") if source.name == first.name else UnitSystem("kN", "m")

    window = MainWindow(
        open_model_service=service,
        imported_unit_resolver=resolve_units,
    )
    _load_model(window, first, application)
    _load_model(window, second, application)

    assert window.viewport.unit_system == UnitSystem("kN", "m")
    assert window.analysis_settings.target_displacement.suffix() == " m"

    first_key = str(first.resolve())
    window._activate_workspace_session(first_key)
    application.processEvents()

    assert window.viewport.unit_system == UnitSystem("kip", "in")
    assert window.viewport.force_unit_selector.currentText() == "kip"
    assert window.viewport.length_unit_selector.currentText() == "in"
    assert window.analysis_settings.target_displacement.suffix() == " in"
    assert window.results_workspace.viewport._unit_system == UnitSystem("kip", "in")
    window.close()
