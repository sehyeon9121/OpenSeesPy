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


def test_recent_projects_restores_a_hand_drawn_2d_model() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()

    window._start_new_model_workspace()
    canvas = window.direct_model_workspace.geometry_page.canvas
    canvas.add_node(0.0, 0.0)
    canvas.add_node(4.0, 0.0)
    application.processEvents()

    window._show_start_workspace()

    assert len(window._direct_workspace_sessions) == 1
    assert window.start_workspace._session_names[0].text() == "Untitled 2D Model"
    assert "Nodes 2" in window.start_workspace._session_details[0].text()
    assert not window.start_workspace._session_buttons[0].isHidden()

    # Prove that RETURN restores the stored snapshot, rather than merely
    # revealing whatever happens to remain in the shared canvas widget.
    canvas.load_dict({"ndm": 2})
    assert not canvas.nodes
    window.start_workspace._session_buttons[0].click()
    application.processEvents()

    assert window.workspace_stack.currentWidget() is window.direct_model_workspace
    assert window.direct_model_workspace.stage_stack.currentWidget() is window.direct_model_workspace.geometry_page
    assert len(canvas.nodes) == 2
    window.close()


def test_recent_projects_lists_2d_and_3d_models_and_keeps_them_separate() -> None:
    application = QApplication.instance() or QApplication([])
    window = MainWindow()

    window._start_new_model_workspace()
    window.direct_model_workspace.geometry_page.canvas.add_node(1.0, 2.0)
    window._show_start_workspace()

    window._start_new_3d_model_workspace()
    window.direct_model_workspace.geometry_page_3d.canvas.add_node(3.0, 4.0)
    window._show_start_workspace()

    names = [label.text() for label in window.start_workspace._session_names[:2]]
    assert names == ["Untitled 3D Model", "Untitled 2D Model"]

    two_d_index = names.index("Untitled 2D Model")
    window.start_workspace._session_buttons[two_d_index].click()
    application.processEvents()
    direct = window.direct_model_workspace
    assert direct.stage_stack.currentWidget() is direct.geometry_page
    assert direct.geometry_page.canvas.ndm == 2
    assert len(direct.geometry_page.canvas.nodes) == 1

    window._show_start_workspace()
    visible_names = [label.text() for label in window.start_workspace._session_names[:2]]
    three_d_index = visible_names.index("Untitled 3D Model")
    window.start_workspace._session_buttons[three_d_index].click()
    application.processEvents()
    assert direct.geometry_page_3d.canvas.ndm == 3
    assert len(direct.geometry_page_3d.canvas.nodes) == 1
    window.close()
