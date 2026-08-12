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
from PySide6.QtWidgets import QApplication, QFileDialog, QScrollArea

from openframe.core.domain import AnalysisKind
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


def test_time_history_build_options_matches_the_solvers_own_keyword_arguments() -> None:
    """run_time_history_analysis's kwargs are ground_motion_path/direction/
    damping_ratio/scale_factor - a different shape from both nonlinear's and
    modal's, so this needs its own early return too."""
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))
    panel._ground_motion_path = Path("C:/motions/el_centro.AT2")
    panel.time_history_direction.addItem("UY", 2)
    panel.time_history_direction.setCurrentIndex(
        panel.time_history_direction.findData(2)
    )
    panel.damping_ratio.setValue(0.02)
    panel.ground_motion_scale.setValue(9.81)

    options = panel.build_options()

    assert options == {
        "ground_motion_path": "C:\\motions\\el_centro.AT2",
        "direction": 2,
        "damping_ratio": 0.02,
        "scale_factor": 9.81,
    }
    application.processEvents()


def test_time_history_build_options_defaults_to_direction_1_with_no_model_loaded() -> None:
    """set_model() is what normally populates time_history_direction - a panel
    used before any model is loaded must not crash build_options()."""
    application = QApplication.instance() or QApplication([])
    panel = AnalysisSettingsPanel()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))

    options = panel.build_options()

    assert options["ground_motion_path"] == ""
    assert options["direction"] == 1
    application.processEvents()


def _stub_file_dialog(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(path), ""))
    )


