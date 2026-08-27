"""Quick3DViewport's own behaviour: the view/structural coordinate inversion
used for free-form 3D drawing, and camera-reset control on set_model.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QPoint
from PySide6.QtWidgets import QApplication

from openframe.core.domain import Element, Node, StructuralModel
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport


def _viewport() -> Quick3DViewport:
    QApplication.instance() or QApplication([])
    viewport = Quick3DViewport()
    # QML loading (setSource(), which is what makes rootObject() non-None) is
    # deferred to the widget's first showEvent - see quick3d_viewport.py's own
    # comment on why - so tests that need the QML root loaded must show() it
    # first, same as a real page becoming visible would.
    viewport.show()
    return viewport


def test_plane_picked_inverts_the_view_coordinate_mapping() -> None:
    """Quick3DSceneBridge maps structural (x, y, z) -> view (x, z, -y); a click
    on the plane must come back as the original structural point."""
    viewport = _viewport()
    picks: list[tuple[float, float, float]] = []
    viewport.plane_point_picked.connect(lambda x, y, z: picks.append((x, y, z)))

    structural = (2.0, 5.0, -3.0)
    view_x, view_y, view_z = structural[0], structural[2], -structural[1]
    viewport._on_plane_picked(view_x, view_y, view_z)

    assert picks == [pytest.approx(structural)]


def test_set_active_plane_and_plane_picking_mode_reach_the_qml_root() -> None:
    viewport = _viewport()
    root = viewport.quick_widget.rootObject()
    assert root is not None

    viewport.set_active_plane("xz", 3.5)
    assert root.property("planeKind") == "xz"
    assert root.property("planeOffset") == pytest.approx(3.5)

    viewport.set_plane_picking_mode(True)
    assert root.property("planePickingEnabled") is True
    viewport.set_plane_picking_mode(False)
    assert root.property("planePickingEnabled") is False


def test_set_model_resets_the_camera_by_default_but_can_be_told_not_to() -> None:
    """Resetting on every load is right for opening a file once; wrong while a
    student is drawing interactively, where it would fight their own orbiting
    after every single click."""
    viewport = _viewport()
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        ndm=3,
    )
    root = viewport.quick_widget.rootObject()

    viewport.set_camera_preset("xy")
    assert root.property("cameraPitch") == pytest.approx(-89.0)

    viewport.set_model(model, reset_camera=False)
    assert root.property("cameraPitch") == pytest.approx(-89.0), "must not reframe"

    viewport.set_model(model)
    assert root.property("cameraPitch") == pytest.approx(-25.0), "default still reframes to iso"


def test_members_expose_endpoints_for_projected_box_selection() -> None:
    viewport = _viewport()
    model = StructuralModel(
        nodes={1: Node(1, 1.0, 2.0, 3.0), 2: Node(2, 5.0, 7.0, 11.0)},
        elements={8: Element(8, 1, 2, "frame")},
        ndm=3,
    )

    viewport.set_model(model)

    member = viewport.bridge.members[0]
    assert (member["start_x"], member["start_y"], member["start_z"]) == pytest.approx(
        (1.0, 3.0, -2.0)
    )
    assert (member["end_x"], member["end_y"], member["end_z"]) == pytest.approx(
        (5.0, 11.0, -7.0)
    )


def test_qml_box_selection_payload_is_converted_to_tag_sets() -> None:
    viewport = _viewport()
    selections: list[tuple[set[int], set[int], bool]] = []
    viewport.selection_box_finished.connect(
        lambda nodes, members, additive: selections.append((nodes, members, additive))
    )

    viewport._on_selection_box_finished("1,4", "7,9", True)

    assert selections == [({1, 4}, {7, 9}, True)]


def test_member_pick_is_forwarded_with_global_screen_coordinates() -> None:
    viewport = _viewport()
    picks: list[tuple[int, int, int]] = []
    viewport.member_picked.connect(lambda tag, x, y: picks.append((tag, x, y)))

    viewport._on_member_picked(8, 12.0, 18.0)

    expected = viewport.quick_widget.mapToGlobal(QPoint(12, 18))
    assert picks == [(8, expected.x(), expected.y())]


def test_qml_box_selection_always_includes_fully_enclosed_members() -> None:
    """A member whose both endpoints are inside the drag box must be
    selected regardless of drag direction - same as the 2D canvas's
    _select_in_rect. Only a member the box merely *touches* (one or neither
    endpoint inside) depends on direction: included when dragging upward
    ("crossing"), excluded when dragging downward ("window")."""
    viewport = _viewport()
    viewport.resize(640, 480)
    viewport.set_model(
        StructuralModel(
            nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
            elements={3: Element(3, 1, 2, "frame")},
            ndm=3,
        )
    )
    QApplication.processEvents()
    root = viewport.quick_widget.rootObject()
    selections: list[tuple[set[int], set[int], bool]] = []
    viewport.selection_box_finished.connect(
        lambda nodes, members, additive: selections.append((nodes, members, additive))
    )

    root.setProperty("selectionStartX", 0.0)
    root.setProperty("selectionCurrentX", float(root.property("width")))
    root.setProperty("selectionStartY", 0.0)
    root.setProperty("selectionCurrentY", float(root.property("height")))
    root.finishSelectionBox(False)

    root.setProperty("selectionStartY", float(root.property("height")))
    root.setProperty("selectionCurrentY", 0.0)
    root.finishSelectionBox(False)

    assert selections[0] == ({1, 2}, {3}, False)
    assert selections[1] == ({1, 2}, {3}, False)


def test_orientation_is_a_fixed_top_right_camera_gizmo() -> None:
    viewport = _viewport()
    root = viewport.quick_widget.rootObject()
    assert root is not None

    gizmo = root.findChild(QObject, "orientationGizmo")
    assert gizmo is not None
    assert gizmo.property("visible") is True
    assert gizmo.property("width") == pytest.approx(112.0)
    assert gizmo.property("height") == pytest.approx(118.0)

    qml = viewport._qml_path.read_text(encoding="utf-8")
    assert 'objectName: "orientationGizmo"' in qml
    assert 'anchors.top: parent.top' in qml
    assert 'anchors.right: parent.right' in qml
    assert 'objectName: "orientationGizmoMouseArea"' in qml


def test_world_origin_axes_are_attached_to_structural_zero() -> None:
    viewport = _viewport()
    root = viewport.quick_widget.rootObject()
    assert root is not None

    axes = root.findChild(QObject, "worldOriginAxes")
    assert axes is not None
    assert axes.property("visible") is True
    assert axes.property("axisLength") == pytest.approx(0.35)

    qml = viewport._qml_path.read_text(encoding="utf-8")
    assert 'objectName: "worldOriginAxes"' in qml
    assert "return view3d.mapFrom3DScene(Qt.vector3d(x, z, -y))" in qml
    assert 'context.strokeText("0,0,0"' in qml


def test_orientation_axis_actions_change_to_the_matching_orthographic_view() -> None:
    viewport = _viewport()
    root = viewport.quick_widget.rootObject()
    gizmo = root.findChild(QObject, "orientationGizmo")

    gizmo.activateTarget("X")
    assert root.property("cameraYaw") == pytest.approx(90.0)
    assert root.property("cameraPitch") == pytest.approx(0.0)

    gizmo.activateTarget("Y")
    assert root.property("cameraYaw") == pytest.approx(0.0)
    assert root.property("cameraPitch") == pytest.approx(0.0)

    gizmo.activateTarget("Z")
    assert root.property("cameraPitch") == pytest.approx(-89.0)

    gizmo.activateTarget("ISO")
    assert root.property("cameraYaw") == pytest.approx(45.0)
    assert root.property("cameraPitch") == pytest.approx(-25.0)
