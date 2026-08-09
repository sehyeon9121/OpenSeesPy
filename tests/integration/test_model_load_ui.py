import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QTimer
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
    # +3 element-number badges (one per element), added alongside node labels but
    # hidden by default until a truss result view turns them on.
    assert len(window.scene.items()) == 17
    assert window.viewport.mode_label.text() == "MODEL LOADED"
    assert window.workspace_stack.currentWidget() is window.workspace
    assert not window.navigation.isHidden()
    assert not window.header.home_button.isHidden()
    assert window.start_workspace.session_title.text() == "CURRENT SESSION"
    assert EXAMPLE_MODEL.name in window.start_workspace.session_detail.text()

    window.header.brand_button.click()
    assert window.workspace_stack.currentWidget() is window.start_workspace
    assert window._current_model_source == EXAMPLE_MODEL
    assert not window.start_workspace.resume_button.isHidden()

    window.start_workspace.resume_button.click()
    assert window.workspace_stack.currentWidget() is window.workspace
    assert not window.navigation.isHidden()

    window.header.home_button.click()
    assert window.workspace_stack.currentWidget() is window.start_workspace
    window.start_workspace.resume_button.click()
    assert window.workspace_stack.currentWidget() is window.workspace

    load_items = [
        item
        for item in window.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "load"
    ]
    assert len(load_items) == 1
    assert "Fx=20" in load_items[0].toolTip()
    assert "Fy=-30" in load_items[0].toolTip()
    assert "|F|" not in load_items[0].toolTip()
    assert "kN" in load_items[0].toolTip()

    force_index = window.viewport.force_unit_selector.findText("N")
    length_index = window.viewport.length_unit_selector.findText("mm")
    window.viewport.force_unit_selector.setCurrentIndex(force_index)
    assert window.viewport.unit_system.force == "N"
    assert window.viewport.unit_system.length == "m"
    assert (
        window.results_workspace.data_panel.result_table.horizontalHeaderItem(1).text()
        == "UX (m)"
    )

    window.viewport.length_unit_selector.setCurrentIndex(length_index)
    assert window.viewport.unit_system.key == "n_mm"
    assert "Fx=20 N" in load_items[0].toolTip()
    assert "kN" not in load_items[0].toolTip()
    assert (
        window.results_workspace.data_panel.result_table.horizontalHeaderItem(1).text()
        == "UX (mm)"
    )

    element_tree_item = window.model_sidebar._tree_items[("element", 3)]
    window.model_sidebar.tree.setCurrentItem(element_tree_item)
    application.processEvents()
    assert window.model_inspector.selection_identity == ("element", 3)
    assert any(item.data(0) == ("element", 3) for item in window.scene.selectedItems())
    property_values = [value.text() for _, _, value in window.model_inspector.property_cards]
    assert any("N/mm²" in value for value in property_values)
    readiness_status, _ = window.model_inspector.readiness_rows["displacement"]
    assert readiness_status.text() == "READY"

    window.scene.clearSelection()
    load_items[0].setSelected(True)
    application.processEvents()
    assert window.model_inspector.selection_identity == ("load", 4)
    assert window.model_sidebar.tree.currentItem().data(
        0, Qt.ItemDataRole.UserRole
    ) == ("load", 4)

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
