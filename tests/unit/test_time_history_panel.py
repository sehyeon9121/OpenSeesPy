import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    NodeResult,
    StructuralModel,
    TimeHistoryStep,
)
from openframe.features.results.presentation.time_history_panel import TimeHistoryPanel


def _panel() -> TimeHistoryPanel:
    QApplication.instance() or QApplication([])
    return TimeHistoryPanel()


def _time_history_result() -> AnalysisResult:
    steps = tuple(
        TimeHistoryStep(
            time=index * 0.1,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0), reaction=(1.0, 2.0, 0.0)),
                2: NodeResult(2, displacement=(index * 0.5, -index * 0.25, 0.01 * index)),
            },
        )
        for index in range(5)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def _full_response_result() -> AnalysisResult:
    """Node 1 is a support (has reaction, no free displacement); Node 2 is
    free (has displacement/velocity/acceleration, no reaction) - the same
    real-world split every fixed-base model has."""
    values = [3.0, -8.0, 5.0, -2.0, 1.0]  # abs max is index 1 (-8.0) at t=0.1
    steps = tuple(
        TimeHistoryStep(
            time=index * 0.1,
            node_results={
                1: NodeResult(1, displacement=(0.0, 0.0, 0.0), reaction=(10.0 + index, 0.0, 0.0)),
                2: NodeResult(
                    2,
                    displacement=(values[index] * 0.1, 0.0, 0.0),
                    velocity=(values[index] * 0.2, 0.0, 0.0),
                    acceleration=(values[index], 0.0, 0.0),
                ),
            },
        )
        for index in range(5)
    )
    return AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=steps)


def test_node_selector_lists_every_node_from_the_first_time_step() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))

    panel.show_result(_time_history_result())

    labels = [panel.node_selector.itemText(index) for index in range(panel.node_selector.count())]
    assert labels == ["Node 1", "Node 2"]


def test_dof_selector_matches_the_models_ndf_and_labels() -> None:
    panel = _panel()

    panel.set_model(StructuralModel(ndm=2))
    labels_2d = [panel.dof_selector.itemText(i) for i in range(panel.dof_selector.count())]
    assert labels_2d == ["UX", "UY", "RZ"]

    panel.set_model(StructuralModel(ndm=3, ndf=6))
    labels_3d = [panel.dof_selector.itemText(i) for i in range(panel.dof_selector.count())]
    assert labels_3d == ["UX", "UY", "UZ", "RX", "RY", "RZ"]


def test_selecting_a_node_and_dof_plots_the_correct_series() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(_time_history_result())

    panel.node_selector.setCurrentIndex(panel.node_selector.findData(2))
    panel.dof_selector.setCurrentIndex(panel.dof_selector.findData(0))  # UX

    assert panel.curve_view._times == pytest.approx((0.0, 0.1, 0.2, 0.3, 0.4))
    assert panel.curve_view._values == pytest.approx((0.0, 0.5, 1.0, 1.5, 2.0))

    panel.dof_selector.setCurrentIndex(panel.dof_selector.findData(1))  # UY
    assert panel.curve_view._values == pytest.approx((0.0, -0.25, -0.5, -0.75, -1.0))


def test_clear_result_empties_the_node_selector_and_the_plotted_series() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(_time_history_result())

    panel.clear_result()

    assert panel.node_selector.count() == 0
    assert panel.curve_view._times == ()


def _select(panel: TimeHistoryPanel, *, response: str, node: int, dof: int) -> None:
    panel.response_selector.setCurrentIndex(panel.response_selector.findData(response))
    panel.node_selector.setCurrentIndex(panel.node_selector.findData(node))
    panel.dof_selector.setCurrentIndex(panel.dof_selector.findData(dof))


