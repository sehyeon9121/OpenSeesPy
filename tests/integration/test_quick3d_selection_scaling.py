"""Exercise actual QML selection with mixed section sizes and bounded bridge reads."""

from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Property, QCoreApplication, QEvent, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from openframe.core.domain import Element, Node, StructuralModel
from openframe.features.viewport.presentation import quick3d_viewport
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge


class CountingBridge(Quick3DSceneBridge):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.list_reads = 0
        self.geometry_exports = 0

    @Property("QVariantList", notify=Quick3DSceneBridge.topology_changed)
    def nodes(self):
        self.list_reads += 1
        return self._nodes

    @Property("QVariantList", notify=Quick3DSceneBridge.topology_changed)
    def members(self):
        self.list_reads += 1
        return self._members

    @Slot(result="QVariantMap")
    def geometrySnapshot(self):
        self.geometry_exports += 1
        return super().geometrySnapshot()


def mixed_sections(count):
    model = StructuralModel(ndm=3, ndf=6)
    sections = [
        {"section_shape": "Rectangle", "width": 0.3, "height": 0.5},
        {"section_shape": "Rectangle", "width": 0.5, "height": 0.3},
        {"section_shape": "Rectangle", "width": 0.6, "height": 0.6},
        {
            "section_shape": "H/I Section",
            "dim_H": 0.6,
            "dim_B": 0.3,
            "dim_tw": 0.012,
            "dim_tf": 0.02,
        },
    ]
    for i in range(count):
        x, y = (i % 30) * 2.0, (i // 30) * 2.0
        model.nodes[2 * i + 1] = Node(2 * i + 1, x, y, 0.0, 6)
        model.nodes[2 * i + 2] = Node(2 * i + 2, x, y, 3.0, 6)
        model.elements[i + 1] = Element(
            i + 1,
            2 * i + 1,
            2 * i + 2,
            "elasticBeamColumn",
            properties=dict(sections[i % len(sections)]),
            local_axis_angle=(i % 3) * 30.0,
        )
    return model


@pytest.fixture
def viewport(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(quick3d_viewport, "Quick3DSceneBridge", CountingBridge)
    view = quick3d_viewport.Quick3DViewport()
    view.setFixedSize(800, 600)
    view.show()
    assert view.quick_widget.rootObject() is not None
    yield view
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def entries(root):
    return root.property("_cubeEntryPool").toVariant()


def assert_dimensions(view):
    root = view.quick_widget.rootObject()
    tags = root.property("cubeTags").toVariant()
    parts = view.bridge._members
    assert len(tags) == len(parts)
    for entry, part, tag in zip(entries(root), parts, tags):
        assert tag == part["tag"]
        scale = entry.property("scale")
        assert scale.x() * 100 == pytest.approx(part["width_b"], rel=1e-5)
        assert scale.z() * 100 == pytest.approx(part["width_h"], rel=1e-5)
        assert scale.y() * 100 == pytest.approx(part["length"], rel=1e-5)
        rotation = entry.property("rotation")
        assert rotation.scalar() == pytest.approx(part["qscalar"], abs=1e-6)
        assert rotation.x() == pytest.approx(part["qx"], abs=1e-6)
        assert rotation.y() == pytest.approx(part["qy"], abs=1e-6)
        assert rotation.z() == pytest.approx(part["qz"], abs=1e-6)


@pytest.mark.parametrize("count", [40, 600])
def test_box_selection_reuses_snapshot_and_retains_each_section(viewport, count):
    model = mixed_sections(count)
    viewport.set_model(model)
    QApplication.processEvents()
    bridge = viewport.bridge
    root = viewport.quick_widget.rootObject()
    assert_dimensions(viewport)
    # Verify the user-facing dimension distinction, not only internal agreement.
    scales = [entry.property("scale") for entry in entries(root)[:3]]
    for scale, expected in zip(scales, [(0.3, 0.5), (0.5, 0.3), (0.6, 0.6)]):
        assert (scale.x() * 100, scale.z() * 100) == pytest.approx(expected)
    bridge.list_reads = 0
    exports_before = bridge.geometry_exports
    results = []
    root.selectionBoxFinished.connect(lambda n, m, a: results.append((n, m, a)))
    root.setProperty("selectionStartX", -100000.0)
    root.setProperty("selectionStartY", 100000.0)
    root.setProperty("selectionCurrentX", 100000.0)
    root.setProperty("selectionCurrentY", -100000.0)
    root.finishSelectionBox(False)
    node_csv, member_csv, additive = results[-1]
    node_tags = [int(tag) for tag in node_csv.split(",")]
    member_tags = [int(tag) for tag in member_csv.split(",")]
    assert set(node_tags) == set(model.nodes)
    assert set(member_tags) == set(model.elements)
    assert len(member_tags) == count  # H/I web and flanges must not repeat the tag.
    assert additive is False

    viewport.set_selection(set(node_tags), set(member_tags))
    QApplication.processEvents()
    assert all(entry.property("color") == QColor("#ef4444") for entry in entries(root))
    assert_dimensions(viewport)
    viewport.set_selection(set(), {1})
    root.setProperty("cameraYaw", 70.0)
    root.pickNearestNode(400.0, 300.0)
    QApplication.processEvents()
    assert bridge.list_reads == 0
    assert bridge.geometry_exports == exports_before
    assert entries(root)[0].property("color") == QColor("#ef4444")
    assert entries(root)[1].property("color") != QColor("#ef4444")
    assert root.property("cubePaintHex").toVariant() == []


def test_snapshot_updates_for_resize_move_topology_and_isolate(viewport):
    model = mixed_sections(4)
    viewport.set_model(model)
    QApplication.processEvents()
    root = viewport.quick_widget.rootObject()
    first = entries(root)[0]
    viewport.set_selection(set(), {2, 4})
    resized = replace(
        model,
        elements={
            **model.elements,
            2: replace(
                model.elements[2],
                properties={"section_shape": "Rectangle", "width": 0.8, "height": 0.2},
                local_axis_angle=90.0,
            ),
        },
        nodes={**model.nodes, 4: replace(model.nodes[4], z=5.0)},
    )
    viewport.set_model(resized, reset_camera=False)
    QApplication.processEvents()
    assert_dimensions(viewport)
    assert entries(root)[0] is first
    assert entries(root)[1].property("scale").x() * 100 == pytest.approx(0.8)
    assert entries(root)[1].property("color") == QColor("#ef4444")

    viewport.set_isolate(set(), {2, 4})
    QApplication.processEvents()
    assert set(root.property("cubeTags").toVariant()) == {2, 4}
    viewport.set_line_display_active(True)
    QApplication.processEvents()
    assert root.property("cubeTags").toVariant() == [2, 4]
    viewport.clear_isolate()
    viewport.set_line_display_active(False)
    QApplication.processEvents()
    assert_dimensions(viewport)

    viewport.set_model(mixed_sections(8), reset_camera=False)
    QApplication.processEvents()
    assert_dimensions(viewport)
    assert set(root.property("cubeTags").toVariant()) == set(range(1, 9))
    viewport.set_model(StructuralModel(ndm=3, ndf=6))
    QApplication.processEvents()
    assert root.property("cubeTags").toVariant() == []
    assert root.property("sceneData").toVariant()["nodes"] == []


def test_animation_refreshes_snapshot_and_reuses_instance_objects(viewport):
    model = mixed_sections(4)
    viewport.set_model(model)
    QApplication.processEvents()
    bridge = viewport.bridge
    root = viewport.quick_widget.rootObject()
    bridge.begin_time_history_deformation(model)
    QApplication.processEvents()
    first = entries(root)[0]
    snapshot = root.property("sceneData").toVariant()
    exports_before = bridge.geometry_exports
    points = dict(bridge._points)
    points[2] = (1.0, 4.0, 0.0)
    bridge.update_deformed_node_positions(points, show_original=False, show_deformed=True)
    QApplication.processEvents()
    current = root.property("sceneData").toVariant()
    assert current["nodes"][1]["x"] == pytest.approx(1.0)
    assert snapshot["nodes"][1]["x"] == pytest.approx(0.0)
    assert bridge.geometry_exports == exports_before + 1
    assert entries(root)[0] is first
    assert_dimensions(viewport)
    bridge.end_time_history_deformation()
    QApplication.processEvents()
    assert root.property("sceneData").toVariant()["nodes"][1]["x"] == pytest.approx(0.0)
    assert_dimensions(viewport)
