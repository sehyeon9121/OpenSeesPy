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
from openframe.features.results.presentation.time_history_animation_panel import (
    TimeHistoryAnimationPanel,
)


def _model() -> StructuralModel:
    return StructuralModel(
        ndm=2,
        ndf=3,
        nodes={
            1: Node(1, 0.0, 0.0),
            2: Node(2, 6.0, 0.0),
            3: Node(3, 0.0, 3.0),
            4: Node(4, 6.0, 3.0),
        },
        elements={
            1: Element(1, 1, 3, "elasticBeamColumn"),
            2: Element(2, 2, 4, "elasticBeamColumn"),
            3: Element(3, 3, 4, "elasticBeamColumn"),
        },
    )


def _result(num_steps: int = 50, dt: float = 0.1) -> AnalysisResult:
    steps = tuple(
        TimeHistoryStep(
            time=index * dt,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                2: NodeResult(2, displacement=(0.0, 0.0, 0.0)),
                3: NodeResult(3, displacement=(index * 0.01, 0.0, 0.0)),
                4: NodeResult(4, displacement=(index * 0.01, -index * 0.002, 0.0)),
            },
        )
        for index in range(num_steps)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def _panel() -> TimeHistoryAnimationPanel:
    QApplication.instance() or QApplication([])
    panel = TimeHistoryAnimationPanel()
    panel.show()  # isVisible() reflects state only once the widget chain is shown.
    return panel


def _loaded_panel(
    num_steps: int = 50, dt: float = 0.1
) -> tuple[TimeHistoryAnimationPanel, AnalysisResult]:
    panel = _panel()
    result = _result(num_steps, dt)
    panel.set_model(_model())
    panel.show_result(result)
    return panel, result


def test_1_initial_state_is_step_zero_and_paused() -> None:
    panel, _ = _loaded_panel()

    assert panel._current_step_index == 0
    assert panel._playing is False


def test_2_step_geometry_matches_original_plus_displacement_times_scale() -> None:
    panel, result = _loaded_panel()

    panel._apply_step(10)

    scale = panel._active_deformation_multiplier()
    node3_result = result.time_history[10].node_results[3]
    expected = panel.scene.project_coordinates(
        0.0 + node3_result.displacement[0] * scale, 3.0, 0.0
    )
    actual = panel._node_items[3].pos()
    assert actual.x() == pytest.approx(expected.x())
    assert actual.y() == pytest.approx(expected.y())


def test_3_slider_moves_to_the_exact_step_and_updates_the_time_label() -> None:
    panel, result = _loaded_panel()

    panel.slider.setValue(25)

    assert panel._current_step_index == 25
    expected_time = result.time_history[25].time
    assert f"{expected_time:.3f}" in panel.time_step_label.text()
    assert "Step 25" in panel.time_step_label.text()


def test_4_timer_tick_advances_the_step_while_playing() -> None:
    panel, _ = _loaded_panel()
    panel._go_to_first()
    panel._toggle_play()
    assert panel._playing is True

    for _ in range(5):
        panel._on_tick()

    assert panel._current_step_index > 0


def test_5_pause_stops_the_index_from_advancing() -> None:
    panel, _ = _loaded_panel()
    panel._go_to_first()
    panel._toggle_play()
    panel._on_tick()
    panel._set_playing(False)
    index_after_pause = panel._current_step_index

    for _ in range(10):
        panel._on_tick()

    assert panel._current_step_index == index_after_pause


def test_6_reaching_the_last_step_auto_stops_and_keeps_the_last_frame() -> None:
    panel, result = _loaded_panel(num_steps=50)
    panel._go_to_last()
    panel._playback_time = panel._times[-1]
    panel._set_playing(True)

    panel._on_tick()

    assert panel._playing is False
    assert panel._current_step_index == len(result.time_history) - 1


