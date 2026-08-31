"""Quick3D viewport Phase P-1 performance and incremental-update tests."""

from __future__ import annotations

import os
import time
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import Element, Node, NodalLoad, StructuralModel, UniformElementLoad
from openframe.core.domain.model import LoadCaseKind
from openframe.features.viewport.presentation.quick3d_perf import (
    enable_quick3d_perf,
    perf_recorder,
)
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _grid_model(columns: int, rows: int) -> StructuralModel:
    """Rectangular grid: ``columns * rows`` nodes, ``columns*(rows-1)+rows*(columns-1)`` members."""
    model = StructuralModel(ndm=3, ndf=6)
    tag = 1
    grid: dict[tuple[int, int], int] = {}
    for row in range(rows):
        for col in range(columns):
            grid[(col, row)] = tag
            model.nodes[tag] = Node(tag, float(col), float(row), 0.0, 6)
            tag += 1
    element_tag = 1
    for row in range(rows):
        for col in range(columns):
            here = grid[(col, row)]
            if col + 1 < columns:
                model.elements[element_tag] = Element(
                    element_tag,
                    here,
                    grid[(col + 1, row)],
                    element_type="elasticBeamColumn",
                    properties={"behavior": "general_beam", "section_shape": "Rectangle", "width": 0.3, "height": 0.5},
                )
                element_tag += 1
            if row + 1 < rows:
                model.elements[element_tag] = Element(
                    element_tag,
                    here,
                    grid[(col, row + 1)],
                    element_type="elasticBeamColumn",
                    properties={"behavior": "general_beam", "section_shape": "Rectangle", "width": 0.3, "height": 0.5},
                )
                element_tag += 1
    return model


def _move_node(model: StructuralModel, tag: int, dx: float, dy: float, dz: float = 0.0) -> StructuralModel:
    node = model.nodes[tag]
    updated = replace(node, x=node.x + dx, y=node.y + dy, z=node.z + dz)
    nodes = dict(model.nodes)
    nodes[tag] = updated
    return replace(model, nodes=nodes)


@pytest.fixture(autouse=True)
def _perf_off_after_test() -> None:
    yield
    enable_quick3d_perf(False)
    perf_recorder().counters.reset()


def test_coordinate_change_keeps_list_identity_and_skips_scene_changed() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(10, 10)
    bridge.set_model(model)
    nodes_id = id(bridge._nodes)
    members_id = id(bridge._members)

    moved = _move_node(model, tag=1, dx=0.5, dy=0.25)

    counts: dict[str, int] = {"scene": 0, "topology": 0, "geometry": 0}

    bridge.scene_changed.connect(lambda: counts.__setitem__("scene", counts["scene"] + 1))
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))
    bridge.geometry_changed.connect(lambda: counts.__setitem__("geometry", counts["geometry"] + 1))

    bridge.set_model(moved)

    assert id(bridge._nodes) == nodes_id
    assert id(bridge._members) == members_id
    assert counts["scene"] == 0
    assert counts["topology"] == 0
    assert counts["geometry"] == 1
    assert bridge._nodes[0]["x"] == pytest.approx(bridge._view_coordinates(0.5, 0.25, 0.0)[0])


def test_topology_change_triggers_single_full_rebuild() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(5, 5)
    bridge.set_model(model)

    counts = {"topology": 0}
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))

    new_tag = max(model.nodes) + 1
    nodes = dict(model.nodes)
    nodes[new_tag] = Node(new_tag, 99.0, 99.0, 0.0, 6)
    extended = replace(model, nodes=nodes)
    bridge.set_model(extended)

    assert counts["topology"] == 1
    assert new_tag in bridge._node_by_tag


