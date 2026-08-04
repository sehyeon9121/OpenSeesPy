import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openframe.app.shell.main_window import MainWindow
from openframe.features.model.application.open_model import OpenModelService
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "portal_frame_2d.py"


def test_model_file_updates_sidebar_and_viewport() -> None:
    application = QApplication.instance() or QApplication([])
    service = OpenModelService(OpenSeesModelImporter(timeout_seconds=10))
    window = MainWindow(open_model_service=service)

    window._start_model_load(EXAMPLE_MODEL)
    thread = window._model_load_thread
    assert thread is not None

    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    QTimer.singleShot(5_000, loop.quit)
    loop.exec()
    application.processEvents()

    assert window._model_load_thread is None
    assert window.model_sidebar.summary_values["nodes"].text() == "4"
    assert window.model_sidebar.summary_values["elements"].text() == "3"
    assert window.model_sidebar.summary_values["supports"].text() == "2"
    assert len(window.scene.items()) == 14
    assert window.viewport.mode_label.text() == "MODEL LOADED"

    load_items = [
        item
        for item in window.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "load"
    ]
    assert len(load_items) == 1
    assert "Fx=20" in load_items[0].toolTip()
    assert "Fy=-30" in load_items[0].toolTip()
    assert "|F|" not in load_items[0].toolTip()

    window.viewport.filter_options["load"].setChecked(False)
    assert all(not item.isVisible() for item in load_items)
    window.viewport.filter_options["load"].setChecked(True)
    assert all(item.isVisible() for item in load_items)

    node_label_items = [
        item
        for item in window.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "node_label"
    ]
    assert len(node_label_items) == 4
    assert all(item.isVisible() for item in node_label_items)

    window.viewport.filter_options["node_label"].setChecked(False)
    assert all(not item.isVisible() for item in node_label_items)
    window.viewport.filter_options["node_label"].setChecked(True)
    assert all(item.isVisible() for item in node_label_items)

    window.viewport.filter_options["node"].setChecked(False)
    assert all(not item.isVisible() for item in node_label_items)
    window.viewport.filter_options["node"].setChecked(True)
    assert all(item.isVisible() for item in node_label_items)

    window.close()
