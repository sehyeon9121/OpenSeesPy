"""Quick3DViewport's own behaviour: the view/structural coordinate inversion
used for free-form 3D drawing, and camera-reset control on set_model.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject
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


def test_orientation_is_a_fixed_top_right_gizmo_not_scene_origin_axes() -> None:
    viewport = _viewport()
    root = viewport.quick_widget.rootObject()
    assert root is not None

    gizmo = root.findChild(QObject, "orientationGizmo")
    assert gizmo is not None
    assert gizmo.property("visible") is True
    assert gizmo.property("width") == pytest.approx(104.0)
    assert gizmo.property("height") == pytest.approx(104.0)

    qml = viewport._qml_path.read_text(encoding="utf-8")
    assert "property real axisLength" not in qml
    assert 'objectName: "orientationGizmo"' in qml
