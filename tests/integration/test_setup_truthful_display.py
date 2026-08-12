"""Phase 3-A: SETUP's SOLUTION METHOD/CONVERGENCE readouts must match what
ANALYSIS_CAPABILITIES (and, transitively, the actual solver code it was
written to describe) says the current AnalysisKind's engine really does -
not always mirror whatever the nonlinear controls last held.

Also pins the fix for the Phase 2 Known Issue: the main SETUP page's
CONSTRAINT/NUMBERER labels used to be two independent QLabels hardcoded to
"Plain"/"RCM" and never wired to the real constraints_type/numberer combos at
all - changing them left the main page stuck showing
the wrong value forever. Test B below is the regression test for that.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.setup_workspace import (
    _FLOW_STEPS,
    _GUIDE_CALLOUT,
    _GUIDE_TEXT,
    _GUIDE_TOPIC,
    _KIND_LABELS,
    SetupWorkspace,
)
from openframe.core.domain import (
    ANALYSIS_CAPABILITIES,
    AnalysisKind,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
)
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)


def _make_setup() -> tuple[QApplication, SetupWorkspace]:
    application = QApplication.instance() or QApplication([])
    store = AnalysisConfigStore()
    setup = SetupWorkspace(store)
    # isVisible() reflects the whole ancestor chain, not just this widget's own
    # setVisible() calls - without an actual show(), everything reads as hidden
    # regardless of what _apply_solver_field/_apply_convergence_display did.
    setup.show()
    return application, setup


def test_linear_static_shows_engine_fixed_values_not_editable() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.LINEAR_STATIC)
    application.processEvents()

    # Phase 3-B: every value under here is ENGINE_FIXED for Linear Static, so
    # it starts collapsed behind an ADVANCED ENGINE DETAILS toggle instead of
    # dominating the default screen.
    assert settings.engine_details_toggle.isVisible()
    assert not settings.engine_details_toggle.isChecked()
    assert not settings.solution_body.isVisible()

    settings.engine_details_toggle.setChecked(True)
    application.processEvents()
    assert settings.solution_body.isVisible()

    assert not settings.solver.isVisible()
    assert settings.solver_fixed_value.isVisible()
    assert "BandGeneral" in settings.solver_fixed_value.text()
    assert "FIXED" in settings.solver_fixed_value.text()

    assert "Linear" in settings.solution_algorithm.text()
    assert "FIXED" in settings.solution_algorithm.text()
    assert "Transformation" in settings.constraint_value.text()
    assert "FIXED" in settings.constraint_value.text()
    assert "Plain" in settings.numberer_value.text()
    assert "FIXED" in settings.numberer_value.text()

    # Linear Static never iterates - Newton/tolerance convergence must not
    # appear to apply to it.
    assert not settings.convergence_card.isVisible()

    setup.close()


def test_nonlinear_static_inline_advanced_changes_reach_run_options() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()

    assert not settings.solver.isVisible()
    settings.nonlinear_advanced_toggle.setChecked(True)
    application.processEvents()
    assert settings.solver.isVisible()

    settings.algorithm.setCurrentText("KrylovNewton")
    settings.test_type.setCurrentText("EnergyIncr")
    settings.constraints_type.setCurrentText("Transformation")
    settings.numberer.setCurrentText("AMD")
    settings.solver.setCurrentText("UmfPack")
    application.processEvents()

    options = settings.config_store.options
    assert options["algorithm"] == "KrylovNewton"
    assert options["test_type"] == "EnergyIncr"
    assert options["constraints_type"] == "Transformation"
    assert options["numberer"] == "AMD"
    assert options["system"] == "UmfPack"
    assert not settings.convergence_card.isVisible()

    setup.close()


def test_modal_shows_engine_fixed_solver_and_hides_convergence() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.MODAL)
    application.processEvents()

    assert not settings.solver.isVisible()
    assert "BandGeneral" in settings.solver_fixed_value.text()
    assert "FIXED" in settings.solver_fixed_value.text()

    # Modal has no Newton/tolerance convergence loop - must not look editable.
    assert not settings.convergence_card.isVisible()

    setup.close()


def test_time_history_no_longer_uses_the_shared_solution_and_convergence_cards() -> None:
    """Phase 3-E: Time History gets its own "4. SOLUTION / CONVERGENCE" card
    (see time_history_solution_card) instead of the shared solution_card/
    convergence_card Nonlinear Static uses - both must be hidden for this
    kind now, not shown a second time."""
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.TIME_HISTORY)
    application.processEvents()

    assert not settings.solution_card.isVisible()
    assert not settings.convergence_card.isVisible()

    setup.close()


def test_switching_kinds_back_and_forth_restores_the_correct_solver_editability() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()
    assert not settings.solver.isVisible()
    settings.nonlinear_advanced_toggle.setChecked(True)
    application.processEvents()
    assert settings.solver.isVisible()
    assert not settings.solver_fixed_value.isVisible()

    # Linear Static's SOLVER is ENGINE_FIXED, but only visible once ADVANCED
    # ENGINE DETAILS is expanded (see Phase 3-B) - Modal/Time History hide
    # solution_card outright now (Phase 3-C/3-E), so neither shows
    # solver_fixed_value at all regardless of expand state.
    settings.config_store.set_kind(AnalysisKind.LINEAR_STATIC)
    application.processEvents()
    assert not settings.solver.isVisible()
    assert not settings.solver_fixed_value.isVisible()
    settings.engine_details_toggle.setChecked(True)
    application.processEvents()
    assert settings.solver_fixed_value.isVisible()

    settings.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()
    assert not settings.solver.isVisible()
    settings.nonlinear_advanced_toggle.setChecked(True)
    application.processEvents()
    assert settings.solver.isVisible()
    assert not settings.solver_fixed_value.isVisible()

    setup.close()


def test_time_history_guide_no_longer_shows_stale_not_implemented_text() -> None:
    """Phase 3-A.1: Time History is fully implemented and working end-to-end,
    but the ANALYSIS GUIDE panel still called it "not implemented yet" - the
    same kind of stale-state bug Phase 1 fixed for the MODEL screen's type
    selector, just in a different dict (setup_workspace._GUIDE_TEXT)."""
    application, setup = _make_setup()

    setup.config_store.set_kind(AnalysisKind.TIME_HISTORY)
    application.processEvents()

    guide_text = setup.guide_text.text().lower()
    assert "not implemented" not in guide_text
    assert "newmark" in guide_text

    setup.close()


def test_linear_static_shows_its_own_loads_and_analysis_method_card() -> None:
    """Phase 3-B: Linear Static gets a compact LOADS/ANALYSIS METHOD card
    instead of the shared "1. LOAD & CONTROL" card, whose Gravity/Lateral/
    Control/Steps rows describe Nonlinear Static's pushover staging and mean
    nothing for a single-step linear solve."""
    application, setup = _make_setup()
    settings = setup.settings_panel

    model = StructuralModel(
        ndm=2,
        ndf=3,
        nodal_loads=[NodalLoad(node_tag=1, values=(10.0, 0.0, 0.0), pattern_tag=2)],
    )
    setup.set_model(model)
    settings.config_store.set_kind(AnalysisKind.LINEAR_STATIC)
    application.processEvents()

    assert not settings.load_card.isVisible()
    assert settings.linear_static_group.isVisible()
    assert settings.linear_static_load_value.text() == "Pattern 2"

    # Nonlinearity must not appear to be part of Linear Static's workflow.
    assert not settings.nonlinear_group.isVisible()
    assert not settings.modal_group.isVisible()
    assert not settings.time_history_group.isVisible()

    setup.close()


def test_linear_static_flow_and_guide_are_its_own() -> None:
    application, setup = _make_setup()

    setup.config_store.set_kind(AnalysisKind.LINEAR_STATIC)
    application.processEvents()

    flow_labels = [
        setup._flow_list_widget.item(index).text()
        for index in range(setup._flow_list_widget.count())
    ]
    flow_text = " ".join(flow_labels)
    # The flow must not read like Nonlinear Static's workflow.
    assert "Nonlinearity" not in flow_text
    assert "Convergence" not in flow_text
    assert "Analysis Method" in flow_text

    assert setup.guide_topic.text() == "LINEAR STATIC"

    setup.close()


def test_switching_between_linear_static_and_other_kinds_leaves_no_residue() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    for other_kind in (
        AnalysisKind.NONLINEAR_STATIC,
        AnalysisKind.MODAL,
        AnalysisKind.TIME_HISTORY,
    ):
        settings.config_store.set_kind(other_kind)
        application.processEvents()
        assert not settings.linear_static_group.isVisible()
        assert not settings.load_card.isVisible()
        assert settings.nonlinear_group.isVisible() == (
            other_kind == AnalysisKind.NONLINEAR_STATIC
        )

        settings.config_store.set_kind(AnalysisKind.LINEAR_STATIC)
        application.processEvents()
        assert settings.linear_static_group.isVisible()
        assert not settings.load_card.isVisible()
        # Re-entering Linear Static always starts collapsed again, even if a
        # previous visit had it expanded.
        assert not settings.engine_details_toggle.isChecked()
        assert not settings.solution_body.isVisible()


def test_modal_presentation_dictionaries_no_longer_rely_on_fallbacks() -> None:
    """Phase 3-C, Known Issue #1: AnalysisKind.MODAL used to be entirely
    absent from setup_workspace's five presentation dicts - the page title
    only happened to look right because AnalysisKind.MODAL's own string value
    ("modal") survived the ``.get(kind, kind)`` fallback; Flow and Guide were
    silently empty."""
    for mapping in (_KIND_LABELS, _FLOW_STEPS, _GUIDE_TEXT, _GUIDE_TOPIC, _GUIDE_CALLOUT):
        assert AnalysisKind.MODAL in mapping
        assert mapping[AnalysisKind.MODAL]


def test_modal_flow_and_guide_are_its_own() -> None:
    application, setup = _make_setup()

    setup.config_store.set_kind(AnalysisKind.MODAL)
    application.processEvents()

    flow_labels = [
        setup._flow_list_widget.item(index).text()
        for index in range(setup._flow_list_widget.count())
    ]
    flow_text = " ".join(flow_labels)
    assert "Modal Parameters" in flow_text
    assert "Eigen Solution" in flow_text
    assert "Loading" not in flow_text
    assert "Nonlinearity" not in flow_text
    assert "Convergence" not in flow_text

    assert setup.guide_topic.text() == "MODAL ANALYSIS"
    guide_text = setup.guide_text.text()
    assert "not implemented" not in guide_text.lower()

    setup.close()


def test_modal_core_configuration_hides_unrelated_cards() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.MODAL)
    application.processEvents()

    # Number of Modes is visible and reachable - still the exact same widget/
    # options path build_options() has always used for Modal.
    assert settings.modal_group.isVisible()
    assert settings.num_modes.isVisible()

    # Nonlinear Static's staging/behavior concepts must not appear to apply.
    assert not settings.load_card.isVisible()
    assert not settings.nonlinear_group.isVisible()
    assert not settings.convergence_card.isVisible()
    assert not settings.solution_card.isVisible()

    setup.close()


def test_modal_number_of_modes_change_reaches_the_config_store() -> None:
    """Regression test for the sync bug found while implementing Phase 3-C:
    self.num_modes had no valueChanged connection at all, so a value typed
    here was silently dropped from config_store.options (and therefore from
    what RUN ANALYSIS actually sends the engine) until some unrelated event
    happened to call _sync_store_options() anyway."""
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.MODAL)
    application.processEvents()

    settings.num_modes.setValue(9)
    application.processEvents()

    assert settings.config_store.options.get("num_modes") == 9

    setup.close()


def test_modal_eigen_solution_matches_the_capability_registry() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.MODAL)
    application.processEvents()

    assert settings.modal_engine_card.isVisible()
    eigen = ANALYSIS_CAPABILITIES[AnalysisKind.MODAL].eigen_solver
    details = dict(eigen.details)

    # Walk every QLabel under the card instead of hardcoding widget names, so
    # this stays correct even if the internal layout is rearranged later.
    from PySide6.QtWidgets import QLabel

    labels = " | ".join(
        label.text() for label in settings.modal_engine_card.findChildren(QLabel)
    )
    assert "Automatic" in labels
    assert "AUTO" in labels
    assert details["primary"] in labels
    assert details["fallback"] in labels

    setup.close()


def test_modal_advanced_engine_details_start_collapsed_and_match_registry() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.MODAL)
    application.processEvents()

    assert not settings.modal_engine_details_toggle.isChecked()
    assert not settings.modal_engine_details_body.isVisible()

    settings.modal_engine_details_toggle.setChecked(True)
    application.processEvents()
    assert settings.modal_engine_details_body.isVisible()

    from PySide6.QtWidgets import QLabel

    labels = " | ".join(
        label.text() for label in settings.modal_engine_details_body.findChildren(QLabel)
    )
    capabilities = ANALYSIS_CAPABILITIES[AnalysisKind.MODAL]
    assert capabilities.equation_solver.value in labels
    assert capabilities.algorithm.value in labels
    assert capabilities.constraint_handler.value in labels
    assert capabilities.numberer.value in labels
    assert "FIXED" in labels

    setup.close()


def test_switching_between_modal_and_other_kinds_leaves_no_residue() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    for other_kind in (
        AnalysisKind.LINEAR_STATIC,
        AnalysisKind.NONLINEAR_STATIC,
        AnalysisKind.TIME_HISTORY,
    ):
        settings.config_store.set_kind(AnalysisKind.MODAL)
        application.processEvents()
        assert settings.modal_group.isVisible()
        assert settings.modal_engine_card.isVisible()
        # Expanding here must not leak into the next Modal visit.
        settings.modal_engine_details_toggle.setChecked(True)
        application.processEvents()

        settings.config_store.set_kind(other_kind)
        application.processEvents()
        assert not settings.modal_group.isVisible()
        assert not settings.modal_engine_card.isVisible()

        settings.config_store.set_kind(AnalysisKind.MODAL)
        application.processEvents()
        assert settings.modal_group.isVisible()
        assert settings.modal_engine_card.isVisible()
        assert not settings.modal_engine_details_toggle.isChecked()
        assert not settings.modal_engine_details_body.isVisible()

    setup.close()


def _model_with_pattern(pattern_tag: int = 2, *, nonlinear_element: bool = False) -> StructuralModel:
    elements = {}
    if nonlinear_element:
        elements[1] = Element(
            tag=1, node_i=1, node_j=2, element_type="forceBeamColumn"
        )
    return StructuralModel(
        ndm=2,
        ndf=3,
        nodes={1: Node(tag=1, x=0.0, y=0.0), 2: Node(tag=2, x=6.0, y=0.0)},
        elements=elements,
        nodal_loads=[NodalLoad(node_tag=1, values=(10.0, 0.0, 0.0), pattern_tag=pattern_tag)],
    )


def test_nonlinear_static_load_control_shows_only_relevant_inline_inputs() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.set_model(_model_with_pattern())
    settings.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()

    assert settings.nonlinear_group.isVisible()
    for widget in (
        settings.gravity_pattern,
        settings.lateral_pattern,
        settings.integrator_type,
        settings.num_steps,
    ):
        assert widget.isVisible()
    assert not settings.control_node_group.isVisible()
    assert not settings.control_dof_group.isVisible()
    assert not settings.target_displacement_group.isVisible()
    assert settings.nonlinear_advanced_toggle.isVisible()
    assert not settings.nonlinear_advanced_body.isVisible()

    setup.close()


def test_nonlinear_static_displacement_control_reveals_control_inputs_inline() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.set_model(_model_with_pattern())
    settings.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()

    settings.integrator_type.setCurrentIndex(settings.integrator_type.findData("DisplacementControl"))
    settings.target_displacement.setValue(0.05)
    application.processEvents()

    assert settings.control_node_group.isVisible()
    assert settings.control_dof_group.isVisible()
    assert settings.target_displacement_group.isVisible()
    assert settings.num_steps.isVisible()
    assert settings.target_displacement.value() == 0.05

    setup.close()


def test_nonlinear_static_material_nonlinearity_tile_reflects_the_model() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)

    settings.set_model(_model_with_pattern(nonlinear_element=True))
    application.processEvents()
    assert settings.material_nonlinearity_value.property("state") == "ok"
    assert "✓" in settings.material_nonlinearity_value.text()

    settings.set_model(_model_with_pattern(nonlinear_element=False))
    application.processEvents()
    assert settings.material_nonlinearity_value.property("state") == "off"
    assert "✓" not in settings.material_nonlinearity_value.text()

    # Geometric nonlinearity is not knowable from StructuralModel (the
    # imported script's own geomTransf choice never reaches it) - it must not
    # claim a specific state either way.
    assert "Not tracked" in settings.geometric_nonlinearity_value.text()

    setup.close()


def test_nonlinear_static_advanced_solution_and_convergence_are_collapsible() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()
    assert not settings.nonlinear_advanced_body.isVisible()

    settings.nonlinear_advanced_toggle.setChecked(True)
    application.processEvents()
    assert settings.nonlinear_advanced_body.isVisible()
    for widget in (
        settings.solver,
        settings.algorithm,
        settings.constraints_type,
        settings.test_type,
        settings.tolerance,
        settings.max_iterations,
        settings.max_bisections,
        settings.execution_timeout,
    ):
        assert widget.isVisible()

    # Time History has its own "4. SOLUTION / CONVERGENCE" card now (Phase
    # 3-E) - the shared card (and this recovery summary, which only makes
    # sense for Nonlinear Static's algorithm-fallback/bisection strategy)
    # must not leak into it.
    settings.config_store.set_kind(AnalysisKind.TIME_HISTORY)
    application.processEvents()
    assert not settings.convergence_card.isVisible()
    assert not settings.nonlinear_group.isVisible()

    setup.close()


def test_nonlinear_static_guide_covers_control_modes_and_convergence() -> None:
    application, setup = _make_setup()

    setup.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)
    application.processEvents()

    guide_text = setup.guide_text.text()
    assert "Displacement Control" in guide_text
    assert "Load Control" in guide_text
    assert "collapsed" in guide_text.lower()

    setup.close()


def test_switching_between_nonlinear_static_and_other_kinds_leaves_no_residue() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.set_model(_model_with_pattern(nonlinear_element=True))

    for other_kind in (
        AnalysisKind.LINEAR_STATIC,
        AnalysisKind.MODAL,
        AnalysisKind.TIME_HISTORY,
    ):
        settings.config_store.set_kind(AnalysisKind.NONLINEAR_STATIC)
        application.processEvents()
        assert settings.nonlinear_group.isVisible()
        assert settings.integrator_type.isVisible()
        assert not settings.nonlinear_advanced_body.isVisible()

        settings.config_store.set_kind(other_kind)
        application.processEvents()
        assert not settings.nonlinear_group.isVisible()

    setup.close()


def test_time_history_flow_is_its_own() -> None:
    application, setup = _make_setup()

    setup.config_store.set_kind(AnalysisKind.TIME_HISTORY)
    application.processEvents()

    flow_labels = [
        setup._flow_list_widget.item(index).text()
        for index in range(setup._flow_list_widget.count())
    ]
    flow_text = " ".join(flow_labels)
    assert "Ground Motion" in flow_text
    assert "Damping" in flow_text
    assert "Time Integration" in flow_text
    assert "Solution" in flow_text
    assert "Loading" not in flow_text
    assert "Nonlinearity" not in flow_text
    assert "Convergence" not in flow_text

    setup.close()


def test_time_history_shows_its_own_four_cards_and_hides_nonlinear_ones() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.TIME_HISTORY)
    application.processEvents()

    assert settings.time_history_group.isVisible()
    for card in (
        settings.time_history_ground_motion_card,
        settings.time_history_damping_card,
        settings.time_history_integration_card,
        settings.time_history_solution_card,
    ):
        assert card.isVisible()

    # None of Nonlinear Static's cards (or their contents) may show through.
    assert not settings.load_card.isVisible()
    assert not settings.nonlinear_group.isVisible()
    assert not settings.linear_static_group.isVisible()
    assert not settings.modal_group.isVisible()
    assert not settings.modal_engine_card.isVisible()
    assert not settings.solution_card.isVisible()
    assert not settings.convergence_card.isVisible()

    setup.close()


def test_time_history_ground_motion_direction_and_scale_reach_the_config_store() -> None:
    """Regression test for the sync bug found while implementing Phase 3-E:
    time_history_direction/ground_motion_scale/damping_ratio had no
    valueChanged/currentIndexChanged connection at all (the same gap
    num_modes had in Phase 3-C), so a value picked here was silently dropped
    from config_store.options until an unrelated event happened to sync it."""
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.TIME_HISTORY)
    application.processEvents()

    settings.time_history_direction.addItem("UY", 2)
    settings.time_history_direction.setCurrentIndex(
        settings.time_history_direction.findData(2)
    )
    settings.ground_motion_scale.setValue(9.81)
    settings.damping_ratio.setValue(0.02)
    application.processEvents()

    assert settings.config_store.options.get("direction") == 2
    assert settings.config_store.options.get("scale_factor") == 9.81
    assert settings.config_store.options.get("damping_ratio") == 0.02

    setup.close()


def test_time_history_integration_and_solution_cards_match_the_capability_registry() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    settings.config_store.set_kind(AnalysisKind.TIME_HISTORY)
    application.processEvents()

    from PySide6.QtWidgets import QLabel

    capabilities = ANALYSIS_CAPABILITIES[AnalysisKind.TIME_HISTORY]

    integration_labels = " | ".join(
        label.text()
        for label in settings.time_history_integration_card.findChildren(QLabel)
    )
    assert capabilities.dynamic_integrator.value in integration_labels
    assert dict(capabilities.dynamic_integrator.details)["gamma"] in integration_labels
    assert dict(capabilities.dynamic_integrator.details)["beta"] in integration_labels

    solution_labels = " | ".join(
        label.text() for label in settings.time_history_solution_card.findChildren(QLabel)
    )
    assert capabilities.equation_solver.value in solution_labels
    assert capabilities.algorithm.value in solution_labels
    assert capabilities.constraint_handler.value in solution_labels
    assert capabilities.numberer.value in solution_labels
    assert capabilities.convergence_test.value in solution_labels
    details = dict(capabilities.convergence_test.details)
    assert details["tolerance"] in solution_labels
    assert details["maxIterations"] in solution_labels
    assert "FIXED" in solution_labels

    setup.close()


def test_switching_between_time_history_and_other_kinds_leaves_no_residue() -> None:
    application, setup = _make_setup()
    settings = setup.settings_panel

    for other_kind in (
        AnalysisKind.LINEAR_STATIC,
        AnalysisKind.NONLINEAR_STATIC,
        AnalysisKind.MODAL,
    ):
        settings.config_store.set_kind(AnalysisKind.TIME_HISTORY)
        application.processEvents()
        assert settings.time_history_group.isVisible()
        assert not settings.solution_card.isVisible()
        assert not settings.convergence_card.isVisible()

        settings.config_store.set_kind(other_kind)
        application.processEvents()
        assert not settings.time_history_group.isVisible()

    setup.close()
