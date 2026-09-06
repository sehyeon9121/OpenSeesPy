"""Result-specific 3D settings drive both geometry and reported values."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    AnalysisResult,
    AnalysisStatus,
    BoundaryCondition,
    Element,
    ElementResult,
    ModeShape,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.display_3d import DisplayOptions, active_result, build_display
from openframe.features.results.presentation.result_display_settings import (
    ResultDisplaySettings,
)
from openframe.features.results.presentation.results_workspace import ResultsWorkspace


def _case() -> tuple[StructuralModel, AnalysisResult]:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
        boundaries=[BoundaryCondition(1, (True, True, True, True, True, True))],
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(1, displacement=(0, 0, 0, 0, 0, 0), reaction=(4, -5, 6, 7, 8, 9)),
            2: NodeResult(2, displacement=(1, 2, 3, 0, 0, 0)),
        },
        element_results={
            1: ElementResult(1, local_forces=(10, 20, 30, 0, 40, 50, -10, -20, -30, 0, -40, -50))
        },
    )
    return model, result


def test_displacement_component_projects_shape_and_value() -> None:
    model, result = _case()
    options = DisplayOptions(component="DY", scale_mode="real", values=True)

    data = build_display(model, result, "displacement", options, DEFAULT_UNIT_SYSTEM)

    assert data.result.node_results[2].displacement[:3] == (0.0, 2, 0.0)
    assert data.values["Node 2"] == 2
    assert data.scale == 1.0
    assert data.labels


def test_reaction_component_controls_arrows_and_signed_values() -> None:
    model, result = _case()
    options = DisplayOptions(component="FZ", arrows=True)

    data = build_display(model, result, "reaction", options, DEFAULT_UNIT_SYSTEM)

    assert data.values == {"Node 1": 6}
    assert data.reactions == {1: (0.0, 0.0, 6, 0.0, 0.0, 0.0)}


def test_member_force_component_filters_3d_diagram_plane() -> None:
    model, result = _case()

    data = build_display(
        model, result, "shear", DisplayOptions(component="Vz"), DEFAULT_UNIT_SYSTEM
    )

    assert data.diagrams
    assert all("shear_z" in key for key in data.values)


def test_sidebar_keeps_independent_options_for_each_result() -> None:
    QApplication.instance() or QApplication([])
    panel = ResultDisplaySettings()
    panel.set_model(_case()[0])
    panel.set_result_type("deformation")
    panel.scale_mode.setCurrentIndex(panel.scale_mode.findData("user"))
    panel.scale_value.setValue(75)

    panel.set_result_type("moment")
    panel.diagram_scale.setValue(90)
    panel.set_result_type("deformation")

    assert panel.current_options().scale == 75
    panel.set_result_type("moment")
    assert panel.current_options().diagram_scale == 90


def test_empty_3d_workspace_already_uses_contextual_result_layout() -> None:
    """The result layout must be visible before a model or result is loaded."""
    QApplication.instance() or QApplication([])
    workspace = ResultsWorkspace()
    workspace.set_result_type("moment")

    settings = workspace.result_types.display_settings
    assert not settings.isHidden()
    assert workspace.result_types.minimumWidth() == 264
    assert not settings.force_kind_row.isHidden()
    assert settings.component_selector.currentText() == "My + Mz"
    assert workspace.result_types.current_display_options() is not None
    assert workspace.viewport.controls_stack.isHidden()
    assert workspace.viewport.force_selector.isHidden()
    assert not workspace.summary.active_result_title.isHidden()
    assert not workspace.summary.active_value_table.isHidden()


def test_workspace_force_selector_changes_canvas_and_right_values() -> None:
    application = QApplication.instance() or QApplication([])
    model, result = _case()
    workspace = ResultsWorkspace()
    workspace.set_model(model)
    workspace.show_result(result)
    workspace.set_result_type("moment")

    settings = workspace.result_types.display_settings
    settings.force_kind_selector.setCurrentIndex(settings.force_kind_selector.findData("shear"))
    application.processEvents()

    assert workspace.viewport._result_type == "shear"
    assert settings.component_selector.currentText() == "Vy + Vz"
    assert workspace.summary.active_value_table.rowCount() > 0
    assert workspace.viewport.quick3d_view.bridge.forceDiagrams


def test_modal_mode_and_component_are_selected_from_left_panel() -> None:
    model, static_result = _case()
    mode_result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        mode_shapes=(
            ModeShape(
                1,
                eigenvalue=4.0,
                angular_frequency=2.0,
                frequency_hz=0.3183,
                period=3.1416,
                node_results=static_result.node_results,
            ),
        ),
    )
    panel = ResultDisplaySettings()
    panel.set_model(model)
    panel.show_result(mode_result)
    panel.set_result_type("mode_shapes")
    panel.component_selector.setCurrentText("DZ")

    active, context = active_result(mode_result, "mode_shapes", panel.current_options().mode_index)

    assert panel.mode_selector.count() == 1
    assert panel.current_options().component == "DZ"
    assert active.node_results[2].displacement[2] == 3
    assert "0.3183 Hz" in context
