"""Real QQuickWidget + structural_view.qml visibility toggles (Phase P-1 gate).

These tests drive the same Quick3DViewport the 3D modeling page embeds and
verify bridge state plus QML-side visibility helpers after each toggle.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    BoundaryCondition,
    Element,
    Node,
    NodalLoad,
    StructuralModel,
    UniformElementLoad,
)
from openframe.core.domain.model import LoadCaseKind
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _viewport_with_scene() -> Quick3DViewport:
    viewport = Quick3DViewport()
    viewport.setFixedSize(800, 600)
    viewport.show()
    model = StructuralModel(ndm=3, ndf=6)
    model.nodes = {
        1: Node(1, 0.0, 0.0, 0.0, 6),
        2: Node(2, 3.0, 0.0, 0.0, 6),
        3: Node(3, 0.0, 3.0, 0.0, 6),
    }
    model.elements = {
        10: Element(
            10,
            1,
            2,
            "elasticBeamColumn",
            properties={"behavior": "general_beam", "section_shape": "Rectangle", "width": 0.3, "height": 0.5},
        ),
        11: Element(
            11,
            1,
            3,
            "elasticBeamColumn",
            properties={"behavior": "general_beam", "section_shape": "Rectangle", "width": 0.3, "height": 0.5},
        ),
    }
    model.boundaries = [
        BoundaryCondition(1, (True, True, True, True, True, True)),
    ]
    model.nodal_loads = [
        NodalLoad(1, (0.0, 0.0, -50.0), case_type=LoadCaseKind.DEAD),
        NodalLoad(2, (0.0, 0.0, -30.0), case_type=LoadCaseKind.LIVE),
    ]
    model.element_loads = [
        UniformElementLoad(10, wy=-10.0, case_type=LoadCaseKind.DEAD),
    ]
    viewport.set_model(model)
    for _ in range(15):
        QApplication.processEvents()
    return viewport


def _signal_counter(viewport: Quick3DViewport) -> dict[str, int]:
    bridge = viewport.bridge
    counts = {
        "topology": 0,
        "geometry": 0,
        "scene": 0,
        "visibility": 0,
        "loads": 0,
        "preview": 0,
    }
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))
    bridge.geometry_changed.connect(lambda: counts.__setitem__("geometry", counts["geometry"] + 1))
    bridge.scene_changed.connect(lambda: counts.__setitem__("scene", counts["scene"] + 1))
    bridge.visibility_changed.connect(lambda: counts.__setitem__("visibility", counts["visibility"] + 1))
    bridge.loads_changed.connect(lambda: counts.__setitem__("loads", counts["loads"] + 1))
    bridge.preview_changed.connect(lambda: counts.__setitem__("preview", counts["preview"] + 1))
    return counts


def _qml_node_visible(viewport: Quick3DViewport, tag: int) -> bool:
    root = viewport.quick_widget.rootObject()
    assert root is not None
    return bool(root.nodeVisible(tag))


@pytest.mark.parametrize(
    ("action", "verify"),
    [
        ("isolate_on", lambda v: v.bridge.isolateActive and not _qml_node_visible(v, 3)),
        ("isolate_off", lambda v: not v.bridge.isolateActive and _qml_node_visible(v, 3)),
        ("loads_hide", lambda v: not v.bridge.loadsVisible),
        ("loads_show", lambda v: v.bridge.loadsVisible),
        ("filter_nodal", lambda v: v.bridge.loadFilter == "nodal"),
        ("filter_element", lambda v: v.bridge.loadFilter == "element"),
        ("supports_hide", lambda v: not v.bridge.supportsVisible),
        ("supports_show", lambda v: v.bridge.supportsVisible),
        ("local_axes_on", lambda v: v.bridge.localAxesVisible),
        ("local_axes_off", lambda v: not v.bridge.localAxesVisible),
    ],
)
def test_visibility_toggle_qml_state(action: str, verify) -> None:
    viewport = _viewport_with_scene()
    counts = _signal_counter(viewport)
    nodes_id = id(viewport.bridge._nodes)
    members_id = id(viewport.bridge._members)

    if action == "isolate_on":
        viewport.set_isolate({1, 2}, {10})
    elif action == "isolate_off":
        viewport.clear_isolate()
    elif action == "loads_hide":
        viewport.set_loads_visible(False)
    elif action == "loads_show":
        viewport.set_loads_visible(True)
    elif action == "filter_nodal":
        viewport.set_load_filter("nodal")
    elif action == "filter_element":
        viewport.set_load_filter("element")
    elif action == "supports_hide":
        viewport.set_supports_visible(False)
    elif action == "supports_show":
        viewport.set_supports_visible(True)
    elif action == "local_axes_on":
        viewport.set_local_axes_visible(True)
    elif action == "local_axes_off":
        viewport.set_local_axes_visible(False)

    for _ in range(5):
        QApplication.processEvents()

    assert verify(viewport)
    if action != "local_axes_on":
        assert counts["geometry"] == 0
    assert counts["topology"] == 0
    assert counts["scene"] == 0
    assert id(viewport.bridge._nodes) == nodes_id
    assert id(viewport.bridge._members) == members_id
