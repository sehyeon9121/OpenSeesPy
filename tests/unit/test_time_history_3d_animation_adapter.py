import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
    assert sum(timings) / len(timings) < 0.05
