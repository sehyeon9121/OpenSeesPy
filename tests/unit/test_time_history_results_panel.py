import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisResult, AnalysisStatus, NodeResult, TimeHistoryStep
from openframe.features.results.presentation.time_history_results_panel import (
    TimeHistoryResultsPanel,
)


def _panel() -> TimeHistoryResultsPanel:
    QApplication.instance() or QApplication([])
    panel = TimeHistoryResultsPanel()
    panel.show()
    return panel


def _result() -> AnalysisResult:
    steps = tuple(
        TimeHistoryStep(time=index * 0.1, node_results={1: NodeResult(1, displacement=(0.0,))})
        for index in range(10)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def test_response_history_tab_is_the_default() -> None:
    panel = _panel()

    assert panel.content_stack.currentWidget() is panel.response_history_panel
    assert panel.response_history_tab.isChecked()


def test_clicking_animation_switches_the_stack() -> None:
    panel = _panel()

    panel.animation_tab.click()

    assert panel.content_stack.currentWidget() is panel.animation_panel


def test_switching_away_from_animation_pauses_it() -> None:
    panel = _panel()
    panel.animation_tab.click()
    panel.animation_panel.set_model(_result_model())
    panel.animation_panel.show_result(_result())
    panel.animation_panel._toggle_play()
    assert panel.animation_panel._playing is True

    panel.response_history_tab.click()

    assert panel.animation_panel._playing is False


def test_show_result_reaches_both_children_without_a_separate_store() -> None:
    panel = _panel()
    result = _result()

    panel.set_model(_result_model())
    panel.show_result(result)

    assert panel.response_history_panel._result is result
    assert panel.animation_panel._result is result


def _result_model():
    from openframe.core.domain import Element, Node, StructuralModel

    return StructuralModel(
        ndm=2,
        ndf=1,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 1.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )


def _wide_model():
    from openframe.core.domain import Element, Node, StructuralModel

    return StructuralModel(
        ndm=2,
        ndf=3,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 6.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )


#: Node 1 is a support (has reaction, no varying displacement); node 2 is
#: free. Each response peaks at a different step on purpose, so "Go to Peak"
#: for different responses can be checked to land on different steps.
_DISPLACEMENT = [0.1, 0.2, -0.5, 0.3, 0.05]  # abs max: index 2, t=0.2
_VELOCITY = [0.2, -0.9, 0.1, 0.05, 0.02]  # abs max: index 1, t=0.1
_ACCELERATION = [1.0, 2.0, -1.0, 5.0, 0.5]  # abs max: index 3, t=0.3
_REACTION = [10.0, 10.5, 11.0, 10.2, 9.8]  # abs max: index 2, t=0.2


def _full_response_result() -> AnalysisResult:
    steps = tuple(
        TimeHistoryStep(
            time=index * 0.1,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0), reaction=(_REACTION[index], 0.0, 0.0)),
                2: NodeResult(
                    2,
                    displacement=(_DISPLACEMENT[index], 0.0, 0.0),
                    velocity=(_VELOCITY[index], 0.0, 0.0),
                    acceleration=(_ACCELERATION[index], 0.0, 0.0),
                ),
            },
        )
        for index in range(5)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def _select(panel: TimeHistoryResultsPanel, *, response: str, node: int, dof: int) -> None:
    response_panel = panel.response_history_panel
    response_panel.response_selector.setCurrentIndex(
        response_panel.response_selector.findData(response)
    )
    response_panel.node_selector.setCurrentIndex(response_panel.node_selector.findData(node))
    response_panel.dof_selector.setCurrentIndex(response_panel.dof_selector.findData(dof))


def _loaded_panel() -> TimeHistoryResultsPanel:
    panel = _panel()
    panel.set_model(_wide_model())
    panel.show_result(_full_response_result())
    return panel


