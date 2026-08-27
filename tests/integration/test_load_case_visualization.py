from pathlib import Path

import pytest

from openframe.core.domain import Element, LoadCaseKind, Node, NodalLoad, StructuralModel
from openframe.core.domain.load_case import LoadCase
from openframe.core.domain.load_entry import FloorLoadEntry, LoadEntry, NodalLoadEntry
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter


def test_declared_dead_and_live_patterns_are_collected_coloured_and_filterable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dead_and_live.py"
    source.write_text(
        """
import openseespy.opensees as ops

OPENFRAME_LOAD_CASES = {1: "DEAD", 2: "LIVE"}

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)
ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 0.0, 0.0, 3.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)
ops.geomTransf("Linear", 1, 1.0, 0.0, 0.0)
ops.element("elasticBeamColumn", 1, 1, 2, 0.02, 2.0e8, 7.7e7,
            1.6e-4, 8.0e-5, 8.0e-5, 1)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(2, 0.0, 0.0, -10.0, 0.0, 0.0, 0.0)
ops.eleLoad("-ele", 1, "-type", "-beamUniform", 0.0, -2.0, 0.0)

ops.timeSeries("Linear", 2)
ops.pattern("Plain", 2, 2)
ops.load(2, 0.0, 0.0, -5.0, 0.0, 0.0, 0.0)
ops.eleLoad("-ele", 1, "-type", "-beamUniform", 0.0, -1.0, 0.0)
""",
        encoding="utf-8",
    )

    model = OpenSeesModelImporter(timeout_seconds=20).load(source)

    assert [load.pattern_tag for load in model.nodal_loads] == [1, 2]
    assert [load.case_type for load in model.nodal_loads] == [
        LoadCaseKind.DEAD,
        LoadCaseKind.LIVE,
    ]
    assert [load.pattern_tag for load in model.element_loads] == [1, 2]
    assert [load.case_type for load in model.element_loads] == [
        LoadCaseKind.DEAD,
        LoadCaseKind.LIVE,
    ]

    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    assert {part["case_type"] for part in bridge.loadArrows} == {"DEAD", "LIVE"}

    bridge.set_load_case_filter("DEAD")
    assert {part["case_type"] for part in bridge.loadArrows} == {"DEAD"}
    assert {part["color"] for part in bridge.loadArrows} == {"#2563eb"}

    bridge.set_load_case_filter("LIVE")
    assert {part["case_type"] for part in bridge.loadArrows} == {"LIVE"}
    assert {part["color"] for part in bridge.loadArrows} == {"#16a34a"}


