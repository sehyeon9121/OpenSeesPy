import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
from openframe.features.results.presentation.time_history_3d_animation_adapter import (
    TimeHistory3DAnimationAdapter,
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


def _result() -> AnalysisResult:
    steps = tuple(
        TimeHistoryStep(
            time=float(index) * 0.05,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                2: NodeResult(2, displacement=(index * 0.001, 0.0, index * 0.002)),
            },
        )
        for index in range(4)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def test_synthetic_result_carries_only_one_step() -> None:
    result = _result()
    synthetic = TimeHistory3DAnimationAdapter.synthetic_result_for_step(result, 2)
    assert synthetic.node_results == result.time_history[2].node_results
    assert synthetic.time_history == ()


def test_adapter_step_change_updates_viewport_without_mutating_model() -> None:
    QApplication.instance() or QApplication([])
    adapter = TimeHistory3DAnimationAdapter()
    model = _model()
    result = _result()
    original_z = model.nodes[2].z

    adapter.viewport.show()
    adapter.set_model(model)
    adapter.set_result(result)
    adapter.set_step(0)
    adapter.set_step(3)
    adapter.set_translation_scale(100.0)

    assert model.nodes[2].z == original_z
    assert adapter.current_step_index() == 3
    assert len(adapter.viewport.bridge.nodes) == 2
