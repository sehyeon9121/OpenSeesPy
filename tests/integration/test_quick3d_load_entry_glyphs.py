"""Quick3DSceneBridge.set_load_entries - viewport glyphs for the Loads tab's
own case-based store (LoadCase/LoadEntry/LoadCombination), entirely separate
from loadArrows (which only ever reflects nodal_loads/element_loads - see
canvas_load_entries.py's own module docstring for why the two never touch).

Pure Quick3DSceneBridge/dict-level tests - no QQuickWidget/QML needed, same
approach as test_quick3d_member_section_rendering.py.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    Element,
    LoadCase,
    LoadCaseKind,
    LoadCombination,
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    Node,
    NodalLoadEntry,
    SelfWeightEntry,
    StructuralModel,
)
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge


def _bridge_with_model() -> Quick3DSceneBridge:
    QApplication.instance() or QApplication([])
    bridge = Quick3DSceneBridge()
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 4.0, 0.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        ndm=3,
    )
    bridge.set_model(model)
    return bridge


def test_nodal_entry_in_the_active_case_renders_a_shaft_and_head() -> None:
    bridge = _bridge_with_model()
    case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    entry = LoadEntry(id=1, case_id="DL", kind="nodal", target=(2,), payload=NodalLoadEntry(fz=-10.0))

    bridge.set_load_entries({1: entry}, {"DL": case}, {}, mode="case", active_case_id="DL")

    parts = bridge.loadEntryGlyphs
    roles = sorted(part["role"] for part in parts)
    assert roles == ["head", "shaft"]
    assert all(part["tag"] == 1 for part in parts)
    assert all(part["color"] == "#2563eb" for part in parts)  # DEAD colour


def test_case_mode_hides_entries_from_other_cases() -> None:
    bridge = _bridge_with_model()
    cases = {
        "DL": LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD),
        "LL": LoadCase(id="LL", name="LL", kind=LoadCaseKind.LIVE),
    }
    entries = {
        1: LoadEntry(id=1, case_id="DL", kind="nodal", target=(2,), payload=NodalLoadEntry(fz=-10.0)),
        2: LoadEntry(id=2, case_id="LL", kind="nodal", target=(2,), payload=NodalLoadEntry(fz=-5.0)),
    }

    bridge.set_load_entries(entries, cases, {}, mode="case", active_case_id="DL")
    assert {part["tag"] for part in bridge.loadEntryGlyphs} == {1}

    bridge.set_load_entries(entries, cases, {}, mode="all", active_case_id="DL")
    assert {part["tag"] for part in bridge.loadEntryGlyphs} == {1, 2}

    bridge.set_load_entries(entries, cases, {}, mode="hidden", active_case_id="DL")
    assert bridge.loadEntryGlyphs == []


def test_hidden_entry_is_never_rendered_regardless_of_mode() -> None:
    bridge = _bridge_with_model()
    case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    entry = LoadEntry(
        id=1, case_id="DL", kind="nodal", target=(2,), payload=NodalLoadEntry(fz=-10.0), hidden=True
    )

    bridge.set_load_entries({1: entry}, {"DL": case}, {}, mode="all")

    assert bridge.loadEntryGlyphs == []


def test_combination_mode_scales_by_factor_and_skips_zero_factor_cases() -> None:
    bridge = _bridge_with_model()
    cases = {
        "DL": LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD),
        "WX": LoadCase(id="WX", name="WX", kind=LoadCaseKind.WIND),
    }
    entries = {
        1: LoadEntry(id=1, case_id="DL", kind="nodal", target=(2,), payload=NodalLoadEntry(fz=-10.0)),
        2: LoadEntry(id=2, case_id="WX", kind="nodal", target=(2,), payload=NodalLoadEntry(fx=3.0)),
    }
    combination = LoadCombination(name="ULS", factors={LoadCaseKind.DEAD: 1.2})

    bridge.set_load_entries(
        entries, cases, {"ULS": combination}, mode="combination", active_combination_id="ULS"
    )

    parts = bridge.loadEntryGlyphs
    # WX has no factor in this combination, so only DL's entry shows up.
    assert {part["tag"] for part in parts} == {1}
    shaft = next(part for part in parts if part["role"] == "shaft")
    assert shaft["magnitude"] == pytest.approx(12.0)  # 10.0 * 1.2


def test_member_uniform_entry_draws_several_arrows_and_a_distribution_line() -> None:
    bridge = _bridge_with_model()
    case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    payload = MemberDistributedLoadEntry(direction="y", start_value=-5.0, end_value=-5.0)
    entry = LoadEntry(id=7, case_id="DL", kind="member_uniform", target=(1,), payload=payload)

    bridge.set_load_entries({7: entry}, {"DL": case}, {}, mode="all")

    parts = bridge.loadEntryGlyphs
    assert sum(1 for part in parts if part["role"] == "shaft") == 5
    assert sum(1 for part in parts if part["role"] == "head") == 5
    assert sum(1 for part in parts if part["role"] == "distribution_line") == 4


def test_member_linear_entry_tails_slope_between_start_and_end_value() -> None:
    """A linearly-varying load's arrow tails should trace a sloped line - the
    first arrow (start_value) and last arrow (end_value) must differ in
    length since each arrow's length already reflects its own magnitude."""
    bridge = _bridge_with_model()
    case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    payload = MemberDistributedLoadEntry(direction="y", start_value=-2.0, end_value=-10.0)
    entry = LoadEntry(id=7, case_id="DL", kind="member_linear", target=(1,), payload=payload)

    bridge.set_load_entries({7: entry}, {"DL": case}, {}, mode="all")

    shafts = [part for part in bridge.loadEntryGlyphs if part["role"] == "shaft"]
    magnitudes = [shaft["magnitude"] for shaft in shafts]
    assert magnitudes[0] == pytest.approx(2.0)
    assert magnitudes[-1] == pytest.approx(10.0)