def test_a_moment_only_nodal_load_gets_a_bowtie_glyph_via_load_arrows() -> None:
    """Regression test: a nodal load's mx/my/mz used to render nothing at
    all - only fx/fy/fz became an arrow - reported as "절점 하중에서 모멘트
    하중의 캔버스 상의 표현 아이콘이나 화살표가 없음". Covers the raw
    ``model.nodal_loads`` path (``loadArrows``/``_build_load_arrows``)."""
    model = StructuralModel(
        ndm=3, ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, 3.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
        nodal_loads=[NodalLoad(2, (0.0, 0.0, 0.0, 0.0, 0.0, 25.0))],
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    moment_parts = [part for part in bridge.loadArrows if part.get("role") == "moment_head"]
    assert len(moment_parts) == 2  # the bowtie is two opposing cones
    assert all(part["shape"] == "#Cone" for part in moment_parts)
    assert all(part["magnitude"] == 25.0 for part in moment_parts)


def test_a_moment_only_nodal_load_entry_gets_a_bowtie_glyph_via_load_entry_glyphs() -> None:
    """Same regression as above, for the newer case-based Loads tab store
    (``loadEntryGlyphs``/``_nodal_entry_parts``), which is entirely separate
    from ``loadArrows`` (see ``Quick3DSceneBridge.set_load_entries``)."""
    model = StructuralModel(
        ndm=3, ndf=6,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, 3.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    load_case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    entry = LoadEntry(id=1, case_id="DL", kind="nodal", target=(2,), payload=NodalLoadEntry(mz=25.0))
    bridge.set_load_entries({1: entry}, {"DL": load_case}, {}, mode="case", active_case_id="DL")

    moment_parts = [part for part in bridge.loadEntryGlyphs if part.get("role") == "moment_head"]
    assert len(moment_parts) == 2
    assert all(part["shape"] == "#Cone" for part in moment_parts)
    assert all(part["magnitude"] == 25.0 for part in moment_parts)


def test_floor_boundary_renders_as_a_closed_non_self_intersecting_loop_in_target_order() -> None:
    """Regression guard for the click-picking feature: entry.target must be
    connected in ITS OWN stored order (never re-sorted by tag) - a rectangle
    whose node tags are numbered "diagonally" (so sorting by tag would draw
    a self-crossing bowtie) must still render as the correct closed
    rectangle when target preserves the real click/boundary order.

    Distinguished by total edge length: a proper rectangle's perimeter (14,
    for a 4x3 rectangle) is strictly shorter than the same 4 points connected
    in the "wrong" (tag-sorted, diagonal-first) order (16) - the geometric
    signature of a crossing vs. non-crossing Hamiltonian cycle through the
    same 4 points.
    """
    model = StructuralModel(
        ndm=3, ndf=6,
        nodes={
            # Tags deliberately NOT in boundary-walk order: tag-sorted this
            # visits (0,0) -> (4,3) -> (4,0) -> (0,3), the crossing diagonal
            # order _floor_entry_parts must NOT produce.
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 4.0, 3.0, 0.0),
            3: Node(3, 4.0, 0.0, 0.0),
            4: Node(4, 0.0, 3.0, 0.0),
        },
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    load_case = LoadCase(id="DL", name="DL", kind=LoadCaseKind.DEAD)
    # Real click/boundary order: (0,0) -> (4,0) -> (4,3) -> (0,3) -> close.
    entry = LoadEntry(
        id=1, case_id="DL", kind="floor", target=(1, 3, 2, 4),
        payload=FloorLoadEntry(magnitude=0.0, target_nodes=(1, 3, 2, 4)),
    )
    bridge.set_load_entries({1: entry}, {"DL": load_case}, {}, mode="case", active_case_id="DL")

    segments = [part for part in bridge.loadEntryGlyphs if part.get("role") == "distribution_line"]
    assert len(segments) == 4  # a closed quadrilateral has 4 edges
    total_length = sum(part["length"] for part in segments)
    assert total_length == pytest.approx(14.0)  # the true rectangle perimeter, not 16 (bowtie)


def test_floor_boundary_outline_draws_an_open_polyline_between_picked_points() -> None:
    """set_floor_boundary_outline (the yellow "next node" trace shown while
    floor-boundary click-picking is in progress) replaced an opaque
    fan-triangulated ghost face that was rebuilt on every mouse-move and made
    the viewport lag. It must draw one thin edge per consecutive pair of
    points, left OPEN (no edge from the last point back to the first) -
    closing only happens once picking actually finishes, via the committed
    entry's own boundary loop (see the closed-loop test above)."""
    model = StructuralModel(
        ndm=3, ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 4.0, 0.0, 0.0),
            3: Node(3, 4.0, 3.0, 0.0),
        },
    )
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    bridge.set_floor_boundary_outline([(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0)])

    segments = bridge.floorBoundaryOutline
    assert len(segments) == 2  # two points picked so far -> two edges, not a closed triangle
    assert sum(part["length"] for part in segments) == pytest.approx(7.0)  # 4 + 3, not +5 closing


def test_floor_boundary_outline_clears_below_two_points() -> None:
    bridge = Quick3DSceneBridge()
    bridge.set_floor_boundary_outline([(0.0, 0.0, 0.0)])

    assert bridge.floorBoundaryOutline == []
