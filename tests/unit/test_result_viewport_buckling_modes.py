"""Buckling Modes counterpart of test_result_viewport_mode_shapes.py.

Both result types share the same mode_shape_selector widget/rendering path
(see result_viewport.py's _MODE_SELECTOR_RESULT_TYPES) - the tests here focus
on what's specific to that reuse: the combo showing buckling factors instead
of periods, drawing the *normalized* shape, and refilling correctly when the
user switches between Mode Shapes and Buckling Modes on the same result.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    BucklingMode,
    Element,
    ModeShape,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.presentation.result_viewport import ResultViewport


def _model() -> StructuralModel:
    return StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )


def _buckling_result() -> AnalysisResult:
    return AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        buckling_modes=(
            BucklingMode(
                mode_number=1,
                buckling_load_factor=12.45,
                raw_eigenvalue=12.45,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.02, 0.0, 0.0)),
                },
                normalized_node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(1.0, 0.0, 0.0)),
                },
                reference_load_case="Pattern 1",
                reference_load_scale=1.0,
            ),
            BucklingMode(
                mode_number=2,
                buckling_load_factor=37.18,
                raw_eigenvalue=37.18,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.03, 0.0)),
                },
                normalized_node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 1.0, 0.0)),
                },
                reference_load_case="Pattern 1",
                reference_load_scale=1.0,
            ),
        ),
    )


def _viewport() -> ResultViewport:
    QApplication.instance() or QApplication([])
    viewport = ResultViewport()
    viewport.set_model(_model())
    return viewport


def _displacement_vector_item(viewport: ResultViewport, node_tag: int):
    for item in viewport.scene.items():
        identity = item.data(0)
        if isinstance(identity, tuple) and identity == ("result_displacement_vector", node_tag):
            return item
    return None


def test_mode_selector_hidden_until_buckling_modes_is_selected() -> None:
    viewport = _viewport()
    assert viewport.mode_shape_selector.isHidden()

    viewport.set_result_type("buckling_modes")
    assert not viewport.mode_shape_selector.isHidden()
    assert not viewport.mode_shape_label.isHidden()

    viewport.set_result_type("moment")
    assert viewport.mode_shape_selector.isHidden()


def test_showing_a_buckling_result_populates_the_selector_with_factors() -> None:
    viewport = _viewport()
    viewport.show_result(_buckling_result())
    viewport.set_result_type("buckling_modes")

    assert viewport.mode_shape_selector.count() == 2
    assert "Mode 1" in viewport.mode_shape_selector.itemText(0)
    assert "12.45" in viewport.mode_shape_selector.itemText(0)
    assert "37.18" in viewport.mode_shape_selector.itemText(1)


def test_selecting_a_buckling_mode_redraws_that_modes_normalized_shape() -> None:
    viewport = _viewport()
    viewport.show_result(_buckling_result())
    viewport.set_result_type("buckling_modes")

    mode1_vector = _displacement_vector_item(viewport, 2)
    assert mode1_vector is not None
    mode1_end = mode1_vector.line().p2()

    viewport.mode_shape_selector.setCurrentIndex(1)

    mode2_vector = _displacement_vector_item(viewport, 2)
    assert mode2_vector is not None
    mode2_end = mode2_vector.line().p2()
    assert (mode1_end.x(), mode1_end.y()) != (mode2_end.x(), mode2_end.y())


def test_switching_between_mode_shapes_and_buckling_modes_refills_the_selector() -> None:
    """The two result types share one combo widget - switching between them on
    the *same* result (which can carry both kinds of modes, e.g. after
    re-running a different analysis on the same model) must always show the
    list matching whichever is currently selected, never a stale one."""
    modal_and_buckling = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        mode_shapes=(
            ModeShape(
                mode_number=1,
                eigenvalue=4.0,
                angular_frequency=2.0,
                frequency_hz=0.318,
                period=3.1416,
            ),
        ),
        buckling_modes=_buckling_result().buckling_modes,
    )
    viewport = _viewport()
    viewport.show_result(modal_and_buckling)

    viewport.set_result_type("mode_shapes")
    assert viewport.mode_shape_selector.count() == 1
    assert "T=" in viewport.mode_shape_selector.itemText(0)

    viewport.set_result_type("buckling_modes")
    assert viewport.mode_shape_selector.count() == 2
    assert "λ=" in viewport.mode_shape_selector.itemText(0)

    viewport.set_result_type("mode_shapes")
    assert viewport.mode_shape_selector.count() == 1


def test_buckling_modes_view_with_no_modes_shows_the_bare_undeformed_model() -> None:
    viewport = _viewport()
    viewport.show_result(AnalysisResult(status=AnalysisStatus.COMPLETED))

    viewport.set_result_type("buckling_modes")

    assert viewport.mode_shape_selector.count() == 0
    assert _displacement_vector_item(viewport, 2) is None
