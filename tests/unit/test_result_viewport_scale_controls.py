import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
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
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 10.0, 0.0)},
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )


def _result() -> AnalysisResult:
    return AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
            2: NodeResult(2, displacement=(0.5, 0.0, 0.0)),
        },
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


def test_real_deform_draws_at_true_scale_and_disables_the_slider() -> None:
    viewport = _viewport()
    viewport.show_result(_result())
    viewport.set_result_type("displacement")
    viewport.deformation_scale.setValue(50)

    # Node 2 sits at x=10 - the drawn endpoint is its base position plus ux * scale.
    exaggerated = _displacement_vector_item(viewport, 2)
    assert exaggerated is not None
    exaggerated_x = exaggerated.line().p2().x()
    assert exaggerated_x == pytest.approx(10.0 + 0.5 * 50)

    assert viewport.deformation_scale.isEnabled()
    viewport.real_deform.setChecked(True)
    assert not viewport.deformation_scale.isEnabled()

    real = _displacement_vector_item(viewport, 2)
    assert real is not None
    assert real.line().p2().x() == pytest.approx(10.0 + 0.5 * 1)
    assert viewport.scale_value.text() == "x1 (REAL)"

    viewport.real_deform.setChecked(False)
    assert viewport.deformation_scale.isEnabled()
    restored = _displacement_vector_item(viewport, 2)
    assert restored.line().p2().x() == pytest.approx(10.0 + 0.5 * 50)


def test_auto_scale_picks_a_multiplier_from_model_span_and_peak_displacement() -> None:
    """Span is 10 (nodes at x=0 and x=10), peak displacement 0.5 - at the 8%
    rule of thumb that is (10*0.08)/0.5 = 1.6, rounded to 2."""
    viewport = _viewport()
    viewport.show_result(_result())
    viewport.set_result_type("displacement")

    viewport.auto_scale_button.click()

    assert viewport.deformation_scale.value() == 2


def test_auto_scale_button_is_a_no_op_without_a_result() -> None:
    viewport = _viewport()
    viewport.deformation_scale.setValue(30)

    viewport.auto_scale_button.click()

    assert viewport.deformation_scale.value() == 30


def test_real_deform_and_auto_scale_hidden_for_force_diagrams() -> None:
    viewport = _viewport()
    viewport.show_result(_result())

    viewport.set_result_type("displacement")
    assert not viewport.real_deform.isHidden()
    assert not viewport.auto_scale_button.isHidden()

    viewport.set_result_type("moment")
    assert viewport.real_deform.isHidden()
    assert viewport.auto_scale_button.isHidden()


def test_auto_scale_uses_the_selected_mode_shapes_displacement() -> None:
    viewport = _viewport()
    viewport.show_result(
        AnalysisResult(
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
                        2: NodeResult(2, displacement=(0.5, 0.0, 0.0)),
                    },
                ),
                ModeShape(
                    mode_number=2,
                    eigenvalue=36.0,
                    angular_frequency=6.0,
                    frequency_hz=0.955,
                    period=1.0472,
                    node_results={
                        1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
                        2: NodeResult(2, displacement=(0.0, 0.1, 0.0)),
                    },
                ),
            ),
        )
    )
    viewport.set_result_type("mode_shapes")

    viewport.mode_shape_selector.setCurrentIndex(1)
    viewport.auto_scale_button.click()
    # Mode 2's peak is 0.1: (10*0.08)/0.1 = 8.
    assert viewport.deformation_scale.value() == 8
