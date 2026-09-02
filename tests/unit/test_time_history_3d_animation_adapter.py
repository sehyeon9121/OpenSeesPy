import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Element,
    Node,
    NodeResult,
    StructuralModel,
    TimeHistoryStep,
)
from openframe.features.results.deformation.deformed_3d_state import build_deformed_3d_state
from openframe.features.results.presentation.time_history_3d_animation_adapter import (
    TimeHistory3DAnimationAdapter,
    compute_effective_marker_count,
    sanitize_rotation_scale,
)
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

_FRAME_3D = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "examples"
    / "frame_4bay_4story_3d.py"
)


def _model() -> StructuralModel:
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 0.0, 0.0, 3.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )


def _result(num_steps: int = 4) -> AnalysisResult:
    steps = tuple(
        TimeHistoryStep(
            time=float(index) * 0.05,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                2: NodeResult(2, displacement=(index * 0.001, 0.0, index * 0.002)),
            },
        )
        for index in range(num_steps)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def test_animation_keeps_member_type_colors_instead_of_displacement_ramp() -> None:
    QApplication.instance() or QApplication([])
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(_model())
    adapter.set_result(_result())
    adapter.set_step(3)

    bridge = adapter.viewport.bridge
    assert {node["color"] for node in bridge.nodes} == {"#2877b7"}
    assert {part["color"] for part in bridge.members} == {"#647789"}


def test_adapter_uses_incremental_deformation_mode() -> None:
    QApplication.instance() or QApplication([])
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(_model())
    adapter.set_result(_result())
    adapter.set_step(2)

    bridge = adapter.viewport.bridge
    assert bridge.timeHistoryDeformationActive
    assert bridge.deformationRevision >= 1
    assert len(bridge.nodes) == 2
    first_node_count = len(bridge.nodes)
    adapter.set_step(3)
    assert len(bridge.nodes) == first_node_count
    assert bridge.deformationRevision >= 2


def test_incremental_positions_match_build_deformed_3d_state() -> None:
    QApplication.instance() or QApplication([])
    model = _model()
    result = _result()
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(result)
    adapter.set_translation_scale(50.0)
    adapter.set_step(2)

    state = build_deformed_3d_state(model, result, 2, 50.0)
    assert state is not None
    bridge = adapter.viewport.bridge
    for node in bridge.nodes:
        tag = int(node["tag"])
        expected = Quick3DSceneBridge._view_coordinates(
            state.node_lookup[tag].deformed_x,
            state.node_lookup[tag].deformed_y,
            state.node_lookup[tag].deformed_z,
        )
        assert node["x"] == pytest.approx(expected[0])
        assert node["y"] == pytest.approx(expected[1])
        assert node["z"] == pytest.approx(expected[2])


def test_visibility_toggle_does_not_rebuild_scene_lists() -> None:
    QApplication.instance() or QApplication([])
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(_model())
    adapter.set_result(_result())
    adapter.set_step(1)
    bridge = adapter.viewport.bridge
    member_ref = bridge.members
    adapter.set_show_deformed(False)
    assert bridge.members is member_ref
    assert bridge.timeHistoryShowDeformed is False
    assert bridge.timeHistoryShowOriginal is True
    adapter.set_show_original(False)
    assert bridge.timeHistoryDeformationActive is False


def test_torsion_markers_incremental_update() -> None:
    QApplication.instance() or QApplication([])
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 10.0, 0.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        time_history=(
            TimeHistoryStep(
                time=0.0,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.0, 0.0, 0.05, 0.0, 0.0)),
                },
            ),
            TimeHistoryStep(
                time=0.05,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.0, 0.0, 0.1, 0.0, 0.0)),
                },
            ),
        ),
    )
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(result)
    adapter.set_show_torsion_markers(True)
    adapter.set_step(0)

    bridge = adapter.viewport.bridge
    assert bridge.torsionMarkersVisible
    marker_ref = bridge.torsionMarkers
    revision0 = bridge.torsionRevision

    adapter.set_step(1)
    assert bridge.torsionMarkers is marker_ref
    assert bridge.torsionRevision > revision0