def test_member_moment_entry_draws_a_bowtie_cone_pair_not_an_arrow() -> None:
    bridge = _bridge_with_model()
    case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    payload = MemberPointLoadEntry(direction="z", value=8.0, position=0.5)
    entry = LoadEntry(id=3, case_id="DL", kind="member_moment", target=(1,), payload=payload)

    bridge.set_load_entries({3: entry}, {"DL": case}, {}, mode="all")

    parts = bridge.loadEntryGlyphs
    assert len(parts) == 2
    assert all(part["role"] == "moment_head" for part in parts)
    assert all(part["shape"] == "#Cone" for part in parts)
    # Both cones share the same apex (the load's position along the member).
    first, second = parts
    assert first["x"] == pytest.approx(second["x"])
    assert first["y"] == pytest.approx(second["y"])
    assert first["z"] == pytest.approx(second["z"])


def test_self_weight_apply_to_all_draws_one_marker_not_one_per_member() -> None:
    bridge = _bridge_with_model()
    case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    payload = SelfWeightEntry(factor_z=-1.0, apply_to_all=True)
    entry = LoadEntry(id=9, case_id="DL", kind="self_weight", target=(), payload=payload)

    bridge.set_load_entries({9: entry}, {"DL": case}, {}, mode="all")

    parts = bridge.loadEntryGlyphs
    assert sorted(part["role"] for part in parts) == ["head", "shaft"]


def test_floor_entry_outlines_the_boundary_and_drops_a_centroid_arrow() -> None:
    QApplication.instance() or QApplication([])
    bridge = Quick3DSceneBridge()
    model = StructuralModel(
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 4.0, 0.0, 0.0),
            3: Node(3, 4.0, 4.0, 0.0),
            4: Node(4, 0.0, 4.0, 0.0),
        },
        elements={},
        ndm=3,
    )
    bridge.set_model(model)
    case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    from openframe.core.domain import FloorLoadEntry

    payload = FloorLoadEntry(magnitude=5.0, direction="-z", target_nodes=(1, 2, 3, 4))
    entry = LoadEntry(id=11, case_id="DL", kind="floor", target=(1, 2, 3, 4), payload=payload)

    bridge.set_load_entries({11: entry}, {"DL": case}, {}, mode="all")

    parts = bridge.loadEntryGlyphs
    assert sum(1 for part in parts if part["role"] == "distribution_line") == 4  # closed loop
    assert sum(1 for part in parts if part["role"] == "shaft") == 1
    assert sum(1 for part in parts if part["role"] == "head") == 1
