"""Functional coverage for AnalysisSettingsPanel beyond layout: the CONTROL DOF combo
must only ever offer DOFs the loaded model actually has.

A truss-only model (ops.model('basic', '-ndm', 2, '-ndf', 2)) has 2 DOFs per node
(UX, UY) - no RZ. The combo used to always offer UX/UY/RZ for any 2D model, so
picking RZ on a model like this crashed the solver with a raw IndexError instead of
a validation message (see test_nonlinear_static_solver.py for the solver-side fix)."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QScrollArea

from openframe.core.domain import AnalysisKind, Node, StructuralModel
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)
from openframe.features.analysis.presentation.analysis_settings_panel import (
    AnalysisSettingsPanel,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

TRUSS_MODEL = Path(__file__).parents[2] / "examples" / "nonlinear_truss_pushover.py"
SPRING_MODEL = Path(__file__).parents[2] / "examples" / "nonlinear_spring_pushover_1d.py"


def _send_wheel(widget, delta: int = 120) -> None:
    point = QPointF(widget.rect().center())
    event = QWheelEvent(
        point,
        point,
        QPoint(),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_mouse_wheel_does_not_change_setup_combo_or_numeric_values() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()

    panel.analysis_type.setCurrentIndex(1)
    panel.num_modes.setValue(7)
    panel.algorithm.setCurrentIndex(1)
    panel.max_iterations.setValue(30)

    before = (
        panel.analysis_type.currentIndex(),
        panel.num_modes.value(),
        panel.algorithm.currentIndex(),
        panel.max_iterations.value(),
    )
    for widget in (
        panel.analysis_type,
        panel.num_modes,
        panel.algorithm,
        panel.max_iterations,
    ):
        _send_wheel(widget, 120)
        _send_wheel(widget, -120)

    assert (
        panel.analysis_type.currentIndex(),
        panel.num_modes.value(),
        panel.algorithm.currentIndex(),
        panel.max_iterations.value(),
    ) == before
    application.processEvents()


def test_mouse_wheel_over_main_setup_input_scrolls_the_page() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.resize(640, 280)
    panel.show()
    application.processEvents()

    scroll = panel.findChild(QScrollArea, "setupSettingsScroll")
    bar = scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum() // 2)
    before = bar.value()

    _send_wheel(panel.analysis_type, 120)

    assert bar.value() < before
    panel.close()


def test_control_dof_options_are_limited_to_the_model_ndf() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    assert model.ndf == 2

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    labels = [panel.control_dof.itemText(index) for index in range(panel.control_dof.count())]
    assert labels == ["UX", "UY"]
    application.processEvents()


def test_control_dof_options_still_cover_full_ndf_for_a_frame_style_model() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(SPRING_MODEL)

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    assert panel.control_dof.count() == model.ndf
    application.processEvents()


def test_control_node_defaults_to_the_loaded_node_not_the_first_by_tag() -> None:
    """Node 1 (the combo's natural first entry, sorted by tag) is a support in this
    model - the old plain "leave it at index 0" default silently produced a pushover
    curve that was a flat vertical line at zero displacement forever. The default
    must land on node 4, where the load (and all the movement) actually is."""
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    assert panel.control_node.currentData() == 4
    application.processEvents()


def test_control_node_default_is_the_free_node_for_the_spring_model_too() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(SPRING_MODEL)

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    assert panel.control_node.currentData() == 2
    application.processEvents()


def test_gravity_pattern_combo_lists_patterns_found_in_the_model() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)

    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    labels = [
        panel.gravity_pattern.itemText(index) for index in range(panel.gravity_pattern.count())
    ]
    assert labels == ["NONE", "Pattern 1"]
    assert panel.gravity_pattern.currentData() is None
    application.processEvents()


def test_lateral_pattern_combo_lists_patterns_and_builds_explicit_selection() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)

    labels = [
        panel.lateral_pattern.itemText(index)
        for index in range(panel.lateral_pattern.count())
    ]
    assert labels == ["ALL NON-GRAVITY PATTERNS", "Pattern 1"]
    panel.lateral_pattern.setCurrentIndex(panel.lateral_pattern.findData(1))
    assert panel.build_options()["lateral_pattern"] == 1
    application.processEvents()


def test_gravity_steps_hidden_until_a_gravity_pattern_is_chosen() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    assert panel.gravity_steps_group.isVisible() is False
    panel.gravity_pattern.setCurrentIndex(panel.gravity_pattern.findData(1))
    assert panel.gravity_steps_group.isVisible() is True
    panel.close()


def test_target_displacement_hidden_until_displacement_control_is_chosen() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    assert panel.target_displacement_group.isVisible() is False
    assert panel.control_node_group.isVisible() is False
    assert panel.control_dof_group.isVisible() is False
    panel.integrator_type.setCurrentIndex(
        panel.integrator_type.findData("DisplacementControl")
    )
    assert panel.target_displacement_group.isVisible() is True
    assert panel.control_node_group.isVisible() is True
    assert panel.control_dof_group.isVisible() is True
    panel.close()


def test_build_options_omits_gravity_and_target_displacement_by_default() -> None:
    panel = AnalysisSettingsPanel()

    options = panel.build_options()

    assert options["integrator_type"] == "LoadControl"
    assert "gravity_pattern" not in options
    assert "gravity_steps" not in options
    assert "target_displacement" not in options
    assert "lateral_pattern" not in options
    assert options["max_bisections"] == 4
    assert options["execution_timeout_seconds"] == 600
    assert options["constraints_type"] == "Plain"
    assert options["numberer"] == "RCM"


def test_build_options_includes_gravity_and_target_displacement_when_selected() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.gravity_pattern.setCurrentIndex(panel.gravity_pattern.findData(1))
    panel.gravity_steps.setValue(7)
    panel.integrator_type.setCurrentIndex(
        panel.integrator_type.findData("DisplacementControl")
    )
    panel.target_displacement.setValue(0.5)

    options = panel.build_options()

    assert options["gravity_pattern"] == 1
    assert options["gravity_steps"] == 7
    assert options["integrator_type"] == "DisplacementControl"
    assert options["target_displacement"] == 0.5
    application.processEvents()


def test_build_options_includes_the_new_nonlinear_control_fields_by_default() -> None:
    panel = AnalysisSettingsPanel()

    options = panel.build_options()

    assert options["geometric_transform_type"] == "Linear"
    assert options["target_load_factor"] == 1.0
    assert options["automatic_recovery"] is True
    assert options["adaptive_step"] is False
    # 0 (the spin boxes' "Auto" sentinel) means "let the solver derive it" -
    # sending an explicit 0 would instead be validated as an error there.
    assert "min_increment" not in options
    assert "max_increment" not in options


def test_build_options_includes_min_and_max_increment_once_set() -> None:
    panel = AnalysisSettingsPanel()
    panel.min_increment.setValue(0.001)
    panel.max_increment.setValue(0.5)

    options = panel.build_options()

    assert options["min_increment"] == 0.001
    assert options["max_increment"] == 0.5


def test_geometric_transformation_selection_updates_the_behavior_tile_and_notice() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    assert panel.geometric_nonlinearity_value.text() == "○  Linear (disabled)"
    assert panel.geometric_nonlinearity_value.property("state") == "off"

    panel.geometric_transformation.setCurrentIndex(
        panel.geometric_transformation.findData("PDelta")
    )

    assert panel.geometric_nonlinearity_value.text() == "✓  P-Delta ENABLED"
    assert panel.geometric_nonlinearity_value.property("state") == "ok"
    assert "P-Delta" in panel.geometric_nonlinearity_notice.text()
    assert panel.build_options()["geometric_transform_type"] == "PDelta"
    panel.close()


def test_reset_to_default_restores_a_customized_solution_strategy() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    assert panel.solution_strategy_status.text() == "DEFAULT"
    panel.algorithm.setCurrentText("KrylovNewton")
    panel.tolerance.setValue(1.0e-4)
    assert panel.solution_strategy_status.text() == "CUSTOM"

    panel.reset_solution_strategy_button.click()

    assert panel.solution_strategy_status.text() == "DEFAULT"
    assert panel.algorithm.currentText() == "Newton"
    assert panel.tolerance.value() == pytest.approx(1.0e-6)
    panel.close()


def test_automatic_recovery_off_disables_adaptive_and_increment_fields() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    assert panel.adaptive_step.isEnabled() is True
    panel.adaptive_step.setChecked(True)

    panel.automatic_recovery.setChecked(False)

    assert panel.adaptive_step.isEnabled() is False
    assert panel.adaptive_step.isChecked() is False
    assert panel.min_increment_group.isEnabled() is False
    assert panel.max_increment_group.isEnabled() is False
    assert panel.build_options()["automatic_recovery"] is False
    panel.close()


def test_arc_length_fields_hidden_until_arc_length_control_is_chosen() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    assert panel.control_node_group.isVisible() is False
    assert panel.control_dof_group.isVisible() is False
    assert panel.num_steps_group.isVisible() is True
    for group in panel.arc_length_field_groups:
        assert group.isVisible() is False

    panel.integrator_type.setCurrentIndex(panel.integrator_type.findData("ArcLength"))

    assert panel.control_node_group.isVisible() is True
    assert panel.control_dof_group.isVisible() is True
    assert panel.target_load_factor_group.isVisible() is False
    assert panel.load_increment_group.isVisible() is False
    assert panel.target_displacement_group.isVisible() is False
    assert panel.num_steps_group.isVisible() is False
    for group in panel.arc_length_field_groups:
        assert group.isVisible() is True
    panel.close()


def test_build_options_includes_arc_length_fields_when_selected() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.integrator_type.setCurrentIndex(panel.integrator_type.findData("ArcLength"))
    panel.arc_length_radius.setValue(0.02)
    panel.arc_length_alpha.setValue(2.0)
    panel.arc_length_max_steps.setValue(150)
    panel.arc_length_min_radius.setValue(0.0002)
    panel.arc_length_max_radius.setValue(0.02)
    panel.arc_length_adaptive.setChecked(True)

    options = panel.build_options()

    assert options["integrator_type"] == "ArcLength"
    assert options["arc_length_radius"] == 0.02
    assert options["arc_length_alpha"] == 2.0
    assert options["arc_length_max_steps"] == 150
    assert options["arc_length_min_radius"] == 0.0002
    assert options["arc_length_max_radius"] == 0.02
    assert options["arc_length_adaptive"] is True
    # Optional fields left at their sentinel/default: not sent, matching the
    # MIN/MAX INCREMENT "0 = Auto, don't send" convention above.
    assert "arc_length_control_node" not in options
    assert "arc_length_control_dof" not in options
    assert "arc_length_max_displacement" not in options
    # LoadControl/DisplacementControl-only fields must not leak through either.
    assert "target_displacement" not in options
    application.processEvents()


def test_build_options_includes_optional_arc_length_target_and_limit_once_set() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.integrator_type.setCurrentIndex(panel.integrator_type.findData("ArcLength"))
    panel.arc_length_control_node.setCurrentIndex(panel.arc_length_control_node.findData(4))
    panel.arc_length_control_dof.setCurrentIndex(panel.arc_length_control_dof.findData(1))
    panel.arc_length_max_displacement.setValue(5.0)

    options = panel.build_options()

    assert options["arc_length_control_node"] == 4
    assert options["arc_length_control_dof"] == 1
    assert options["arc_length_max_displacement"] == 5.0
    application.processEvents()


def test_automatic_recovery_off_disables_arc_length_adaptive_fields_too() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    assert panel.arc_length_adaptive.isEnabled() is True
    panel.arc_length_adaptive.setChecked(True)

    panel.automatic_recovery.setChecked(False)

    assert panel.arc_length_adaptive.isEnabled() is False
    assert panel.arc_length_adaptive.isChecked() is False
    assert panel.arc_length_min_radius_group.isEnabled() is False
    assert panel.arc_length_max_radius_group.isEnabled() is False
    panel.close()


def test_precheck_flags_arc_length_radius_out_of_order() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.integrator_type.setCurrentIndex(panel.integrator_type.findData("ArcLength"))
    panel.show()
    application.processEvents()

    assert panel.precheck_status.property("state") == "ok"

    panel.arc_length_min_radius.setValue(1.0)
    panel.arc_length_max_radius.setValue(0.5)
    panel._update_precheck()

    assert panel.precheck_status.property("state") == "warning"
    assert "MINIMUM RADIUS" in panel.precheck_status.text()
    assert panel.arc_length_precheck_note.isVisible() is True
    panel.close()


def test_buckling_group_visible_only_when_buckling_is_selected() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.show()
    application.processEvents()

    assert panel.buckling_group.isVisible() is False
    assert panel.buckling_precheck_card.isVisible() is False

    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.BUCKLING))

    assert panel.buckling_group.isVisible() is True
    assert panel.buckling_precheck_card.isVisible() is True
    assert panel.nonlinear_group.isVisible() is False
    assert panel.modal_group.isVisible() is False
    assert panel.time_history_group.isVisible() is False
    panel.close()


def test_buckling_geometric_transform_is_restricted_to_p_delta_only() -> None:
    """Officially restricted to P-Delta for now - Corotational/"From Model"
    are not offered until separately validated for buckling (closing check
    after the feature's initial implementation)."""
    panel = AnalysisSettingsPanel()

    values = {
        panel.buckling_geometric_transform.itemData(index)
        for index in range(panel.buckling_geometric_transform.count())
    }

    assert values == {"PDelta"}
    assert panel.buckling_geometric_transform.currentData() == "PDelta"
    assert panel.buckling_geometric_transform.isEnabled() is False


def test_build_options_returns_buckling_shape_when_buckling_selected() -> None:
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.BUCKLING))

    options = panel.build_options()

    assert options["reference_load_scale"] == 1.0
    assert options["num_modes"] == 5
    assert options["geometric_transform_type"] == "PDelta"
    assert "reference_load_pattern" not in options
    assert "eigenvalue_tolerance" not in options
    # LoadControl/DisplacementControl/ArcLength-only keys must not leak through.
    assert "integrator_type" not in options
    assert "control_node" not in options