def test_rotation_scale_does_not_move_centerline() -> None:
    QApplication.instance() or QApplication([])
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 10.0, 0.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        time_history=(
            TimeHistoryStep(
                time=0.0,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.0, 0.0, 0.05, 0.0, 0.0)),
                },
            ),
        ),
    )
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(result)
    adapter.set_translation_scale(10.0)
    adapter.set_rotation_scale(1.0)
    adapter.set_step(0)
    bridge = adapter.viewport.bridge
    nodes_rot1 = [(node["x"], node["y"], node["z"]) for node in bridge.nodes]

    adapter.set_rotation_scale(50.0)
    adapter.set_step(0)
    nodes_rot50 = [(node["x"], node["y"], node["z"]) for node in bridge.nodes]
    assert nodes_rot1 == pytest.approx(nodes_rot50)


@pytest.mark.skipif(not _FRAME_3D.exists(), reason="example model missing")
def test_incremental_step_with_torsion_markers_under_60ms() -> None:
    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=30).load(_FRAME_3D)
    node_tags = sorted(model.nodes)
    steps = tuple(
        TimeHistoryStep(
            time=index * 0.01,
            node_results={
                tag: NodeResult(
                    tag,
                    displacement=(
                        (index + tag) * 0.0001,
                        index * 0.00005,
                        index * 0.00002,
                        index * 0.00001,
                        index * 0.000008,
                        index * 0.000006,
                    ),
                )
                for tag in node_tags
            },
        )
        for index in range(150)
    )
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)

    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(result)
    adapter.set_show_torsion_markers(True)
    adapter.set_step(1)

    bridge = adapter.viewport.bridge
    assert adapter.effective_marker_count() <= 2
    initial_markers = len(bridge.torsionMarkers)
    assert initial_markers > 0
    marker_ref = bridge.torsionMarkers

    timings: list[float] = []
    for step in range(2, 102):
        start = time.perf_counter()
        adapter.set_step(step)
        QApplication.processEvents()
        timings.append(time.perf_counter() - start)

    assert len(bridge.torsionMarkers) == initial_markers
    assert bridge.torsionMarkers is marker_ref
    assert sum(timings) / len(timings) < 0.06


@pytest.mark.skipif(not _FRAME_3D.exists(), reason="example model missing")
def test_incremental_step_updates_under_50ms_on_frame_model() -> None:
    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=30).load(_FRAME_3D)
    node_tags = sorted(model.nodes)
    steps = tuple(
        TimeHistoryStep(
            time=index * 0.01,
            node_results={
                tag: NodeResult(
                    tag,
                    displacement=(
                        (index + tag) * 0.0001,
                        index * 0.00005,
                        index * 0.00002,
                    ),
                )
                for tag in node_tags
            },
        )
        for index in range(150)
    )
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)

    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(result)
    adapter.set_step(0)

    bridge = adapter.viewport.bridge
    initial_nodes = len(bridge.nodes)
    initial_members = len(bridge.members)

    timings: list[float] = []
    for step in range(1, 101):
        start = time.perf_counter()
        adapter.set_step(step)
        QApplication.processEvents()
        timings.append(time.perf_counter() - start)

    assert len(bridge.nodes) == initial_nodes
    assert len(bridge.members) == initial_members
    assert sum(timings) / len(timings) < 0.06


def _large_chain_model(beam_count: int) -> StructuralModel:
    nodes = {index: Node(index, float(index - 1), 0.0, 0.0) for index in range(1, beam_count + 2)}
    elements = {
        index: Element(index, index, index + 1, "elasticBeamColumn")
        for index in range(1, beam_count + 1)
    }
    return StructuralModel(ndm=3, ndf=6, nodes=nodes, elements=elements)