def test_selection_emits_only_selection_changed() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    bridge.set_model(_grid_model(4, 4))

    counts = {"selection": 0, "topology": 0, "geometry": 0, "scene": 0}
    bridge.selection_changed.connect(lambda: counts.__setitem__("selection", counts["selection"] + 1))
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))
    bridge.geometry_changed.connect(lambda: counts.__setitem__("geometry", counts["geometry"] + 1))
    bridge.scene_changed.connect(lambda: counts.__setitem__("scene", counts["scene"] + 1))

    bridge.set_selection({1, 2}, {3})

    assert counts["selection"] == 1
    assert counts["topology"] == 0
    assert counts["geometry"] == 0
    assert counts["scene"] == 0


def test_repeat_set_selection_is_noop() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    bridge.set_model(_grid_model(4, 4))
    bridge.set_selection({1}, {1})

    counts = {"selection": 0}
    bridge.selection_changed.connect(lambda: counts.__setitem__("selection", counts["selection"] + 1))
    bridge.set_selection({1}, {1})
    assert counts["selection"] == 0


def test_node_marker_radius_never_shrinks_below_global_fallback() -> None:
    """A slender member's section bulge must not replace the default node
    sphere with a sub-pixel radius - reported as nodes vanishing in 3D."""
    _app()
    bridge = Quick3DSceneBridge()
    model = StructuralModel(
        ndm=3,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 4.0, 0.0, 0.0, 6),
        },
        elements={
            1: Element(1, 1, 2, "elasticBeamColumn", properties={"width": 0.01, "height": 0.01}),
        },
    )
    bridge.set_model(model)

    fallback = bridge._node_radius
    for node in bridge.nodes:
        assert node["radius"] >= fallback


def test_selected_member_highlight_lists_only_selected_parts() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(4, 4)
    bridge.set_model(model)
    first_member = next(iter(model.elements))
    bridge.set_selection(set(), {first_member})

    highlight_tags = {int(part["tag"]) for part in bridge.selectedMemberHighlight}
    assert highlight_tags == {first_member}
    assert len(bridge.selectedMemberHighlight) >= 1
    assert len(bridge.selectedMemberHighlight) < len(bridge._members)


def test_preview_segment_dedup() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    bridge.set_model(_grid_model(3, 3))

    counts = {"preview": 0, "scene": 0}
    bridge.preview_changed.connect(lambda: counts.__setitem__("preview", counts["preview"] + 1))
    bridge.scene_changed.connect(lambda: counts.__setitem__("scene", counts["scene"] + 1))

    start = (0.0, 0.0, 0.0)
    end = (1.0, 0.0, 0.0)
    bridge.set_preview_segment(start, end)
    bridge.set_preview_segment(start, end)
    bridge.set_preview_segment((0.0, 0.0, 0.0), (1.0000001, 0.0, 0.0))

    assert counts["preview"] == 1
    assert counts["scene"] == 0


def test_load_visibility_does_not_rebuild_topology() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(4, 4)
    model.nodal_loads.append(
        NodalLoad(node_tag=1, values=(0.0, 0.0, -10.0), case_type=LoadCaseKind.DEAD)
    )
    bridge.set_model(model)
    nodes_id = id(bridge._nodes)

    counts = {"topology": 0, "geometry": 0, "visibility": 0, "loads": 0}
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))
    bridge.geometry_changed.connect(lambda: counts.__setitem__("geometry", counts["geometry"] + 1))
    bridge.visibility_changed.connect(lambda: counts.__setitem__("visibility", counts["visibility"] + 1))
    bridge.loads_changed.connect(lambda: counts.__setitem__("loads", counts["loads"] + 1))

    bridge.set_loads_visible(False)
    bridge.set_load_filter("nodal")

    assert id(bridge._nodes) == nodes_id
    assert counts["topology"] == 0
    assert counts["geometry"] == 0
    assert counts["visibility"] == 2
    assert counts["loads"] == 2


def test_isolate_uses_visibility_not_topology() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    bridge.set_model(_grid_model(6, 6))
    members_id = id(bridge._members)

    counts = {"topology": 0, "visibility": 0}
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))
    bridge.visibility_changed.connect(lambda: counts.__setitem__("visibility", counts["visibility"] + 1))

    bridge.set_isolate({1, 2}, {1})
    bridge.clear_isolate()

    assert id(bridge._members) == members_id
    assert counts["topology"] == 0
    assert counts["visibility"] == 2