def test_build_options_includes_explicit_load_case_and_tolerance_once_set() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.BUCKLING))
    panel.buckling_load_case.setCurrentIndex(panel.buckling_load_case.findData(1))
    panel.buckling_reference_load_scale.setValue(2.5)
    panel.buckling_num_modes.setValue(10)
    panel.buckling_eigenvalue_tolerance.setValue(0.001)

    options = panel.build_options()

    assert options["reference_load_pattern"] == 1
    assert options["reference_load_scale"] == 2.5
    assert options["num_modes"] == 10
    assert options["eigenvalue_tolerance"] == 0.001
    application.processEvents()


def test_buckling_precheck_flags_a_model_with_no_load_pattern() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.BUCKLING))
    panel.show()
    application.processEvents()

    assert panel.buckling_precheck_status.property("state") == "warning"
    assert "모델이 비어" in panel.buckling_precheck_status.text()
    panel.close()


def test_buckling_precheck_clears_once_a_model_with_a_load_pattern_is_set() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.BUCKLING))
    panel.set_model(model)
    panel.show()
    application.processEvents()

    assert panel.buckling_precheck_status.property("state") == "ok"
    panel.close()


def test_buckling_precheck_shows_no_large_model_warning_for_a_small_model() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.BUCKLING))
    panel.set_model(model)
    panel.show()
    application.processEvents()

    assert panel.buckling_large_model_note.isVisible() is False
    panel.close()