class TestGroundMotionBrowse:
    """Phase 3-F: picking a file now loads it through GroundMotion immediately
    (not just at RUN time inside the worker subprocess), so a bad file is
    caught, and the metadata it lets us verify (dt/NPTS/duration/PGA/unit) is
    shown right away instead of only living inside build_options()'s opaque
    path string."""

    def test_picking_a_valid_file_shows_its_metadata_and_syncs_the_store(
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
        panel = AnalysisSettingsPanel()
        panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))

        panel._choose_ground_motion_file()

        assert panel._ground_motion is not None
        assert panel._ground_motion.pga == pytest.approx(0.5)
        # Phase 3-G moved the metadata out of the file-path label and into the
        # shared info grid (Built-in and Imported both feed the same grid).
        assert panel.ground_motion_path_label.text() == "motion.AT2"
        assert panel.gm_dt_value.text() == "0.02 s"
        assert panel.gm_npts_value.text() == "4"
        assert "0.5" in panel.gm_pga_value.text()
        assert "G" in panel.gm_pga_value.text()
        assert panel.build_options()["ground_motion_path"] == str(motion_path)
        application.processEvents()

    def test_picking_a_malformed_file_reports_an_error_and_clears_selection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        application = QApplication.instance() or QApplication([])
        bad_path = tmp_path / "not_a_motion.txt"
        bad_path.write_text("this file has no numbers in it at all\n", encoding="utf-8")
        _stub_file_dialog(monkeypatch, bad_path)
        panel = AnalysisSettingsPanel()
        panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))

        panel._choose_ground_motion_file()

        assert panel._ground_motion is None
        assert panel._ground_motion_path is None
        assert panel.build_options()["ground_motion_path"] == ""
        application.processEvents()

    def test_a_malformed_file_does_not_clobber_a_previously_valid_selection_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Selecting a bad file after a good one must not leave the store
        pointing at the (now-replaced) good path while the label claims
        failure - the two must agree, so the good selection is cleared too."""
        application = QApplication.instance() or QApplication([])
        good_path = tmp_path / "good.txt"
        good_path.write_text("NPTS=2, DT=0.01 SEC\n1.0 -2.0\n", encoding="utf-8")
        bad_path = tmp_path / "bad.txt"
        bad_path.write_text("no numbers here\n", encoding="utf-8")
        panel = AnalysisSettingsPanel()
        panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))

        _stub_file_dialog(monkeypatch, good_path)
        panel._choose_ground_motion_file()
        assert panel.build_options()["ground_motion_path"] == str(good_path)

        _stub_file_dialog(monkeypatch, bad_path)
        panel._choose_ground_motion_file()

        assert panel.build_options()["ground_motion_path"] == ""
        application.processEvents()


def _time_history_panel() -> AnalysisSettingsPanel:
    panel = AnalysisSettingsPanel()
    panel.show()
    panel.analysis_type.setCurrentIndex(panel.analysis_type.findData(AnalysisKind.TIME_HISTORY))
    return panel


class TestBuiltInGroundMotionLibrary:
    """Phase 3-G: Built-in Library / Imported File as two selectable sources
    for the same GROUND MOTION card, sharing one info grid, one preview, and
    one scaling section - build_options() must never care which source was
    used, only what wound up in _ground_motion/_ground_motion_path."""

    def test_built_in_library_lists_the_bundled_records_including_kobe(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()

        labels = [
            panel.builtin_record_combo.itemText(index)
            for index in range(panel.builtin_record_combo.count())
        ]
        assert panel.builtin_record_combo.count() == 65
        assert any("Kobe" in label for label in labels)
        application.processEvents()

    def test_selecting_built_in_populates_the_info_grid_and_preview(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()

        panel.source_builtin_radio.setChecked(True)

        assert panel._ground_motion is not None
        assert panel.builtin_record_row.isVisible()
        assert not panel.imported_file_row.isVisible()
        assert panel.gm_npts_value.text() == str(panel._ground_motion.npts)
        assert panel.build_options()["ground_motion_path"] == str(panel._ground_motion.path)
        application.processEvents()

    def test_preview_series_matches_the_selected_motions_accelerations(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        panel.source_builtin_radio.setChecked(True)
        motion = panel._ground_motion
        assert motion is not None

        preview_values = panel.ground_motion_preview._values
        preview_times = panel.ground_motion_preview._times

        assert len(preview_values) == motion.npts
        assert preview_values == pytest.approx(motion.accelerations)
        assert preview_times[1] == pytest.approx(motion.dt)
        application.processEvents()

    def test_scale_factor_change_updates_applied_pga_and_preview(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        panel.source_builtin_radio.setChecked(True)
        motion = panel._ground_motion
        assert motion is not None

        panel.ground_motion_scale.setValue(2.0)

        assert panel.applied_pga_value.text() == f"{motion.pga * 2.0:.4g} {motion.unit}"
        assert panel.ground_motion_preview._values == pytest.approx(
            tuple(value * 2.0 for value in motion.accelerations)
        )
        application.processEvents()

    def test_target_pga_computes_the_correct_scale_factor(self) -> None:
        application = QApplication.instance() or QApplication([])
        panel = _time_history_panel()
        panel.source_builtin_radio.setChecked(True)
        motion = panel._ground_motion
        assert motion is not None
        target = motion.pga * 1.5

        panel.target_pga_radio.setChecked(True)
        panel.target_pga_input.setValue(target)

        assert panel.ground_motion_scale.value() == pytest.approx(1.5, rel=1e-6)
        assert panel.build_options()["scale_factor"] == pytest.approx(1.5, rel=1e-6)
        application.processEvents()

    def test_switching_source_leaves_no_stale_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        application = QApplication.instance() or QApplication([])
        imported_path = tmp_path / "imported.txt"
        imported_path.write_text("NPTS=3, DT=0.02 SEC\n0.1 0.2 -0.3\n", encoding="utf-8")
        panel = _time_history_panel()

        panel.source_builtin_radio.setChecked(True)
        builtin_motion = panel._ground_motion
        assert builtin_motion is not None

        _stub_file_dialog(monkeypatch, imported_path)
        panel.source_imported_radio.setChecked(True)
        panel._choose_ground_motion_file()
        assert panel._ground_motion is not None
        assert panel._ground_motion.path == imported_path
        assert panel.build_options()["ground_motion_path"] == str(imported_path)

        panel.source_builtin_radio.setChecked(True)
        assert panel._ground_motion is builtin_motion
        assert panel.build_options()["ground_motion_path"] == str(builtin_motion.path)

        panel.source_imported_radio.setChecked(True)
        assert panel._ground_motion is not None
        assert panel._ground_motion.path == imported_path
        application.processEvents()

    def test_zero_pga_disables_target_pga_with_a_clear_note(self, tmp_path: Path) -> None:
        application = QApplication.instance() or QApplication([])
        zero_path = tmp_path / "zero.txt"
        zero_path.write_text("NPTS=3, DT=0.01 SEC\n0 0 0\n", encoding="utf-8")
        panel = _time_history_panel()

        panel._imported_ground_motion_path = zero_path
        from openframe.infrastructure.opensees.ground_motion import load_ground_motion

        panel._imported_ground_motion = load_ground_motion(zero_path)
        panel._apply_active_ground_motion()

        assert not panel.target_pga_radio.isEnabled()
        assert panel.target_pga_unit_note.isVisible()
        application.processEvents()

    def test_unknown_unit_disables_target_pga_with_a_clear_note(self, tmp_path: Path) -> None:
        application = QApplication.instance() or QApplication([])
        no_unit_path = tmp_path / "no_unit.csv"
        no_unit_path.write_text("0.00,0.10\n0.02,0.20\n0.04,-0.15\n", encoding="utf-8")
        panel = _time_history_panel()

        panel._imported_ground_motion_path = no_unit_path
        from openframe.infrastructure.opensees.ground_motion import load_ground_motion

        panel._imported_ground_motion = load_ground_motion(no_unit_path)
        panel._apply_active_ground_motion()

        assert panel._ground_motion is not None
        assert panel._ground_motion.unit is None
        assert not panel.target_pga_radio.isEnabled()
        assert panel.target_pga_unit_note.isVisible()
        assert panel.gm_unit_value.text() == "Not detected"
        application.processEvents()
