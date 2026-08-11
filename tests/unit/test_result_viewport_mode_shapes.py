import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
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


def _modal_result() -> AnalysisResult:
    return AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        mode_shapes=(
            ModeShape(
                mode_number=1,
                eigenvalue=4.0,
                angular_frequency=2.0,
                frequency_hz=0.318,
                period=3.1416,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.01, 0.0, 0.0)),
                },
                mass_participation_ratio=(1.0, 0.0, 0.0),
            ),
            ModeShape(
                mode_number=2,
                eigenvalue=36.0,
                angular_frequency=6.0,
                frequency_hz=0.955,
                period=1.0472,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.02, 0.0)),
                },
                mass_participation_ratio=(0.0, 1.0, 0.0),
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


def test_mode_shape_selector_hidden_until_that_result_type_is_selected() -> None:
    viewport = _viewport()
    assert viewport.mode_shape_selector.isHidden()
    assert viewport.mode_shape_label.isHidden()

    viewport.set_result_type("mode_shapes")
    assert not viewport.mode_shape_selector.isHidden()
    assert not viewport.mode_shape_label.isHidden()

    viewport.set_result_type("moment")
    assert viewport.mode_shape_selector.isHidden()


def test_showing_a_modal_result_populates_the_mode_selector() -> None:
    viewport = _viewport()
    viewport.show_result(_modal_result())

    assert viewport.mode_shape_selector.count() == 2
    assert "Mode 1" in viewport.mode_shape_selector.itemText(0)
    assert "Mode 2" in viewport.mode_shape_selector.itemText(1)
    # First mode is a sane default so a click on "Mode Shapes" shows something
    # immediately instead of a blank canvas.
    assert viewport.mode_shape_selector.currentIndex() == 0


def test_selecting_a_mode_redraws_that_modes_deflected_shape() -> None:
    viewport = _viewport()
    viewport.show_result(_modal_result())
    viewport.set_result_type("mode_shapes")

    mode1_vector = _displacement_vector_item(viewport, 2)
    assert mode1_vector is not None
    mode1_end = mode1_vector.line().p2()

    viewport.mode_shape_selector.setCurrentIndex(1)

    mode2_vector = _displacement_vector_item(viewport, 2)
    assert mode2_vector is not None
    mode2_end = mode2_vector.line().p2()
    # Mode 1 moves node 2 along X, mode 2 moves it along Y - the drawn
    # endpoint must actually change, not just redraw the same shape twice.
    assert (mode1_end.x(), mode1_end.y()) != (mode2_end.x(), mode2_end.y())


def test_mode_shapes_view_with_no_modes_shows_the_bare_undeformed_model() -> None:
    """A linear-static result has no mode_shapes - selecting Mode Shapes must not
    crash and must fall back to just the undeformed model, not stale data."""
    viewport = _viewport()
    viewport.show_result(AnalysisResult(status=AnalysisStatus.COMPLETED))

    viewport.set_result_type("mode_shapes")

    assert viewport.mode_shape_selector.count() == 0
    assert _displacement_vector_item(viewport, 2) is None