def test_7_playback_speed_changes_how_fast_steps_progress() -> None:
    panel_slow, _ = _loaded_panel()
    panel_fast, _ = _loaded_panel()
    panel_slow.speed_selector.setCurrentIndex(0)  # 0.25x
    panel_fast.speed_selector.setCurrentIndex(4)  # 4x
    for panel in (panel_slow, panel_fast):
        panel._go_to_first()
        panel._toggle_play()

    for _ in range(3):
        panel_slow._on_tick()
        panel_fast._on_tick()

    assert panel_fast._current_step_index >= panel_slow._current_step_index


def test_8_deformation_scale_changes_geometry_but_not_the_result_data() -> None:
    panel, result = _loaded_panel()
    panel._apply_step(10)
    original_displacement = result.time_history[10].node_results[3].displacement

    panel.scale_selector.setCurrentIndex(3)  # 20x fixed multiplier
    position_at_20x = panel._node_items[3].pos()
    panel.scale_selector.setCurrentIndex(2)  # 10x fixed multiplier
    position_at_10x = panel._node_items[3].pos()

    assert result.time_history[10].node_results[3].displacement == original_displacement
    assert (position_at_20x.x(), position_at_20x.y()) != (position_at_10x.x(), position_at_10x.y())


def test_9_show_undeformed_shape_toggle_controls_the_undeformed_layer() -> None:
    panel, _ = _loaded_panel()
    undeformed_items = [
        item
        for item in panel.scene.items()
        if isinstance(item.data(0), tuple) and item.data(0) and item.data(0)[0] in {"node", "element"}
    ]
    assert undeformed_items

    panel.show_undeformed_checkbox.setChecked(False)
    assert all(not item.isVisible() for item in undeformed_items)

    panel.show_undeformed_checkbox.setChecked(True)
    assert all(item.isVisible() for item in undeformed_items)


def test_10_empty_time_history_shows_a_safe_message_instead_of_crashing() -> None:
    panel = _panel()
    panel.set_model(_model())

    panel.show_result(AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=()))

    assert panel.empty_label.isVisible()
    assert not panel._canvas_stack.isVisible()
    assert panel._current_step_index == 0


def test_10b_no_time_history_result_at_all_is_also_safe() -> None:
    panel = _panel()
    panel.set_model(_model())

    panel.clear_result()

    assert panel.empty_label.isVisible()
    assert "Time History" in panel.empty_label.text()


def test_11_loading_a_new_result_resets_playback_state() -> None:
    panel, result = _loaded_panel()
    panel._go_to_last()
    panel._toggle_play()
    assert panel._playing is True or panel._current_step_index == len(result.time_history) - 1

    panel.show_result(_result(num_steps=30))

    assert panel._current_step_index == 0
    assert panel._playing is False


def test_12_other_analysis_kind_results_are_unaffected() -> None:
    """A static result (no time_history) must not confuse the animation panel,
    and ResultsWorkspace's other sub-panels must keep working normally - the
    heavy regression coverage for Linear/Nonlinear/Modal itself lives in the
    existing result_viewport/result_summary test files, unaffected by this
    phase since ResultViewport/StructuralScene.set_model were only read from,
    never modified."""
    from openframe.core.domain import ElementResult

    panel, _ = _loaded_panel()
    panel._go_to_last()

    static_result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={1: NodeResult(1, displacement=(0.001, 0.0, 0.0))},
        element_results={1: ElementResult(1)},
    )
    panel.show_result(static_result)

    assert panel._current_step_index == 0
    assert panel._playing is False
    assert panel.empty_label.isVisible()


def test_13_a_realistic_4096_step_result_loads_and_plays_without_error() -> None:
    panel, result = _loaded_panel(num_steps=4096, dt=0.01)

    panel._go_to_last()
    assert panel._current_step_index == 4095

    panel._go_to_first()
    panel._toggle_play()
    for _ in range(20):
        panel._on_tick()
    assert panel._current_step_index > 0
    assert panel._current_step_index < 4095

    panel.scale_selector.setCurrentIndex(0)  # Auto - forces the one-time full scan
    panel._apply_step(2000)
    assert panel.time_step_label.text() != "—"
