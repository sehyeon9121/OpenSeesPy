import os

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
from openframe.features.results.presentation.time_history_animation_panel import (
    TimeHistoryAnimationPanel,
)
from openframe.features.results.presentation.time_history_results_panel import (
    TimeHistoryResultsPanel,
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


def _result(num_steps: int = 20) -> AnalysisResult:
    steps = tuple(
        TimeHistoryStep(
            time=index * 0.05,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                2: NodeResult(
                    2,
                    displacement=(index * 0.001, 0.0, index * 0.002),
                ),
            },
        )
        for index in range(num_steps)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def _panel() -> TimeHistoryAnimationPanel:
    QApplication.instance() or QApplication([])
    panel = TimeHistoryAnimationPanel()
    panel.show()
    return panel


def test_3d_model_uses_quick3d_canvas() -> None:
    panel = _panel()
    panel.set_model(_model())

    assert panel._canvas_stack.currentWidget() is panel._3d_view
    assert panel.show_deformed_checkbox.isVisible()


def test_3d_step_changes_deformed_coordinates() -> None:
    panel = _panel()
    model = _model()
    result = _result()
    panel.set_model(model)
    panel.show_result(result)

    state0 = build_deformed_3d_state(model, result, 0, panel._active_deformation_multiplier())
    panel._apply_step(10)
    state10 = build_deformed_3d_state(model, result, 10, panel._active_deformation_multiplier())

    assert state0 is not None and state10 is not None
    assert state10.node_lookup[2].deformed_z != pytest.approx(state0.node_lookup[2].deformed_z)


def test_current_step_changed_updates_response_graph() -> None:
    QApplication.instance() or QApplication([])
    wrapper = TimeHistoryResultsPanel()
    wrapper.show()
    wrapper.set_model(_model())
    wrapper.show_result(_result())

    wrapper.animation_panel._apply_step(7)

    assert wrapper.response_history_panel._animation_step_index == 7


def test_slider_emits_current_step_changed_without_looping() -> None:
    panel = _panel()
    panel.set_model(_model())
    panel.show_result(_result())
    received: list[int] = []
    panel.current_step_changed.connect(received.append)

    panel.slider.setValue(5)

    assert received == [5]


def test_play_pause_and_loop_restart() -> None:
    panel = _panel()
    panel.set_model(_model())
    panel.show_result(_result(num_steps=5))
    panel.loop_checkbox.setChecked(True)
    panel._go_to_last()
    panel._playback_time = panel._times[-1]
    panel._set_playing(True)

    panel._on_tick()

    assert panel._current_step_index == 0
    assert panel._playing is True


def test_marker_density_status_shows_when_capped() -> None:
    from openframe.features.results.presentation.time_history_3d_animation_adapter import (
        compute_effective_marker_count,
    )

    panel = _panel()
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={index: Node(index, float(index - 1), 0.0, 0.0) for index in range(1, 1202)},
        elements={
            index: Element(index, index, index + 1, "elasticBeamColumn")
            for index in range(1, 1201)
        },
    )
    panel.set_model(model)
    panel.marker_density_selector.setCurrentIndex(2)  # 7
    panel._update_marker_density_status()

    assert compute_effective_marker_count(model, 7) == 1
    assert panel.marker_density_status_label.isVisible()
    assert "성능 제한" in panel.marker_density_status_label.text()
    assert "요청 7" in panel.marker_density_status_label.text()