def test_selection_preserved_after_coordinate_update() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(5, 5)
    bridge.set_model(model)
    bridge.set_selection({1, 2}, {1})

    moved = _move_node(model, 1, 1.0, 0.0)
    bridge.set_model(moved)

    assert bridge.selectedNodeTags == [1, 2]
    assert bridge.selectedMemberTags == [1]


def test_repeated_coordinate_updates_do_not_grow_lists() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(8, 8)
    bridge.set_model(model)
    initial_nodes = len(bridge._nodes)
    initial_members = len(bridge._members)

    current = model
    for step in range(20):
        current = _move_node(current, tag=1, dx=0.01, dy=0.01)
        bridge.set_model(current)

    assert len(bridge._nodes) == initial_nodes
    assert len(bridge._members) == initial_members


@pytest.mark.parametrize(
    ("columns", "rows"),
    [
        (10, 10),
        (22, 23),
        (45, 45),
    ],
)
def test_incremental_timing_beats_full_rebuild(columns: int, rows: int) -> None:
    """Coordinate-only updates should be faster than full topology rebuilds."""
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(columns, rows)

    bridge.set_model(model)
    moved = _move_node(model, tag=1, dx=1.0, dy=0.5)

    full_start = time.perf_counter()
    bridge.set_model(moved)
    bridge._cached_topology_fingerprint = None
    bridge.set_model(moved)
    full_ms = (time.perf_counter() - full_start) * 1000.0

    bridge.set_model(model)
    inc_start = time.perf_counter()
    for _ in range(5):
        bridge.set_model(moved)
    inc_ms = (time.perf_counter() - inc_start) * 1000.0 / 5.0

    assert inc_ms < full_ms


def test_perf_recorder_counts_incremental_path() -> None:
    _app()
    enable_quick3d_perf(True)
    recorder = perf_recorder()
    recorder.counters.reset()

    bridge = Quick3DSceneBridge()
    model = _grid_model(12, 12)
    bridge.set_model(model)
    bridge.set_model(_move_node(model, 1, 0.2, 0.1))
    bridge.set_selection({1}, set())
    bridge.set_preview_segment((0, 0, 0), (1, 0, 0))
    bridge.set_loads_visible(False)

    counters = recorder.counters
    assert counters.set_model_full >= 1
    assert counters.set_model_incremental >= 1
    assert counters.geometry_updates >= 1
    assert counters.selection_updates >= 1
    assert counters.preview_updates >= 1
    assert counters.signal_emits.get("scene_changed", 0) >= 1
    assert counters.last_list_identities.get("nodes") == id(bridge._nodes)


def _h_beam_model() -> StructuralModel:
    model = StructuralModel(ndm=3, ndf=6)
    model.nodes = {
        1: Node(1, 0.0, 0.0, 0.0, 6),
        2: Node(2, 4.0, 0.0, 0.0, 6),
    }
    model.elements = {
        1: Element(
            1,
            1,
            2,
            "elasticBeamColumn",
            properties={
                "behavior": "general_beam",
                "section_shape": "H/I Section",
                "dim_H": 0.4,
                "dim_B": 0.2,
                "dim_tw": 0.008,
                "dim_tf": 0.012,
            },
        ),
    }
    return model


def _signal_counts(bridge: Quick3DSceneBridge) -> dict[str, int]:
    counts = {"scene": 0, "topology": 0, "geometry": 0, "loads": 0}
    bridge.scene_changed.connect(lambda: counts.__setitem__("scene", counts["scene"] + 1))
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))
    bridge.geometry_changed.connect(lambda: counts.__setitem__("geometry", counts["geometry"] + 1))
    bridge.loads_changed.connect(lambda: counts.__setitem__("loads", counts["loads"] + 1))
    return counts


