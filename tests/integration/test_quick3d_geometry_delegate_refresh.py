"""Coordinate-only updates must refresh delegate source data in Quick3DViewport."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import Element, Node, StructuralModel
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_coordinate_change_updates_bridge_lists_without_topology_rebuild() -> None:
    viewport = Quick3DViewport()
    viewport.setFixedSize(640, 480)
    viewport.show()
    model = StructuralModel(ndm=3, ndf=6)
    model.nodes = {
        1: Node(1, 0.0, 0.0, 0.0, 6),
        2: Node(2, 2.0, 0.0, 0.0, 6),
    }
    model.elements = {
        1: Element(
            1,
            1,
            2,
            "elasticBeamColumn",
            properties={"behavior": "general_beam", "section_shape": "Rectangle", "width": 0.3, "height": 0.5},
        ),
    }
    viewport.set_model(model)
    for _ in range(10):
        QApplication.processEvents()

    bridge = viewport.bridge
    nodes_id = id(bridge._nodes)
    members_id = id(bridge._members)
    node_x_before = float(bridge._nodes[1]["x"])  # tag 2
    member_length_before = float(bridge._members[0]["length"])

    counts = {"topology": 0, "geometry": 0, "scene": 0}
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))
    bridge.geometry_changed.connect(lambda: counts.__setitem__("geometry", counts["geometry"] + 1))
    bridge.scene_changed.connect(lambda: counts.__setitem__("scene", counts["scene"] + 1))

    node = model.nodes[2]
    moved = replace(model, nodes={**model.nodes, 2: replace(node, x=5.0)})
    viewport.set_model(moved)
    for _ in range(5):
        QApplication.processEvents()

    assert counts == {"topology": 0, "geometry": 1, "scene": 0}
    assert id(bridge._nodes) == nodes_id
    assert id(bridge._members) == members_id
    assert float(bridge._nodes[1]["x"]) != node_x_before
    assert float(bridge._members[0]["length"]) != member_length_before
    assert bridge.geometryRevision == 1

    root = viewport.quick_widget.rootObject()
    assert root is not None
    assert root.property("bridgeReady") is True