def test_buckling_precheck_warns_on_a_large_model_without_blocking_the_run() -> None:
    """Closing check: Dense FullGeneral + SciPy's O(n**3) eigensolve deserve a
    warning on a large model - non-blocking, since a large model still runs,
    just slowly (see buckling_solver.py's own threshold)."""
    application = QApplication.instance() or QApplication([])
    # ndf=3 x 200 nodes = 600 estimated DOFs, comfortably over the 500 threshold.
    model = StructuralModel(
        ndm=2, nodes={tag: Node(tag, float(tag), 0.0) for tag in range(1, 201)}
    )
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.BUCKLING))
    panel.set_model(model)
    panel.show()
    application.processEvents()

    assert panel.buckling_large_model_note.isVisible() is True
    assert "600" in panel.buckling_large_model_note.text()
    # Informational only - must not, by itself, block RUN.
    assert "Model Size" not in panel.buckling_precheck_status.text()
    panel.close()


def test_precheck_flags_a_missing_control_node_then_clears_once_one_is_picked() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    panel.control_node.setCurrentIndex(-1)
    panel._update_precheck()
    assert "CONTROL NODE" in panel.precheck_status.text()
    assert panel.precheck_status.property("state") == "warning"

    panel.control_node.setCurrentIndex(0)

    assert panel.precheck_status.text() == "✓  Ready for Analysis"
    assert panel.precheck_status.property("state") == "ok"
    panel.close()