class TestGoToPeak:
    """Phase 3-J: Response History's 'Go to Peak' jumps Animation to the
    currently-selected response/node/dof's own abs-max step - never a
    different response's peak, never a hardcoded index."""

    def test_1_displacement_abs_max_moves_animation_to_the_correct_step(self) -> None:
        panel = _loaded_panel()
        _select(panel, response="displacement", node=2, dof=0)
        assert panel.response_history_panel.go_to_peak_button.isEnabled()

        panel.response_history_panel.go_to_peak_button.click()

        assert panel.content_stack.currentWidget() is panel.animation_panel
        assert panel.animation_panel._current_step_index == 2  # t=0.2, see _DISPLACEMENT

    def test_2_velocity_and_acceleration_peaks_use_their_own_time_but_show_displacement(self) -> None:
        panel = _loaded_panel()

        _select(panel, response="acceleration", node=2, dof=0)
        panel.response_history_panel.go_to_peak_button.click()
        assert panel.animation_panel._current_step_index == 3  # t=0.3, see _ACCELERATION

        node_2_item = panel.animation_panel._node_items[2]
        scale = panel.animation_panel._active_deformation_multiplier()
        expected = panel.animation_panel.scene.project_coordinates(
            6.0 + _DISPLACEMENT[3] * scale, 0.0, 0.0
        )
        assert node_2_item.pos().x() == pytest.approx(expected.x())

        panel.response_history_tab.click()
        _select(panel, response="velocity", node=2, dof=0)
        panel.response_history_panel.go_to_peak_button.click()
        assert panel.animation_panel._current_step_index == 1  # t=0.1, see _VELOCITY

    def test_3_go_to_peak_is_disabled_for_a_no_data_reaction_selection(self) -> None:
        panel = _loaded_panel()

        _select(panel, response="reaction", node=2, dof=0)  # node 2 is free - no reaction

        assert not panel.response_history_panel.go_to_peak_button.isEnabled()

    def test_4_navigating_to_a_step_pauses_playback(self) -> None:
        panel = _loaded_panel()
        panel.animation_panel._toggle_play()
        assert panel.animation_panel._playing is True
        _select(panel, response="displacement", node=2, dof=0)

        panel.response_history_panel.go_to_peak_button.click()

        assert panel.animation_panel._playing is False

    def test_5_deformation_scale_and_undeformed_setting_survive_the_jump(self) -> None:
        panel = _loaded_panel()
        panel.animation_panel.scale_selector.setCurrentIndex(3)  # 20x fixed
        panel.animation_panel.show_undeformed_checkbox.setChecked(False)
        _select(panel, response="displacement", node=2, dof=0)

        panel.response_history_panel.go_to_peak_button.click()

        assert panel.animation_panel.scale_selector.currentIndex() == 3
        assert panel.animation_panel.show_undeformed_checkbox.isChecked() is False

    def test_6_response_history_selection_survives_a_round_trip_through_animation(self) -> None:
        panel = _loaded_panel()
        _select(panel, response="velocity", node=2, dof=0)

        panel.response_history_panel.go_to_peak_button.click()  # -> Animation
        panel.response_history_tab.click()  # -> back

        response_panel = panel.response_history_panel
        assert response_panel.response_selector.currentData() == "velocity"
        assert response_panel.node_selector.currentData() == 2
        assert response_panel.dof_selector.currentData() == 0

    def test_7_graph_click_resolves_to_the_nearest_step_and_can_jump_there(self) -> None:
        panel = _loaded_panel()
        _select(panel, response="displacement", node=2, dof=0)

        panel.response_history_panel.curve_view.time_clicked.emit(0.23)  # nearest: t=0.2, index 2

        response_panel = panel.response_history_panel
        assert response_panel._clicked_step_index == 2
        assert response_panel.view_in_animation_button.isVisible()
        assert "Step 2" in response_panel.selected_time_label.text()

        response_panel.view_in_animation_button.click()
        assert panel.animation_panel._current_step_index == 2

    def test_8_peak_at_the_first_or_last_step_is_handled_without_an_off_by_one(self) -> None:
        boundary_values = [-9.0, 1.0, 2.0, 3.0, 4.0]  # abs max at index 0
        steps = tuple(
            TimeHistoryStep(
                time=index * 0.1,
                node_results={2: NodeResult(2, displacement=(boundary_values[index], 0.0, 0.0))},
            )
            for index in range(5)
        )
        panel = _panel()
        panel.set_model(_wide_model())
        panel.show_result(AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps))
        panel.response_history_panel.node_selector.setCurrentIndex(
            panel.response_history_panel.node_selector.findData(2)
        )

        panel.response_history_panel.go_to_peak_button.click()

        assert panel.animation_panel._current_step_index == 0

    def test_9_loading_a_new_result_clears_the_stale_click_selection(self) -> None:
        panel = _loaded_panel()
        _select(panel, response="displacement", node=2, dof=0)
        panel.response_history_panel.curve_view.time_clicked.emit(0.2)
        assert panel.response_history_panel.view_in_animation_button.isVisible()

        panel.show_result(_full_response_result())

        assert panel.response_history_panel._clicked_step_index is None
        assert not panel.response_history_panel.view_in_animation_button.isVisible()

    def test_10_a_static_result_does_not_break_the_wrapper(self) -> None:
        from openframe.core.domain import ElementResult

        panel = _loaded_panel()
        static_result = AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            node_results={1: NodeResult(1, displacement=(0.001, 0.0, 0.0))},
            element_results={1: ElementResult(1)},
        )

        panel.show_result(static_result)

        assert not panel.response_history_panel.go_to_peak_button.isEnabled()
        assert panel.animation_panel._current_step_index == 0
        assert panel.animation_panel._playing is False
