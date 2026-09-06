"""Instability Mechanism counterpart of test_result_viewport_buckling_modes.py.

Mechanism Modes shares the same mode_shape_selector widget/rendering path as
Mode Shapes and Buckling Modes (see result_viewport.py's
_MODE_SELECTOR_RESULT_TYPES) - the tests here focus on what's specific to
that reuse: MechanismMode.mode_shape is dict[int, tuple[float, ...]] (not
dict[int, NodeResult] like the other two), so it needs the
_mechanism_node_results adapter; the combo shows residuals instead of
periods/factors; and the dominant_dofs readout label is unique to this
result type.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    BucklingMode,
    Element,
    InstabilityDiagnosticResult,
    MechanismMode,
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


def _diagnostic() -> InstabilityDiagnosticResult:
    return InstabilityDiagnosticResult(
        mechanism_count=2,
        modes=(
            MechanismMode(
                mode_number=1,
                eigenvalue=1e-15,
                mode_shape={1: (0.0, 0.0, 0.0), 2: (1.0, 0.0, 0.0)},
                dominant_dofs=("n2:Ux=+1.00",),
                residual=1.2e-14,
            ),
            MechanismMode(
                mode_number=2,
                eigenvalue=2e-15,
                mode_shape={1: (0.0, 0.0, 0.0), 2: (0.0, 1.0, 0.0)},
                dominant_dofs=("n2:Uy=+1.00",),
                residual=3.4e-14,
            ),
        ),
        message="구조가 불안정합니다 - 강성행렬에서 메커니즘 2개가 감지되었습니다.",
        matrix_size=6,
        diagnostic_success=True,
    )


def _mechanism_result() -> AnalysisResult:
    return AnalysisResult(status=AnalysisStatus.FAILED, instability_diagnostic=_diagnostic())


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


def test_mode_selector_hidden_until_mechanism_modes_is_selected() -> None:
    viewport = _viewport()
    assert viewport.mode_shape_selector.isHidden()

    viewport.set_result_type("mechanism_modes")
    assert not viewport.mode_shape_selector.isHidden()
    assert not viewport.mode_shape_label.isHidden()

    viewport.set_result_type("moment")
    assert viewport.mode_shape_selector.isHidden()


def test_showing_a_mechanism_result_populates_the_selector_with_residuals() -> None:
    viewport = _viewport()
    viewport.show_result(_mechanism_result())
    viewport.set_result_type("mechanism_modes")

    assert viewport.mode_shape_selector.count() == 2
    assert "Mechanism 1" in viewport.mode_shape_selector.itemText(0)
    assert "residual=" in viewport.mode_shape_selector.itemText(0)
    assert "Mechanism 2" in viewport.mode_shape_selector.itemText(1)


def test_selecting_a_mechanism_redraws_that_modes_shape() -> None:
    viewport = _viewport()
    viewport.show_result(_mechanism_result())
    viewport.set_result_type("mechanism_modes")

    mode1_vector = _displacement_vector_item(viewport, 2)
    assert mode1_vector is not None
    mode1_end = mode1_vector.line().p2()

    viewport.mode_shape_selector.setCurrentIndex(1)

    mode2_vector = _displacement_vector_item(viewport, 2)
    assert mode2_vector is not None
    mode2_end = mode2_vector.line().p2()
    assert (mode1_end.x(), mode1_end.y()) != (mode2_end.x(), mode2_end.y())


def test_dominant_dofs_label_updates_with_selection() -> None:
    viewport = _viewport()
    viewport.show_result(_mechanism_result())
    viewport.set_result_type("mechanism_modes")

    assert viewport.mechanism_dofs_label.text() == "n2:Ux=+1.00"

    viewport.mode_shape_selector.setCurrentIndex(1)
    assert viewport.mechanism_dofs_label.text() == "n2:Uy=+1.00"


def test_dominant_dofs_label_hidden_outside_mechanism_modes() -> None:
    viewport = _viewport()
    viewport.show_result(_mechanism_result())
    viewport.set_result_type("mechanism_modes")
    assert not viewport.mechanism_dofs_label.isHidden()

    viewport.set_result_type("moment")
    assert viewport.mechanism_dofs_label.isHidden()


def test_active_node_results_returns_adapted_node_result_dict() -> None:
    """MechanismMode.mode_shape is dict[int, tuple[float, ...]], not
    dict[int, NodeResult] - _active_node_results must adapt it, not pass it
    through raw."""
    viewport = _viewport()
    viewport.show_result(_mechanism_result())
    viewport.set_result_type("mechanism_modes")

    active = viewport._active_node_results()
    assert set(active.keys()) == {1, 2}
    assert isinstance(active[2], NodeResult)
    assert active[2].displacement == (1.0, 0.0, 0.0)


def test_switching_between_mode_families_refills_the_selector() -> None:
    """All three result types share one combo widget - switching between them
    on the same result must always show the list matching whichever is
    currently selected, never a stale one from a different mode family."""
    combined = AnalysisResult(
        status=AnalysisStatus.FAILED,
        mode_shapes=(
            ModeShape(
                mode_number=1,
                eigenvalue=4.0,
                angular_frequency=2.0,
                frequency_hz=0.318,
                period=3.1416,
            ),
        ),
        buckling_modes=(
            BucklingMode(
                mode_number=1,
                buckling_load_factor=12.45,
                raw_eigenvalue=12.45,
            ),
        ),
        instability_diagnostic=_diagnostic(),
    )
    viewport = _viewport()
    viewport.show_result(combined)

    viewport.set_result_type("mode_shapes")
    assert viewport.mode_shape_selector.count() == 1
    assert "T=" in viewport.mode_shape_selector.itemText(0)

    viewport.set_result_type("buckling_modes")
    assert viewport.mode_shape_selector.count() == 1
    assert "λ=" in viewport.mode_shape_selector.itemText(0)

    viewport.set_result_type("mechanism_modes")
    assert viewport.mode_shape_selector.count() == 2
    assert "residual=" in viewport.mode_shape_selector.itemText(0)

    viewport.set_result_type("mode_shapes")
    assert viewport.mode_shape_selector.count() == 1


def test_mechanism_modes_view_with_no_diagnostic_shows_the_bare_undeformed_model() -> None:
    viewport = _viewport()
    viewport.show_result(AnalysisResult(status=AnalysisStatus.FAILED))

    viewport.set_result_type("mechanism_modes")

    assert viewport.mode_shape_selector.count() == 0
    assert _displacement_vector_item(viewport, 2) is None
    assert viewport.mechanism_dofs_label.text() == "—"


def test_mechanism_modes_view_with_unsuccessful_diagnostic_shows_empty_selector() -> None:
    viewport = _viewport()
    failed_diagnostic = InstabilityDiagnosticResult(
        message="불안정 진단 자체가 실패했습니다: test", diagnostic_success=False
    )
    viewport.show_result(
        AnalysisResult(status=AnalysisStatus.FAILED, instability_diagnostic=failed_diagnostic)
    )

    viewport.set_result_type("mechanism_modes")

    assert viewport.mode_shape_selector.count() == 0