def test_h_section_incremental_preserves_three_part_identities() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _h_beam_model()
    bridge.set_model(model)
    assert len(bridge._members) == 3
    members_id = id(bridge._members)
    web_id = id(bridge._members[0])
    flange_ids = {id(bridge._members[1]), id(bridge._members[2])}
    before_x = float(bridge._members[0]["x"])

    counts = _signal_counts(bridge)
    moved = _move_node(model, 2, 1.0, 0.0)
    bridge.set_model(moved)

    assert id(bridge._members) == members_id
    assert id(bridge._members[0]) == web_id
    assert {id(bridge._members[1]), id(bridge._members[2])} == flange_ids
    assert float(bridge._members[0]["x"]) != before_x
    assert counts == {"scene": 0, "topology": 0, "geometry": 1, "loads": 0}


def test_h_section_part_count_change_triggers_topology_rebuild() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _h_beam_model()
    bridge.set_model(model)

    counts = _signal_counts(bridge)
    element = model.elements[1]
    props = dict(element.properties)
    props["section_shape"] = "Rectangle"
    props["width"] = 0.3
    props["height"] = 0.5
    model.elements[1] = replace(element, properties=props)
    bridge.set_model(model)

    assert len(bridge._members) == 1
    assert counts["topology"] == 1
    assert counts["scene"] == 1


def test_nodal_load_magnitude_change_is_incremental() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(4, 4)
    model.nodal_loads = [NodalLoad(1, (0.0, 0.0, -10.0), case_type=LoadCaseKind.DEAD)]
    bridge.set_model(model)
    loads_id = id(bridge._load_arrows)
    magnitude_before = float(bridge._load_arrows[0]["magnitude"])
    counts = _signal_counts(bridge)

    loads = list(model.nodal_loads)
    loads[0] = NodalLoad(1, (0.0, 0.0, -25.0), case_type=LoadCaseKind.DEAD)
    bridge.set_model(replace(model, nodal_loads=loads))

    magnitude_after = float(bridge._load_arrows[0]["magnitude"])
    assert counts["topology"] == 0
    assert counts["geometry"] == 1
    assert id(bridge._load_arrows) == loads_id
    assert magnitude_after == pytest.approx(25.0)
    assert magnitude_before == pytest.approx(10.0)


def test_nodal_load_direction_change_is_incremental() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(4, 4)
    model.nodal_loads = [NodalLoad(1, (0.0, 0.0, -10.0), case_type=LoadCaseKind.DEAD)]
    bridge.set_model(model)
    rotation_before = (
        float(bridge._load_arrows[0]["qx"]),
        float(bridge._load_arrows[0]["qy"]),
        float(bridge._load_arrows[0]["qz"]),
    )
    counts = _signal_counts(bridge)

    loads = [NodalLoad(1, (10.0, 0.0, 0.0), case_type=LoadCaseKind.DEAD)]
    bridge.set_model(replace(model, nodal_loads=loads))

    rotation_after = (
        float(bridge._load_arrows[0]["qx"]),
        float(bridge._load_arrows[0]["qy"]),
        float(bridge._load_arrows[0]["qz"]),
    )
    assert counts["topology"] == 0
    assert counts["geometry"] == 1
    assert rotation_after != rotation_before


def test_element_load_magnitude_change_is_incremental() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(4, 4)
    first_element = next(iter(model.elements))
    model.element_loads = [
        UniformElementLoad(first_element, wy=-5.0, case_type=LoadCaseKind.DEAD),
    ]
    bridge.set_model(model)
    counts = _signal_counts(bridge)

    model.element_loads = [
        UniformElementLoad(first_element, wy=-20.0, case_type=LoadCaseKind.DEAD),
    ]
    bridge.set_model(model)

    assert counts["topology"] == 0
    assert counts["geometry"] == 1