class TestResponseKinds:
    """Phase 3-H: a RESPONSE selector (Displacement/Velocity/Acceleration/
    Reaction) alongside the existing Node/DOF pickers - each reads a
    different NodeResult field, straight from AnalysisResult.time_history."""

    def test_each_response_kind_plots_its_own_node_result_field(self) -> None:
        panel = _panel()
        panel.set_model(StructuralModel(ndm=2))
        panel.show_result(_full_response_result())

        _select(panel, response="displacement", node=2, dof=0)
        assert panel.curve_view._values == pytest.approx((0.3, -0.8, 0.5, -0.2, 0.1))

        _select(panel, response="velocity", node=2, dof=0)
        assert panel.curve_view._values == pytest.approx((0.6, -1.6, 1.0, -0.4, 0.2))

        _select(panel, response="acceleration", node=2, dof=0)
        assert panel.curve_view._values == pytest.approx((3.0, -8.0, 5.0, -2.0, 1.0))

        _select(panel, response="reaction", node=1, dof=0)
        assert panel.curve_view._values == pytest.approx((10.0, 11.0, 12.0, 13.0, 14.0))

    def test_acceleration_shows_a_relative_not_absolute_note(self) -> None:
        panel = _panel()
        panel.set_model(StructuralModel(ndm=2))
        panel.show_result(_full_response_result())

        _select(panel, response="displacement", node=2, dof=0)
        assert not panel.status_note.isVisible() or "relative" not in panel.status_note.text().lower()

        _select(panel, response="acceleration", node=2, dof=0)
        assert "relative" in panel.status_note.text().lower()
        assert "absolute" in panel.status_note.text().lower()

    def test_reaction_on_a_free_node_is_reported_as_no_data_not_zero(self) -> None:
        """Node 2 is free (never in fixed_nodes) - the solver never writes a
        reaction key for it, so this must read as "no data", not silently
        plot an empty/zero curve as if reaction were genuinely zero there."""
        panel = _panel()
        panel.set_model(StructuralModel(ndm=2))
        panel.show_result(_full_response_result())

        _select(panel, response="reaction", node=2, dof=0)

        assert panel.curve_view._values == ()
        assert panel.summary_values["max"].text() == "—"

    def test_missing_dof_on_a_lower_ndf_model_is_reported_as_no_data(self) -> None:
        result = AnalysisResult(
            status=AnalysisStatus.COMPLETED,
            time_history=(
                TimeHistoryStep(time=0.0, node_results={1: NodeResult(1, displacement=(0.1, 0.2))}),
            ),
        )
        panel = _panel()
        panel.set_model(StructuralModel(ndm=2, ndf=3))
        panel.show_result(result)

        _select(panel, response="displacement", node=1, dof=2)  # RZ - not in a 2-value tuple

        assert panel.curve_view._values == ()

    def test_switching_response_kind_updates_the_summary_values(self) -> None:
        panel = _panel()
        panel.set_model(StructuralModel(ndm=2))
        panel.show_result(_full_response_result())

        _select(panel, response="acceleration", node=2, dof=0)

        assert panel.summary_values["max"].text() == "+5 m/s²"
        assert panel.summary_values["min"].text() == "-8 m/s²"
        assert panel.summary_values["abs_max"].text() == "8 m/s²"
        assert panel.summary_values["abs_max_time"].text() == "0.1 s"


class TestSummaryStatistics:
    def test_max_min_abs_max_and_its_time_are_computed_correctly(self) -> None:
        panel = _panel()
        panel.set_model(StructuralModel(ndm=2))
        panel.show_result(_full_response_result())

        _select(panel, response="acceleration", node=2, dof=0)

        # values = [3, -8, 5, -2, 1] at times [0, 0.1, 0.2, 0.3, 0.4]
        assert panel.summary_values["max"].text() == "+5 m/s²"
        assert panel.summary_values["min"].text() == "-8 m/s²"
        assert panel.summary_values["abs_max"].text() == "8 m/s²"
        assert panel.summary_values["abs_max_time"].text() == "0.1 s"

    def test_peak_marker_matches_the_computed_abs_max(self) -> None:
        panel = _panel()
        panel.set_model(StructuralModel(ndm=2))
        panel.show_result(_full_response_result())

        _select(panel, response="acceleration", node=2, dof=0)

        assert panel.curve_view._marker == pytest.approx((0.1, -8.0))


def test_graph_click_displays_the_selected_curve_value_and_unit() -> None:
    panel = _panel()
    panel.set_model(StructuralModel(ndm=2))
    panel.show_result(_full_response_result())
    _select(panel, response="acceleration", node=2, dof=0)

    panel.curve_view.time_clicked.emit(0.18)  # nearest step: 0.2 s, value +5

    assert panel._clicked_step_index == 2
    assert panel.curve_view._selected_point == pytest.approx((0.2, 5.0))
    assert "t = 0.200 s" in panel.curve_view._selected_label
    assert "Acceleration UX = +5 m/s²" in panel.curve_view._selected_label
    assert "Acceleration UX: +5 m/s²" in panel.selected_time_label.text()