def _large_chain_result(model: StructuralModel, num_steps: int = 20) -> AnalysisResult:
    return AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        time_history=tuple(
            TimeHistoryStep(
                time=float(step) * 0.01,
                node_results={
                    tag: NodeResult(
                        tag,
                        displacement=(
                            0.0,
                            0.0,
                            0.0,
                            math.sin(step + tag) * 0.01,
                            math.cos(step) * 0.005,
                            step * 0.0001,
                        ),
                    )
                    for tag in model.nodes
                },
            )
            for step in range(num_steps)
        ),
    )


def test_compute_effective_marker_count_caps_at_500_stations() -> None:
    model = _large_chain_model(1200)
    assert compute_effective_marker_count(model, 7) == 1
    assert compute_effective_marker_count(model, 3) == 1
    assert compute_effective_marker_count(None, 5) == 5


def test_sanitize_rotation_scale_rejects_non_finite_values() -> None:
    assert sanitize_rotation_scale(float("nan")) == 1.0
    assert sanitize_rotation_scale(500.0) == 100.0
    assert sanitize_rotation_scale(-250.0) == -100.0


def test_set_result_ends_active_torsion_mode() -> None:
    QApplication.instance() or QApplication([])
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 10.0, 0.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    twisted = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        time_history=(
            TimeHistoryStep(
                time=0.0,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.0, 0.0, 0.1, 0.0, 0.0)),
                },
            ),
        ),
    )
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(twisted)
    adapter.set_show_torsion_markers(True)
    adapter.set_step(0)
    assert adapter.viewport.bridge.torsionMarkersVisible

    adapter.set_result(_result())
    assert not adapter.viewport.bridge.torsionMarkersVisible
    assert not adapter.viewport.bridge.torsionMarkers


def test_torsion_hidden_when_checkbox_off() -> None:
    QApplication.instance() or QApplication([])
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 10.0, 0.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        time_history=(
            TimeHistoryStep(
                time=0.0,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.0, 0.0, 0.1, 0.0, 0.0)),
                },
            ),
        ),
    )
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(result)
    adapter.set_show_torsion_markers(True)
    adapter.set_step(0)
    assert adapter.viewport.bridge.torsionMarkersVisible

    adapter.set_show_torsion_markers(False)
    adapter.set_step(0)
    assert not adapter.viewport.bridge.torsionMarkersVisible


def test_model_switch_clears_torsion_markers() -> None:
    QApplication.instance() or QApplication([])
    twisted_model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 10.0, 0.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        time_history=(
            TimeHistoryStep(
                time=0.0,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.0, 0.0, 0.1, 0.0, 0.0)),
                },
            ),
        ),
    )
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(twisted_model)
    adapter.set_result(result)
    adapter.set_show_torsion_markers(True)
    adapter.set_step(0)
    assert adapter.viewport.bridge.torsionMarkers

    adapter.set_model(_model())
    assert not adapter.viewport.bridge.torsionMarkers


def test_large_model_torsion_step_updates_do_not_grow_marker_list() -> None:
    QApplication.instance() or QApplication([])
    model = _large_chain_model(1200)
    result = _large_chain_result(model, num_steps=30)
    adapter = TimeHistory3DAnimationAdapter()
    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(result)
    adapter.set_marker_count(7)
    adapter.set_show_torsion_markers(True)
    adapter.set_step(0)

    bridge = adapter.viewport.bridge
    assert adapter.effective_marker_count() == 1
    initial_markers = len(bridge.torsionMarkers)
    assert initial_markers == 1200
    marker_ref = bridge.torsionMarkers

    timings: list[float] = []
    for step in range(1, 21):
        start = time.perf_counter()
        adapter.set_step(step)
        QApplication.processEvents()
        timings.append(time.perf_counter() - start)

    assert len(bridge.torsionMarkers) == initial_markers
    assert bridge.torsionMarkers is marker_ref
    assert sum(timings) / len(timings) < 0.12