def test_precheck_reports_material_nonlinearity_not_active_for_an_elastic_model() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(TRUSS_MODEL)
    panel = AnalysisSettingsPanel()
    panel.set_model(model)
    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )
    panel.show()
    application.processEvents()

    assert panel.precheck_value_labels["Material Nonlinearity"].text() == "Not Active"
    panel.close()


def test_panel_without_an_explicit_store_still_defaults_to_linear_static() -> None:
    panel = AnalysisSettingsPanel()

    assert panel.config_store.kind == AnalysisKind.LINEAR_STATIC
    assert panel.selected_analysis_kind() == AnalysisKind.LINEAR_STATIC


def test_changing_the_combo_pushes_the_new_kind_into_the_shared_store() -> None:
    store = AnalysisConfigStore()
    panel = AnalysisSettingsPanel(store=store)

    panel.analysis_type.setCurrentIndex(
        panel.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )

    assert store.kind == AnalysisKind.NONLINEAR_STATIC


def test_changing_the_store_from_outside_updates_the_combo() -> None:
    store = AnalysisConfigStore()
    panel = AnalysisSettingsPanel(store=store)

    store.set_kind(AnalysisKind.TIME_HISTORY)

    assert panel.analysis_type.currentData() == AnalysisKind.TIME_HISTORY


