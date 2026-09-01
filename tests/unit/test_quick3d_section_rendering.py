"""Cross-section rendering scale and node-marker visibility in the 3D view.

Both behaviours regressed the same way: they were derived from the model's
bounding-box extent, so simply making the model bigger - copying an element,
stacking another storey - silently redrew everything already on screen.
"""

from __future__ import annotations

import math
import os

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import Element, Node, StructuralModel
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_COLUMN = {"behavior": "general_beam", "section_shape": "Rectangle", "width": 0.4, "height": 0.6}
_BEAM = {"behavior": "general_beam", "section_shape": "Rectangle", "width": 0.3, "height": 0.5}


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _storey_frame(stories: int) -> StructuralModel:
    """One 6 m bay repeated upward in 3.5 m storeys - the shape a user builds
    by drawing the ground floor and copying it up."""
    model = StructuralModel(ndm=3, ndf=6)
    tag = 1
    grid: dict[tuple[float, int], int] = {}
    for level in range(stories + 1):
        for x in (0.0, 6.0):
            grid[(x, level)] = tag
            model.nodes[tag] = Node(tag, x, 0.0, level * 3.5, 6)
            tag += 1
    element_tag = 1
    for level in range(stories):
        for x in (0.0, 6.0):
            model.elements[element_tag] = Element(
                element_tag,
                grid[(x, level)],
                grid[(x, level + 1)],
                "elasticBeamColumn",
                properties=dict(_COLUMN),
            )
            element_tag += 1
        model.elements[element_tag] = Element(
            element_tag,
            grid[(0.0, level + 1)],
            grid[(6.0, level + 1)],
            "elasticBeamColumn",
            properties=dict(_BEAM),
        )
        element_tag += 1
    return model


def _member_box(bridge: Quick3DSceneBridge, tag: int) -> tuple[float, float]:
    part = next(part for part in bridge.members if part["tag"] == tag)
    return part["width_b"], part["width_h"]


def test_section_size_is_unchanged_by_growing_the_model() -> None:
    """Copying an element must not resize the members already drawn.

    The previous bbox clamp ``extent * 0.055`` pinned a 0.4 x 0.6 column
    well below its real size on a small model, and the moment a copy pushed
    the bounding box out the clamp released and every member on screen
    jumped thicker. Assigned B/H must stay the stored values regardless of
    how large the rest of the model becomes.
    """
    _app()
    sizes = []
    for stories in (1, 2, 5):
        bridge = Quick3DSceneBridge()
        bridge.set_model(_storey_frame(stories))
        sizes.append(_member_box(bridge, 1))

    assert bridge._extent > 1.0
    for width_b, width_h in sizes:
        assert width_b == pytest.approx(_COLUMN["width"])
        assert width_h == pytest.approx(_COLUMN["height"])


def test_section_size_scales_with_the_member_not_the_bounding_box() -> None:
    """A member with no assigned section falls back to a fraction of its own
    length, so a distant copy that only widens the bounding box leaves it be."""
    _app()

    def lone_beam(with_distant_copy: bool) -> tuple[float, float]:
        model = StructuralModel(ndm=3, ndf=6)
        model.nodes[1] = Node(1, 0.0, 0.0, 0.0, 6)
        model.nodes[2] = Node(2, 6.0, 0.0, 0.0, 6)
        model.elements[1] = Element(1, 1, 2, "elasticBeamColumn", properties={})
        if with_distant_copy:
            model.nodes[3] = Node(3, 0.0, 0.0, 40.0, 6)
            model.nodes[4] = Node(4, 6.0, 0.0, 40.0, 6)
            model.elements[2] = Element(2, 3, 4, "elasticBeamColumn", properties={})
        bridge = Quick3DSceneBridge()
        bridge.set_model(model)
        return _member_box(bridge, 1)

    assert lone_beam(False) == lone_beam(True)


def test_node_marker_is_a_constant_fraction_of_the_shortest_incident_member() -> None:
    """Section size and longer framing members must not inflate a node."""
    _app()
    bridge = Quick3DSceneBridge()
    model = _storey_frame(3)
    bridge.set_model(model)

    radii = {node["tag"]: node["radius"] for node in bridge.nodes}
    incident_lengths: dict[int, list[float]] = {}
    for element in model.elements.values():
        length = math.dist(bridge._points[element.node_i], bridge._points[element.node_j])
        incident_lengths.setdefault(element.node_i, []).append(length)
        incident_lengths.setdefault(element.node_j, []).append(length)
    for tag, lengths in incident_lengths.items():
        assert radii[tag] == pytest.approx(min(lengths) * 0.018)


def test_node_marker_scale_is_independent_of_section_and_distant_members() -> None:
    _app()

    def radius(section_width: float, *, add_distant_member: bool) -> float:
        model = StructuralModel(ndm=3, ndf=6)
        model.nodes[1] = Node(1, 0.0, 0.0, 0.0, 6)
        model.nodes[2] = Node(2, 5.0, 0.0, 0.0, 6)
        model.elements[1] = Element(
            1,
            1,
            2,
            "elasticBeamColumn",
            properties={
                "section_shape": "Rectangle",
                "width": section_width,
                "height": section_width,
            },
        )
        if add_distant_member:
            model.nodes[3] = Node(3, 100.0, 0.0, 0.0, 6)
            model.nodes[4] = Node(4, 120.0, 0.0, 0.0, 6)
            model.elements[2] = Element(2, 3, 4, "elasticBeamColumn", properties={})
        bridge = Quick3DSceneBridge()
        bridge.set_model(model)
        return float(next(node["radius"] for node in bridge.nodes if node["tag"] == 1))

    expected = 5.0 * 0.018
    assert radius(0.05, add_distant_member=False) == pytest.approx(expected)
    assert radius(1.0, add_distant_member=False) == pytest.approx(expected)
    assert radius(1.0, add_distant_member=True) == pytest.approx(expected)


def test_small_structure_scales_node_markers_down_without_overlap() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 0.05, 0.0, 0.0, 6),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn", properties={})},
    )
    bridge.set_model(model)

    radii = [float(node["radius"]) for node in bridge.nodes]
    assert radii == pytest.approx([0.05 * 0.018, 0.05 * 0.018])
    assert sum(radii) < 0.05


def test_rendered_member_uses_the_full_center_to_center_length() -> None:
    """Node markers must never shorten the visual member."""
    _app()
    bridge = Quick3DSceneBridge()
    model = _storey_frame(1)
    bridge.set_model(model)

    element = model.elements[1]
    part = next(item for item in bridge.members if item["tag"] == element.tag)
    true_length = math.dist(bridge._points[element.node_i], bridge._points[element.node_j])

    assert float(part["length"]) == pytest.approx(true_length)
