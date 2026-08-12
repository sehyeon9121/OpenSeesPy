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