def test_two_panels_sharing_a_store_stay_in_sync() -> None:
    store = AnalysisConfigStore()
    first = AnalysisSettingsPanel(store=store)
    second = AnalysisSettingsPanel(store=store)

    first.analysis_type.setCurrentIndex(
        first.analysis_type.findData(AnalysisKind.NONLINEAR_STATIC)
    )

    assert second.analysis_type.currentData() == AnalysisKind.NONLINEAR_STATIC


def test_solver_change_is_reflected_in_the_store_options() -> None:
    store = AnalysisConfigStore()
    panel = AnalysisSettingsPanel(store=store)

    panel.solver.setCurrentText("UmfPack")

    assert store.options["system"] == "UmfPack"


def test_selecting_modal_shows_its_own_settings_and_hides_nonlinear() -> None:
    # isVisible() is always False for a widget that was never shown - offscreen or
    # not - regardless of its own visibility flag, so the panel must be shown first
    # to tell "hidden because never shown" apart from "hidden because not selected".
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.show()

    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.MODAL))

    assert panel.modal_group.isVisible()
    assert not panel.nonlinear_group.isVisible()
    application.processEvents()


def test_modal_build_options_defaults_to_fixed_mode_count() -> None:
    """The modal solver's own kwargs (run_modal_analysis) never overlap with the
    nonlinear-shaped dict (system/num_steps/tolerance/...) - handing it that shape
    would raise a TypeError on the unexpected keyword arguments, so this must stay a
    clean, separate shape rather than the nonlinear dict with modal fields merged in."""
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.MODAL))
    panel.num_modes.setValue(6)

    assert panel.build_options() == {"extraction_method": "fixed", "num_modes": 6}
    application.processEvents()


def test_modal_build_options_for_target_participation() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.MODAL))
    panel.modal_extraction_method.setCurrentIndex(
        panel.modal_extraction_method.findData("target")
    )
    panel.modal_target_participation.setValue(95.0)
    panel.modal_max_modes.setValue(30)
    for direction, checkbox in panel.modal_target_direction_checks.items():
        checkbox.setChecked(direction in ("X", "Y", "Z"))

    assert panel.build_options() == {
        "extraction_method": "target",
        "target_participation": 95.0,
        "target_directions": "X,Y,Z",
        "max_modes": 30,
    }
    application.processEvents()


def test_modal_extraction_method_toggles_fixed_and_target_field_groups() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.show()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.MODAL))

    assert panel.modal_fixed_group.isVisible()
    assert not panel.modal_target_group.isVisible()

    panel.modal_extraction_method.setCurrentIndex(
        panel.modal_extraction_method.findData("target")
    )

    assert panel.modal_target_group.isVisible()
    assert not panel.modal_fixed_group.isVisible()
    application.processEvents()


def test_selecting_time_history_shows_its_own_settings_and_hides_the_others() -> None:
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.show()

    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))

    assert panel.time_history_group.isVisible()
    assert not panel.modal_group.isVisible()
    assert not panel.nonlinear_group.isVisible()
    application.processEvents()


def _time_history_panel() -> AnalysisSettingsPanel:
    panel = AnalysisSettingsPanel()
    panel.show()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))
    return panel


