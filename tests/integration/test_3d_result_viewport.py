import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisRequest, AnalysisStatus
from openframe.features.results.presentation.result_viewport import ResultViewport
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "cantilever_frame_3d.py"
EXAMPLE_MODEL_2D = Path(__file__).parents[2] / "examples" / "portal_frame_2d.py"


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_result_viewport_switches_to_quick3d_for_3d_models() -> None:
    application = _application()
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    viewport = ResultViewport()

    viewport.set_model(model)
    application.processEvents()

    assert viewport.canvas_stack.currentWidget() is viewport.quick3d_view
    assert viewport.quick3d_view.quick_widget.status() == QQuickWidget.Status.Ready
    assert len(viewport.quick3d_view.bridge.nodes) == 2
    assert len(viewport.quick3d_view.bridge.members) == 1
    # No analysis has run yet, so nodes keep their plain default colour.
    assert all(node["color"] == "#2877b7" for node in viewport.quick3d_view.bridge.nodes)
    viewport.close()


def test_result_viewport_shows_deformed_overlay_colours_and_load_arrows() -> None:
    application = _application()
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(
        AnalysisRequest(source_path=EXAMPLE_MODEL)
    )
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    viewport = ResultViewport()
    viewport.set_model(model)
    viewport.show_result(result)
    application.processEvents()

    bridge = viewport.quick3d_view.bridge
    # The example loads node 2 with (10, -5, -20) -> one shaft part + one head part.
    assert len(bridge.loadArrows) == 2
    assert {part["tag"] for part in bridge.loadArrows} == {2}
    assert {part["shape"] for part in bridge.loadArrows} == {"#Cylinder", "#Cone"}
    # UNDEFORMED SHAPE is checked by default, so the ghost overlay should be populated.
    assert len(bridge.ghostNodes) == 2
    assert len(bridge.ghostMembers) == 1
    # Node 2 moves under the load, so it should be coloured away from the default blue.
    node_colors = {node["tag"]: node["color"] for node in bridge.nodes}
    assert node_colors[2] != "#2877b7"

    viewport.show_undeformed.setChecked(False)
    application.processEvents()
    assert bridge.ghostNodes == []
    assert bridge.ghostMembers == []

    viewport.close()


def test_displacement_mode_enables_node_picking_for_3d_models_only() -> None:
    application = _application()
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(
        AnalysisRequest(source_path=EXAMPLE_MODEL)
    )
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    viewport = ResultViewport()
    viewport.set_model(model)
    viewport.show_result(result)
    application.processEvents()

    viewport.set_result_type("displacement")
    assert viewport.quick3d_view.quick_widget.cursor().shape() == Qt.CursorShape.CrossCursor
    assert viewport.quick3d_view.quick_widget.rootObject().property("pickingEnabled") is True

    viewport.set_result_type("overview")
    assert viewport.quick3d_view.quick_widget.cursor().shape() != Qt.CursorShape.CrossCursor
    assert viewport.quick3d_view.quick_widget.rootObject().property("pickingEnabled") is False

    viewport.close()


def test_displacement_mode_does_not_enable_picking_for_2d_models() -> None:
    application = _application()
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL_2D)
    viewport = ResultViewport()

    viewport.set_model(model)
    application.processEvents()
    viewport.set_result_type("displacement")

    assert viewport.quick3d_view.quick_widget.cursor().shape() != Qt.CursorShape.CrossCursor
    assert viewport.quick3d_view.quick_widget.rootObject().property("pickingEnabled") is False

    viewport.close()


def test_node_displacement_text_reports_known_values_and_none_for_unknown_tag() -> None:
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(
        AnalysisRequest(source_path=EXAMPLE_MODEL)
    )
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    viewport = ResultViewport()
    viewport.set_model(model)
    viewport.show_result(result)

    text = viewport._node_displacement_text(2)
    assert text is not None
    assert "Node 2" in text
    assert "UX=" in text and "UY=" in text and "UZ=" in text and "|U|=" in text

    assert viewport._node_displacement_text(999) is None

    viewport.close()


def test_picked_node_is_highlighted_and_clears_when_leaving_displacement_mode() -> None:
    application = _application()
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(
        AnalysisRequest(source_path=EXAMPLE_MODEL)
    )
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    viewport = ResultViewport()
    viewport.set_model(model)
    viewport.show_result(result)
    application.processEvents()
    viewport.set_result_type("displacement")

    default_radius = next(
        node["radius"] for node in viewport.quick3d_view.bridge.nodes if node["tag"] == 2
    )

    # Simulate what happens when the QML side reports a successful pick.
    viewport._show_node_displacement(2, 100, 100)

    nodes_by_tag = {node["tag"]: node for node in viewport.quick3d_view.bridge.nodes}
    assert nodes_by_tag[2]["color"] == "#00e5ff"
    assert nodes_by_tag[2]["radius"] > default_radius
    # The other node must be untouched, so only the picked one stands out.
    assert nodes_by_tag[1]["color"] != "#00e5ff"

    # Leaving displacement mode should drop the highlight along with picking mode.
    viewport.set_result_type("overview")
    assert all(node["color"] != "#00e5ff" for node in viewport.quick3d_view.bridge.nodes)

    viewport.close()
