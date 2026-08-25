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


def _result_viewport() -> ResultViewport:
    # Quick3DViewport now defers QML loading (rootObject()/status becoming
    # Ready) to its first showEvent - see quick3d_viewport.py's own comment -
    # so tests that read the QML root must show() first, same as this
    # viewport becoming visible on a real page would trigger it.
    viewport = ResultViewport()
    viewport.show()
    return viewport


def test_result_viewport_switches_to_quick3d_for_3d_models() -> None:
    application = _application()
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    viewport = _result_viewport()

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

    viewport = _result_viewport()
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

    viewport = _result_viewport()
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
    viewport = _result_viewport()

    viewport.set_model(model)
    application.processEvents()
    viewport.set_result_type("displacement")

    assert viewport.quick3d_view.quick_widget.cursor().shape() != Qt.CursorShape.CrossCursor
    # A 2D model never makes quick3d_view the current canvas_stack widget, so
    # it never receives a showEvent and its QML never loads (see
    # quick3d_viewport.py's deferred-loading comment) - picking is "disabled"
    # in the strongest possible sense: there is no QML root to enable it on.
    assert viewport.canvas_stack.currentWidget() is not viewport.quick3d_view
    assert viewport.quick3d_view.quick_widget.rootObject() is None

    viewport.close()


def test_node_displacement_text_reports_known_values_and_none_for_unknown_tag() -> None:
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(
        AnalysisRequest(source_path=EXAMPLE_MODEL)
    )
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    viewport = _result_viewport()
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

    viewport = _result_viewport()
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
    # Reuses the same red selection highlight as the modeling canvas
    # (Quick3DSceneBridge.set_selected_node) - a dedicated cyan pick color
    # used to give no visible feedback on click, so this was switched to the
    # already-working selection color instead.
    assert nodes_by_tag[2]["color"] == "#ef4444"
    assert nodes_by_tag[2]["radius"] > default_radius
    # The other node must be untouched, so only the picked one stands out.
    assert nodes_by_tag[1]["color"] != "#ef4444"

    # Leaving displacement mode should drop the highlight along with picking mode.
    viewport.set_result_type("overview")
    assert all(node["color"] != "#ef4444" for node in viewport.quick3d_view.bridge.nodes)

    viewport.close()


def test_view_selector_and_zoom_buttons_actually_move_the_3d_camera() -> None:
    """Regression test: view_selector (ISO/XY/XZ/YZ) and the +/-/FIT buttons used to
    look connected but never moved the Quick3D camera, because
    QMetaObject.invokeMethod(root, "setPreset"/"zoomBy", Q_ARG(...)) silently returns
    False for these plain QML JS functions. Calling them directly as attributes is
    what actually works."""
    application = _application()
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(
        AnalysisRequest(source_path=EXAMPLE_MODEL)
    )
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    viewport = _result_viewport()
    viewport.set_model(model)
    viewport.show_result(result)
    application.processEvents()

    root = viewport.quick3d_view.quick_widget.rootObject()
    assert (root.property("cameraYaw"), root.property("cameraPitch")) == (45.0, -25.0)

    viewport.view_selector.setCurrentIndex(viewport.view_selector.findData("xy"))
    application.processEvents()
    assert (root.property("cameraYaw"), root.property("cameraPitch")) == (0.0, -89.0)

    viewport.view_selector.setCurrentIndex(viewport.view_selector.findData("xz"))
    application.processEvents()
    assert (root.property("cameraYaw"), root.property("cameraPitch")) == (0.0, 0.0)

    distance_before = root.property("cameraDistance")
    viewport._zoom(1.2)
    application.processEvents()
    assert root.property("cameraDistance") < distance_before

    distance_before_out = root.property("cameraDistance")
    viewport._zoom(1.0 / 1.2)
    application.processEvents()
    assert root.property("cameraDistance") > distance_before_out

    viewport.view_selector.setCurrentIndex(viewport.view_selector.findData("yz"))
    application.processEvents()
    viewport.fit_model()
    application.processEvents()
    assert (root.property("cameraYaw"), root.property("cameraPitch")) == (90.0, 0.0)

    viewport.close()