def _stub_file_dialog(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(path), ""))
    )


def _stub_builtin_picker(monkeypatch: pytest.MonkeyPatch, record) -> None:
    """Stand in for GroundMotionPickerDialog's modal exec()/selected_record()
    - patched on the class itself, so it applies regardless of which module
    (time_history_direction_row.py) actually instantiates it."""
    from openframe.features.analysis.presentation.ground_motion_picker_dialog import (
        GroundMotionPickerDialog,
    )

    monkeypatch.setattr(GroundMotionPickerDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(GroundMotionPickerDialog, "selected_record", lambda self: record)


class TestDirectionTable:
    """Item 3/4's multi-direction Ground Motion table: one row per
    translational DOF (X/Y for 2D, X/Y/Z for 3D - rotational excitation is
    out of scope), so two rows can never activate the same direction by
    construction."""

    def test_two_dimensional_model_gets_exactly_x_and_y_rows(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        model = StructuralModel(ndm=2, ndf=3)

        panel.set_model(model)

        assert [row.dof for row in panel.time_history_direction_rows] == [1, 2]
        application.processEvents()

    def test_three_dimensional_model_gets_x_y_and_z_rows(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        model = StructuralModel(ndm=3, ndf=6)

        panel.set_model(model)

        assert [row.dof for row in panel.time_history_direction_rows] == [1, 2, 3]
        application.processEvents()

    def test_no_two_rows_can_ever_share_a_direction(self) -> None:
        """Each row's DOF is fixed at construction (see
        time_history_direction_row.py) - a structural guarantee, not a
        runtime check, that duplicate activation is impossible."""
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        panel.set_model(StructuralModel(ndm=3, ndf=6))

        dofs = [row.dof for row in panel.time_history_direction_rows]
        assert len(dofs) == len(set(dofs))
        application.processEvents()

    def test_build_options_directions_is_empty_with_no_model_loaded(self) -> None:
        """A panel used before any model is loaded must not crash
        build_options() - directions simply come back empty."""
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()

        options = panel.build_options()

        assert options["directions"] == []
        assert options["analysis_time"]["duration_mode"] == "full"
        assert "damping" in options
        assert "integrator" in options
        assert "solution" in options
        assert "recovery" in options
        application.processEvents()


class TestGroundMotionRowFileImport:
    """Picking a file loads it through GroundMotion immediately (not just at
    RUN time inside the worker subprocess), so a bad file is caught and the
    metadata (dt/NPTS/Duration/Original PGA) is shown right away."""

    def test_picking_a_valid_file_shows_its_metadata_and_is_included_once_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        motion_path = tmp_path / "motion.AT2"
        motion_path.write_text(
            "PACIFIC EARTHQUAKE ENGINEERING RESEARCH CENTER\n"
            "SOME STATION, SOME EVENT\n"
            "ACCELERATION TIME SERIES IN UNITS OF G\n"
            "NPTS=   4, DT=  0.0200 SEC\n"
            " 0.1000  -0.5000  0.3000  0.2000\n",
            encoding="utf-8",
        )
        _stub_file_dialog(monkeypatch, motion_path)
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]

        row._choose_record_or_file()

        assert row.active_motion() is not None
        assert row.active_motion().pga == pytest.approx(0.5)
        assert row.record_label.text() == "motion.AT2"
        assert row.readout_values["Record dt"].text() == "0.02 s"
        assert row.readout_values["NPTS"].text() == "4"

        # Not active until the row is actually enabled.
        assert panel.build_options()["directions"] == []
        row.enabled_checkbox.setChecked(True)
        directions = panel.build_options()["directions"]
        assert len(directions) == 1
        assert directions[0]["path"] == str(motion_path)
        assert directions[0]["dof"] == row.dof
        application.processEvents()

    def test_picking_a_malformed_file_reports_an_error_and_clears_selection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        bad_path = tmp_path / "not_a_motion.txt"
        bad_path.write_text("this file has no numbers in it at all\n", encoding="utf-8")
        _stub_file_dialog(monkeypatch, bad_path)
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        row.enabled_checkbox.setChecked(True)

        row._choose_record_or_file()

        assert row.active_motion() is None
        assert panel.build_options()["directions"] == []
        application.processEvents()

    def test_a_malformed_file_does_not_clobber_a_previously_valid_selection_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        good_path = tmp_path / "good.txt"
        good_path.write_text("NPTS=2, DT=0.01 SEC\n1.0 -2.0\n", encoding="utf-8")
        bad_path = tmp_path / "bad.txt"
        bad_path.write_text("no numbers here\n", encoding="utf-8")
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        row.enabled_checkbox.setChecked(True)

        _stub_file_dialog(monkeypatch, good_path)
        row._choose_record_or_file()
        assert len(panel.build_options()["directions"]) == 1

        _stub_file_dialog(monkeypatch, bad_path)
        row._choose_record_or_file()

        assert panel.build_options()["directions"] == []
        application.processEvents()


class TestBuiltInGroundMotionLibrary:
    """Built-in Library / Imported File as two selectable sources per row,
    sharing one readout grid - build_options() never cares which source was
    used, only what each row's active_motion()/active_path() resolve to."""

    def test_built_in_library_has_the_bundled_records_including_kobe(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]

        records = row._catalog.list_records()

        assert len(records) == 65
        assert any("Kobe" in f"{record.event} {record.station}" for record in records)
        application.processEvents()

    def test_selecting_built_in_populates_the_readouts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        record = row._catalog.list_records()[0]
        _stub_builtin_picker(monkeypatch, record)
        row.builtin_radio.setChecked(True)

        row._choose_record_or_file()

        motion = row.active_motion()
        assert motion is not None
        assert row.readout_values["NPTS"].text() == str(motion.npts)
        row.enabled_checkbox.setChecked(True)
        assert panel.build_options()["directions"][0]["path"] == str(record.path)
        application.processEvents()

    def test_scale_factor_change_updates_the_effective_scale_readout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        record = row._catalog.list_records()[0]
        _stub_builtin_picker(monkeypatch, record)
        row.builtin_radio.setChecked(True)
        row._choose_record_or_file()

        row.scale_factor_spin.setValue(2.0)

        assert row.readout_values["Effective Scale"].text() == "2"
        application.processEvents()

    def test_selecting_a_record_populates_the_acceleration_time_preview(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each direction row keeps its own ACCELERATION-TIME PREVIEW chart
        (unit-converted + scaled, matching what the solver actually applies) -
        not merely the numeric readouts."""
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        record = row._catalog.list_records()[0]
        _stub_builtin_picker(monkeypatch, record)
        row.builtin_radio.setChecked(True)
        row.unit_combo.setCurrentIndex(row.unit_combo.findData("model"))
        row._choose_record_or_file()

        motion = row.active_motion()
        assert motion is not None
        assert len(row.preview._values) == motion.npts
        assert row.preview._values == pytest.approx(motion.accelerations)

        row.scale_factor_spin.setValue(2.0)
        assert row.preview._values == pytest.approx(tuple(v * 2.0 for v in motion.accelerations))
        application.processEvents()

    def test_target_pga_mode_derives_the_correct_effective_scale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        record = row._catalog.list_records()[0]
        _stub_builtin_picker(monkeypatch, record)
        row.builtin_radio.setChecked(True)
        row.unit_combo.setCurrentIndex(row.unit_combo.findData("model"))
        row._choose_record_or_file()
        motion = row.active_motion()
        assert motion is not None

        row.target_pga_radio.setChecked(True)
        row.target_pga_spin.setValue(motion.pga * 1.5)

        scaling = row.scaling_summary()
        assert scaling is not None
        assert scaling.effective_scale == pytest.approx(1.5, rel=1e-6)
        row.enabled_checkbox.setChecked(True)
        directions = panel.build_options()["directions"]
        assert directions[0]["scaling_method"] == "target_pga"
        application.processEvents()

    def test_switching_source_leaves_no_stale_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        imported_path = tmp_path / "imported.txt"
        imported_path.write_text("NPTS=3, DT=0.02 SEC\n0.1 0.2 -0.3\n", encoding="utf-8")
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        record = row._catalog.list_records()[0]
        _stub_builtin_picker(monkeypatch, record)

        row.builtin_radio.setChecked(True)
        row._choose_record_or_file()
        builtin_motion = row.active_motion()
        assert builtin_motion is not None

        _stub_file_dialog(monkeypatch, imported_path)
        row.imported_radio.setChecked(True)
        row._choose_record_or_file()
        assert row.active_motion() is not None
        assert row.active_path() == imported_path

        row.builtin_radio.setChecked(True)
        assert row.active_motion() is builtin_motion

        row.imported_radio.setChecked(True)
        assert row.active_path() == imported_path
        application.processEvents()

    def test_zero_pga_record_shows_a_dash_instead_of_crashing_target_pga(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        zero_path = tmp_path / "zero.txt"
        zero_path.write_text("NPTS=3, DT=0.01 SEC\n0 0 0\n", encoding="utf-8")
        _stub_file_dialog(monkeypatch, zero_path)
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        row.imported_radio.setChecked(True)
        row._choose_record_or_file()

        row.target_pga_radio.setChecked(True)
        row.target_pga_spin.setValue(1.0)

        assert row.readout_values["Effective Scale"].text() == "—"
        application.processEvents()


class TestTimeHistoryStatusBadgesAndPrecheck:
    """DEFAULT/CUSTOM/AUTO status + Reset to Default (item 2's Analysis Time,
    item 7's PRE-CHECK) - mirrors Nonlinear Static's own
    _SOLUTION_STRATEGY_DEFAULTS/_update_precheck pattern."""

    def test_solution_strategy_starts_default_and_flags_custom_on_change(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()

        assert panel.th_solution_strategy_status.text() == "DEFAULT"

        panel.th_algorithm.setCurrentText("ModifiedNewton")

        assert panel.th_solution_strategy_status.text() == "CUSTOM"
        application.processEvents()

    def test_reset_to_default_restores_the_solution_strategy(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        panel.th_algorithm.setCurrentText("KrylovNewton")
        panel.th_tolerance.setValue(1.0e-4)
        assert panel.th_solution_strategy_status.text() == "CUSTOM"

        panel.th_reset_solution_strategy_button.click()

        assert panel.th_algorithm.currentText() == "Newton"
        assert panel.th_tolerance.value() == pytest.approx(1.0e-8)
        assert panel.th_solution_strategy_status.text() == "DEFAULT"
        application.processEvents()

    def test_analysis_time_starts_auto_and_flags_custom_on_a_manual_dt(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()

        assert panel.analysis_time_status.text() == "AUTO"

        panel.analysis_time_step.setValue(0.005)

        assert panel.analysis_time_status.text() == "CUSTOM"

        panel.reset_analysis_time_button.click()

        assert panel.analysis_time_status.text() == "AUTO"
        assert panel.analysis_time_step.value() == 0.0
        application.processEvents()

    def test_precheck_blocks_with_no_active_direction_and_clears_once_one_is_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()

        assert panel.th_precheck_status.property("state") == "warning"

        row = panel.time_history_direction_rows[0]
        record = row._catalog.list_records()[0]
        _stub_builtin_picker(monkeypatch, record)
        row.builtin_radio.setChecked(True)
        row._choose_record_or_file()
        row.enabled_checkbox.setChecked(True)

        assert panel.th_precheck_status.property("state") == "ok"
        assert "Ready for Analysis" in panel.th_precheck_status.text()
        application.processEvents()

    def test_precheck_warns_when_damping_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        row = panel.time_history_direction_rows[0]
        record = row._catalog.list_records()[0]
        _stub_builtin_picker(monkeypatch, record)
        row.builtin_radio.setChecked(True)
        row._choose_record_or_file()
        row.enabled_checkbox.setChecked(True)

        panel.damping_none_radio.setChecked(True)

        assert panel.th_precheck_status.property("state") == "warning"
        assert "감쇠" in panel.th_precheck_status.text()
        application.processEvents()

    def test_hht_selected_shows_its_own_fields_and_hides_newmarks(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()

        assert panel.newmark_group.isVisible()
        assert not panel.hht_group.isVisible()

        panel.integrator_hht_radio.setChecked(True)

        assert not panel.newmark_group.isVisible()
        assert panel.hht_group.isVisible()
        assert not panel.hht_custom_group.isVisible()

        panel.hht_custom_radio.setChecked(True)
        assert panel.hht_custom_group.isVisible()
        application.processEvents()

    def test_modal_targets_damping_is_the_default_and_direct_hides_it(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()

        assert panel.damping_modal_radio.isChecked()
        assert panel.damping_modal_group.isVisible()
        assert not panel.damping_direct_group.isVisible()

        panel.damping_direct_radio.setChecked(True)

        assert not panel.damping_modal_group.isVisible()
        assert panel.damping_direct_group.isVisible()
        application.processEvents()