def test_load_add_and_delete_trigger_topology_rebuild() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(3, 3)
    bridge.set_model(model)

    counts = _signal_counts(bridge)
    model.nodal_loads = [NodalLoad(1, (0.0, 0.0, -1.0), case_type=LoadCaseKind.DEAD)]
    bridge.set_model(model)
    assert counts["topology"] == 1
    # loadArrows notify=loads_changed; a topology rebuild that replaces the
    # arrow list has to tell that Repeater3D too, or the first applied load
    # stays invisible until some later loads_changed (undo used to be that
    # later signal - arrows appeared after reverting).
    assert counts["loads"] == 1

    counts = _signal_counts(bridge)
    bridge.set_model(replace(model, nodal_loads=[]))
    assert counts["topology"] == 1
    assert counts["loads"] == 1


def test_length_mismatch_falls_back_to_topology_rebuild() -> None:
    _app()
    enable_quick3d_perf(True)
    bridge = Quick3DSceneBridge()
    model = _grid_model(3, 3)
    model.nodal_loads = [NodalLoad(1, (0.0, 0.0, -5.0), case_type=LoadCaseKind.DEAD)]
    bridge.set_model(model)

    counts = _signal_counts(bridge)
    bridge._load_arrows.pop()
    moved = _move_node(model, 1, 0.1, 0.0)
    bridge.set_model(moved)

    assert counts["topology"] == 1
    assert perf_recorder().counters.incremental_fallbacks >= 1


def test_set_selection_filters_deleted_tags() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(3, 3)
    bridge.set_model(model)
    bridge.set_selection({1, 2, 99}, {1, 99})
    assert bridge.selectedNodeTags == [1, 2]
    assert bridge.selectedMemberTags == [1]


def test_set_isolate_filters_deleted_tags() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(3, 3)
    bridge.set_model(model)
    bridge.set_isolate({1, 99}, {99})
    assert bridge.isolateNodeTags == [1]
    assert bridge.isolateMemberTags == []


def test_isolate_tags_pruned_when_model_loses_nodes() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(3, 3)
    bridge.set_model(model)
    bridge.set_isolate({1, 2}, {1})

    nodes = dict(model.nodes)
    del nodes[2]
    bridge.set_model(replace(model, nodes=nodes))

    assert bridge.isolateActive
    assert bridge.isolateNodeTags == [1]


def test_h_section_fingerprint_stable_across_extent_change() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    compact = _h_beam_model()
    bridge.set_model(compact)
    fp_compact = bridge._cached_topology_fingerprint

    spread = _h_beam_model()
    spread.nodes[2] = Node(2, 400.0, 0.0, 0.0, 6)
    bridge.set_model(spread)
    fp_spread = bridge._cached_topology_fingerprint

    assert fp_compact == fp_spread


def test_duplicate_set_model_with_same_geometry_is_skipped() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(4, 4)
    bridge.set_model(model)

    counts = {"geometry": 0, "topology": 0}
    bridge.geometry_changed.connect(lambda: counts.__setitem__("geometry", counts["geometry"] + 1))
    bridge.topology_changed.connect(lambda: counts.__setitem__("topology", counts["topology"] + 1))

    bridge.set_model(model)
    assert counts == {"geometry": 0, "topology": 0}


def test_coordinate_update_without_loads_skips_loads_changed() -> None:
    _app()
    bridge = Quick3DSceneBridge()
    model = _grid_model(5, 5)
    bridge.set_model(model)

    counts = {"loads": 0, "geometry": 0, "metrics": 0}
    bridge.loads_changed.connect(lambda: counts.__setitem__("loads", counts["loads"] + 1))
    bridge.geometry_changed.connect(lambda: counts.__setitem__("geometry", counts["geometry"] + 1))
    bridge.scene_metrics_changed.connect(
        lambda: counts.__setitem__("metrics", counts["metrics"] + 1)
    )

    bridge.set_model(_move_node(model, max(model.nodes), 1.0, 1.0))
    assert counts["loads"] == 0
    assert counts["geometry"] == 1
    assert counts["metrics"] == 1
