"""Quick3DViewport's own behaviour: the view/structural coordinate inversion
used for free-form 3D drawing, and camera-reset control on set_model.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtQml import QJSValue
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import Element, Node, StructuralModel
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport


def _viewport() -> Quick3DViewport:
    QApplication.instance() or QApplication([])
    viewport = Quick3DViewport()
    # QML loading (setSource()) is deferred to the first visible showEvent -
    # see quick3d_viewport.py - so tests that need the QML root must show()
    # first, same as a real page becoming visible.
    viewport.show()
    return viewport


def _qml_list(value: object) -> list:
    if isinstance(value, QJSValue):
        value = value.toVariant()
    if value is None:
        return []
    return list(value)


def _set_model(viewport: Quick3DViewport, model: StructuralModel, **kwargs) -> None:
    """Apply a model through the coalesced viewport path used in production."""
    viewport.set_model(model, **kwargs)
    QApplication.processEvents()


def test_qml_is_not_loaded_until_first_visible_show() -> None:
    """Startup builds several QQuickWidgets before MainWindow appears; mapping
    their native surfaces early flashes blank title-bar windows on Windows.
    Construction is allowed (focus/shortcuts need the child), but setSource
    and clearing WA_DontShowOnScreen must wait for a real visible show."""
    from PySide6.QtCore import Qt

    QApplication.instance() or QApplication([])
    viewport = Quick3DViewport()
    assert viewport.quick_widget.rootObject() is None
    assert viewport.quick_widget.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)

    viewport.show()
    assert not viewport.quick_widget.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    assert viewport.quick_widget.rootObject() is not None


def test_display_panel_opens_and_tracks_bridge_visibility() -> None:
    viewport = _viewport()
    viewport.setFixedSize(640, 480)
    QApplication.processEvents()
    root = viewport.quick_widget.rootObject()
    assert root is not None

    button = root.findChild(QObject, "displayOptionsButton")
    popup = root.findChild(QObject, "displayOptionsPopup")
    assert button is not None
    assert popup is not None
    assert popup.property("opened") is False

    QTest.mouseClick(
        viewport.quick_widget,
        Qt.MouseButton.LeftButton,
        pos=QPoint(52, 29),
    )
    QApplication.processEvents()
    assert popup.property("opened") is True

    option_names = (
        "nodesVisibleOption",
        "nodeNumbersVisibleOption",
        "membersVisibleOption",
        "memberNumbersVisibleOption",
        "nodalLoadsVisibleOption",
        "memberLoadsVisibleOption",
        "floorLoadsVisibleOption",
        "selfWeightLoadsVisibleOption",
    )
    options = {name: root.findChild(QObject, name) for name in option_names}
    assert all(option is not None for option in options.values())

    def click_display_item(name: str) -> None:
        item = root.findChild(QObject, name)
        assert item is not None
        point = item.mapToItem(root, QPointF(8, item.height() / 2))
        QTest.mouseClick(
            viewport.quick_widget,
            Qt.MouseButton.LeftButton,
            pos=QPoint(round(point.x()), round(point.y())),
        )
        QApplication.processEvents()

    # Parent rows turn every child on from mixed state, then all off.
    click_display_item("nodesDisplayParent")
    assert viewport.bridge.nodesVisible is True
    assert viewport.bridge.nodeNumbersVisible is True
    click_display_item("nodesDisplayParent")
    assert viewport.bridge.nodesVisible is False
    assert viewport.bridge.nodeNumbersVisible is False

    click_display_item("loadsDisplayParent")
    assert viewport.bridge.loadsVisible is False
    assert viewport.bridge.nodalLoadsVisible is False
    assert viewport.bridge.memberLoadsVisible is False
    assert viewport.bridge.floorLoadsVisible is False
    assert viewport.bridge.selfWeightLoadsVisible is False
    click_display_item("loadsDisplayParent")
    assert viewport.bridge.loadsVisible is True
    assert viewport.bridge.nodalLoadsVisible is True
    assert viewport.bridge.memberLoadsVisible is True
    assert viewport.bridge.floorLoadsVisible is True
    assert viewport.bridge.selfWeightLoadsVisible is True

    click_display_item("floorLoadsVisibleOption")
    assert viewport.bridge.loadsVisible is True
    assert viewport.bridge.floorLoadsVisible is False
    assert viewport.bridge.nodalLoadsVisible is True
    click_display_item("floorLoadsVisibleOption")
    assert viewport.bridge.floorLoadsVisible is True

    viewport.set_nodes_visible(False)
    viewport.set_node_numbers_visible(True)
    viewport.set_members_visible(False)
    viewport.set_member_numbers_visible(True)
    viewport.bridge.set_nodal_loads_visible(False)
    viewport.bridge.set_floor_loads_visible(False)
    QApplication.processEvents()

    assert options["nodesVisibleOption"].property("checked") is False
    assert options["nodeNumbersVisibleOption"].property("checked") is True
    assert options["membersVisibleOption"].property("checked") is False
    assert options["memberNumbersVisibleOption"].property("checked") is True
    assert options["nodalLoadsVisibleOption"].property("checked") is False
    assert options["memberLoadsVisibleOption"].property("checked") is True
    assert options["floorLoadsVisibleOption"].property("checked") is False
    assert options["selfWeightLoadsVisibleOption"].property("checked") is True
    assert bool(root.nodeModelVisible(1)) is False
    assert bool(root.memberModelVisible(1)) is False


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

    _set_model(viewport, model, reset_camera=False)
    assert root.property("cameraPitch") == pytest.approx(-89.0), "must not reframe"

    _set_model(viewport, model)
    assert root.property("cameraPitch") == pytest.approx(-25.0), "default still reframes to iso"


def test_members_expose_endpoints_for_projected_box_selection() -> None:
    viewport = _viewport()
    model = StructuralModel(
        nodes={1: Node(1, 1.0, 2.0, 3.0), 2: Node(2, 5.0, 7.0, 11.0)},
        elements={8: Element(8, 1, 2, "frame")},
        ndm=3,
    )

    _set_model(viewport, model)

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


def test_qml_window_drag_selects_only_nodes_even_when_members_are_fully_enclosed() -> None:
    """Regression test: a downward ("window") drag used to still grab any
    member whose both endpoints fell inside the box, so boxing a whole
    building to pick many nodes also swept those members in - reported as
    "전체나 혹은 부재가 일부 이상 포함되면 부재도 같이 잡혀버림". Match the
    2D canvas's default-"all" filter: window = nodes only; upward
    ("crossing") still takes enclosed/touched members."""
    viewport = _viewport()
    viewport.setFixedSize(640, 480)
    _set_model(
        viewport,
        StructuralModel(
            nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 1.0, 0.0, 0.0)},
            elements={3: Element(3, 1, 2, "frame")},
            ndm=3,
        ),
    )
    viewport.set_camera_preset("xy")
    for _ in range(20):
        QApplication.processEvents()
    root = viewport.quick_widget.rootObject()
    assert root is not None
    if len(viewport.bridge.nodes) < 2:
        pytest.skip("viewport bridge did not publish both nodes")
    selections: list[tuple[set[int], set[int], bool]] = []
    viewport.selection_box_finished.connect(
        lambda nodes, members, additive: selections.append((nodes, members, additive))
    )

    # Downward window drag: start at top of the view, end at bottom.
    # Use a generous margin - offscreen mapFrom3DScene can place nodes slightly
    # outside the widget's nominal width/height even when both are visible.
    root.setProperty("selectionStartX", -200.0)
    root.setProperty("selectionCurrentX", float(root.property("width")) + 200.0)
    root.setProperty("selectionStartY", -200.0)
    root.setProperty("selectionCurrentY", float(root.property("height")) + 200.0)
    root.finishSelectionBox(False)

    # Upward crossing drag: start at bottom, end at top.
    root.setProperty("selectionStartY", float(root.property("height")) + 200.0)
    root.setProperty("selectionCurrentY", -200.0)
    root.finishSelectionBox(False)

    assert selections[0] == ({1, 2}, set(), False)
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


def test_nodes_have_a_non_interactive_screen_space_marker_overlay() -> None:
    """The marker stays readable above member solids without blocking input."""
    viewport = _viewport()
    root = viewport.quick_widget.rootObject()
    assert root is not None

    overlay = root.findChild(QObject, "nodeMarkerOverlay")
    assert overlay is not None
    assert overlay.property("enabled") is False
    assert root.property("nodeMarkerRadiusPixels") == pytest.approx(3.75)
    assert root.property("selectedNodeMarkerRadiusPixels") == pytest.approx(5.25)
    assert root.property("nodePickRadiusPixels") == pytest.approx(18.0)
    assert QColor(root.property("nodeMarkerColor")).name() == "#eab308"


def test_members_are_drawn_as_one_instanced_model_instead_of_one_model_each() -> None:
    """Repeater3D used to build a Model+material per member part, which is
    why adding storeys made orbiting and picking feel stuck. One cube model
    plus an InstanceList keeps the same B/H while the draw-call count stays
    at two (cube/cylinder) no matter how many members are in the frame.
    """
    viewport = _viewport()
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 4.0, 0.0, 0.0, 6),
            3: Node(3, 4.0, 0.0, 3.0, 6),
        },
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties={"section_shape": "Rectangle", "width": 0.3, "height": 0.5},
            ),
            2: Element(
                2,
                2,
                3,
                "elasticBeamColumn",
                properties={"section_shape": "Rectangle", "width": 0.3, "height": 0.5},
            ),
        },
    )
    _set_model(viewport, model)
    QApplication.processEvents()

    root = viewport.quick_widget.rootObject()
    cubes = root.findChild(QObject, "cubeInstanceList")
    cylinders = root.findChild(QObject, "cylinderInstanceList")
    assert cubes is not None
    assert cylinders is not None
    assert cubes.property("instanceCount") == len(viewport.bridge.members)
    assert cylinders.property("instanceCount") == 0
    assert root.findChild(QObject, "cubeMemberModel") is not None


def test_selecting_a_member_recolors_its_instance_without_a_second_mesh() -> None:
    """The visible member is the instance cube. A duplicate red Model at
    the same B/H used to z-fight it, so selection looked like a no-op.
    """
    viewport = _viewport()
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 4.0, 0.0, 0.0, 6),
            3: Node(3, 4.0, 0.0, 3.0, 6),
        },
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties={"section_shape": "Rectangle", "width": 0.3, "height": 0.5},
            ),
            2: Element(
                2,
                2,
                3,
                "elasticBeamColumn",
                properties={"section_shape": "Rectangle", "width": 0.3, "height": 0.5},
            ),
        },
    )
    _set_model(viewport, model)
    viewport.set_selection(set(), {1})
    QApplication.processEvents()

    root = viewport.quick_widget.rootObject()
    tags = _qml_list(root.property("cubeTags"))
    hexes = [QColor(value).name() for value in _qml_list(root.property("cubePaintHex"))]
    assert tags == [1, 2]
    assert hexes[0] == "#ef4444"
    assert hexes[1] != "#ef4444"

    viewport.set_selection(set(), set())
    QApplication.processEvents()
    hexes = [QColor(value).name() for value in _qml_list(root.property("cubePaintHex"))]
    assert hexes[0] != "#ef4444"
    assert hexes[1] != "#ef4444"


def test_applying_a_section_to_the_only_member_updates_instance_scale() -> None:
    """Drawing a beam then stamping the Element-tab section used to leave a
    hairline until the *next* member was created. Instance sync keyed off
    member count, and applying a section keeps that count at 1, so the
    InstanceList kept the unassigned stick until a later add bumped it.
    """
    from dataclasses import replace

    viewport = _viewport()
    unassigned = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 4.0, 0.0, 0.0, 6),
        },
        elements={
            1: Element(1, 1, 2, "elasticBeamColumn", properties={}),
        },
    )
    _set_model(viewport, unassigned)
    root = viewport.quick_widget.rootObject()
    stick = _qml_list(root.property("cubePaintWidthB"))
    assert len(stick) == 1
    assert stick[0] < 0.05

    assigned = replace(
        unassigned,
        elements={
            1: replace(
                unassigned.elements[1],
                properties={
                    "section_shape": "Rectangle",
                    "width": 0.3,
                    "height": 0.5,
                },
            ),
        },
    )
    _set_model(viewport, assigned)
    widths = _qml_list(root.property("cubePaintWidthB"))
    assert len(widths) == 1
    assert widths[0] == pytest.approx(0.3, rel=1e-4)


def test_section_on_a_new_beam_updates_even_when_older_members_keep_their_size() -> None:
    """The ramen case: columns already have a section, then the next two
    nodes create a girder. The instance key used to look only at members[0],
    so the new span stayed a hairline until another member changed the count.
    """
    from dataclasses import replace

    viewport = _viewport()
    columns = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 4.0, 0.0, 0.0, 6),
            3: Node(3, 0.0, 0.0, 3.0, 6),
            4: Node(4, 4.0, 0.0, 3.0, 6),
        },
        elements={
            1: Element(
                1,
                1,
                3,
                "elasticBeamColumn",
                properties={"section_shape": "Rectangle", "width": 0.3, "height": 0.5},
            ),
            2: Element(
                2,
                2,
                4,
                "elasticBeamColumn",
                properties={"section_shape": "Rectangle", "width": 0.3, "height": 0.5},
            ),
        },
    )
    _set_model(viewport, columns)
    with_stick = replace(
        columns,
        elements={
            **columns.elements,
            3: Element(3, 3, 4, "elasticBeamColumn", properties={}),
        },
    )
    _set_model(viewport, with_stick)
    root = viewport.quick_widget.rootObject()
    widths = _qml_list(root.property("cubePaintWidthB"))
    assert len(widths) == 3
    assert widths[0] == pytest.approx(0.3, rel=1e-4)
    assert widths[1] == pytest.approx(0.3, rel=1e-4)
    assert widths[2] < 0.05

    sectioned = replace(
        with_stick,
        elements={
            **with_stick.elements,
            3: replace(
                with_stick.elements[3],
                properties={"section_shape": "Rectangle", "width": 0.3, "height": 0.5},
            ),
        },
    )
    _set_model(viewport, sectioned)
    widths = _qml_list(root.property("cubePaintWidthB"))
    assert len(widths) == 3
    assert widths[2] == pytest.approx(0.3, rel=1e-4)


def test_navigation_cursor_feedback_loads_and_switches_to_pan_mode() -> None:
    viewport = _viewport()
    viewport.setFixedSize(640, 480)
    root = viewport.quick_widget.rootObject()
    assert root is not None

    feedback = root.findChild(QObject, "navigationCursorFeedback")
    mouse_area = root.findChild(QObject, "viewportMouseArea")
    assert feedback is not None
    assert mouse_area is not None
    assert feedback.property("visible") is False
    assert feedback.property("enabled") is False

    point = QPoint(240, 180)
    QTest.mousePress(
        viewport.quick_widget,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        point,
    )
    QApplication.processEvents()
    assert feedback.property("visible") is True
    assert feedback.property("panMode") is False

    QTest.mouseRelease(
        viewport.quick_widget,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        point,
    )
    QApplication.processEvents()
    assert feedback.property("visible") is False

    QTest.mousePress(
        viewport.quick_widget,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.ShiftModifier,
        point,
    )
    QApplication.processEvents()
    assert feedback.property("visible") is True
    assert feedback.property("panMode") is True

    QTest.mouseRelease(
        viewport.quick_widget,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.ShiftModifier,
        point,
    )
    QApplication.processEvents()
    assert feedback.property("visible") is False


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


def test_selection_highlight_does_not_replace_geometry_lists() -> None:
    viewport = _viewport()
    model = StructuralModel(
        ndm=3,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 4.0, 0.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    _set_model(viewport, model)
    bridge = viewport.bridge
    nodes_ref = bridge.nodes
    members_ref = bridge.members

    bridge.set_selection({1}, {1})

    assert bridge.nodes is nodes_ref
    assert bridge.members is members_ref
    assert bridge.selectedNodeTags == [1]
    assert bridge.selectedMemberTags == [1]
    assert bridge.selectionRevision >= 1
