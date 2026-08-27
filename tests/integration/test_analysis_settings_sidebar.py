"""AnalysisSettingsSidebar - the Analysis Case skeleton added alongside the
3D canvas's existing (unchanged) method-selector/dialog/solve flow. Covers
case creation/switching not clobbering other cases, Quick Settings page
swap per kind, PRE-CHECK rendering, and this panel's own 320px width safety
(the same class of bug the Loads tab's seismic/wind generators hit earlier
this session - see modeling_interface_page.py's inline comments on the hint
labels/method combo this change also had to fix)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from openframe.core.domain import AnalysisKind
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1280, 800)
    page.show()
    page._show_category("analysis")
    return page


def test_sidebar_starts_with_exactly_one_default_case() -> None:
    page = _page()

    cases = page.analysis_case_store.list_cases()

    assert len(cases) == 1
    assert cases[0].kind == AnalysisKind.LINEAR_STATIC
    assert page.analysis_case_store.active_case_id() == cases[0].case_id
    assert page.analysis_settings_sidebar.quick_settings_section.isHidden()


def test_empty_quick_settings_and_assigned_data_cards_are_not_shown() -> None:
    page = _page()
    sidebar = page.analysis_settings_sidebar

    assert sidebar.quick_settings_section.isHidden()
    assert "ASSIGNED DATA" not in [
        label.text() for label in sidebar.findChildren(QLabel)
    ]


def test_creating_a_case_makes_it_active_and_swaps_the_quick_settings_page() -> None:
    page = _page()
    sidebar = page.analysis_settings_sidebar

    sidebar._create_case(AnalysisKind.NONLINEAR_STATIC)

    active_id = page.analysis_case_store.active_case_id()
    assert page.analysis_case_store.case(active_id).kind == AnalysisKind.NONLINEAR_STATIC
    current_page = sidebar.quick_settings_stack.currentWidget()
    expected_page = sidebar.quick_settings_stack.widget(
        sidebar._quick_pages[AnalysisKind.NONLINEAR_STATIC]
    )
    assert current_page is expected_page


def test_switching_between_cases_never_touches_the_others_settings() -> None:
    page = _page()
    store = page.analysis_case_store
    sidebar = page.analysis_settings_sidebar
    linear_id = store.active_case_id()
    store.case(linear_id).settings["load_factor"] = 1.5

    sidebar._create_case(AnalysisKind.MODAL)
    modal_id = store.active_case_id()
    store.case(modal_id).settings["num_modes"] = 20

    store.set_active_case(linear_id)

    assert store.case(linear_id).settings == {"load_factor": 1.5}
    assert store.case(modal_id).settings == {"num_modes": 20}


def test_duplicate_rename_delete_via_sidebar_handlers() -> None:
    page = _page()
    store = page.analysis_case_store
    sidebar = page.analysis_settings_sidebar
    original_id = store.active_case_id()

    sidebar._duplicate_active_case()
    duplicate_id = store.active_case_id()
    assert duplicate_id != original_id
    assert store.case(duplicate_id).kind == store.case(original_id).kind

    assert store.rename_case(duplicate_id, "LS-Renamed")
    assert store.case(duplicate_id).name == "LS-Renamed"

    sidebar._delete_active_case()
    assert not store.has_case(duplicate_id)
    assert store.active_case_id() == original_id


def test_delete_refuses_to_remove_the_last_case_via_the_sidebar() -> None:
    page = _page()
    store = page.analysis_case_store
    sidebar = page.analysis_settings_sidebar
    only_id = store.active_case_id()

    sidebar._delete_active_case()

    assert store.has_case(only_id)


def test_precheck_blocks_and_reports_when_the_model_is_empty() -> None:
    page = _page()
    sidebar = page.analysis_settings_sidebar

    sidebar.refresh_precheck()

    assert "실행할 수 없습니다" in sidebar.precheck_summary.text()
    assert sidebar.precheck_summary.property("state") == "error"


def test_precheck_passes_once_the_model_has_loaded_geometry_and_a_load() -> None:
    page = _page()
    a = page.canvas._add_node_at((0.0, 0.0, 0.0))
    b = page.canvas._add_node_at((4.0, 0.0, 0.0))
    page.canvas.add_member(a, b)
    page.canvas.selected_nodes = {a}
    page.canvas.apply_support_to_selection((True,) * 6)
    page.canvas.selected_nodes = {b}
    page.canvas.apply_nodal_load_to_selection((0.0, 0.0, -10.0, 0.0, 0.0, 0.0))
    sidebar = page.analysis_settings_sidebar

    sidebar.refresh_precheck()

    assert sidebar.precheck_summary.text() == "✓ 실행 가능"
    assert sidebar.precheck_summary.property("state") == "ok"


def test_analysis_category_page_stays_within_the_fixed_left_panel_width() -> None:
    page = _page()

    current = page.category_stack.currentWidget()

    assert current.sizeHint().width() <= page.left_panel_stack.width() - 24


def test_analysis_category_page_stays_within_width_with_a_time_history_case_active() -> None:
    """Time History's Quick Settings page (3 direction groups + summary
    cards + a common-fields form) is the tallest/most field-heavy page built
    so far - the one most likely to reproduce the width trap the plain
    placeholder pages could not."""
    page = _page()
    page.analysis_settings_sidebar._create_case(AnalysisKind.TIME_HISTORY)

    current = page.category_stack.currentWidget()

    assert current.sizeHint().width() <= page.left_panel_stack.width() - 24
    assert not page.analysis_settings_sidebar.quick_settings_section.isHidden()


def test_time_history_quick_settings_edits_write_into_the_active_cases_settings() -> None:
    page = _page()
    sidebar = page.analysis_settings_sidebar
    sidebar._create_case(AnalysisKind.TIME_HISTORY)
    case_id = page.analysis_case_store.active_case_id()
    quick_settings = sidebar._quick_widgets[AnalysisKind.TIME_HISTORY]

    quick_settings._direction_groups["x"].setChecked(True)
    quick_settings._scale_fields["x"].setValue(1.5)

    settings = page.analysis_case_store.case(case_id).settings
    assert settings["active_x"] is True
    assert settings["scale_factor_x"] == 1.5


def test_time_history_precheck_flags_missing_ground_motion_and_reports_not_wired() -> None:
    page = _page()
    a = page.canvas._add_node_at((0.0, 0.0, 0.0))
    b = page.canvas._add_node_at((4.0, 0.0, 0.0))
    page.canvas.add_member(a, b)
    sidebar = page.analysis_settings_sidebar
    sidebar._create_case(AnalysisKind.TIME_HISTORY)
    quick_settings = sidebar._quick_widgets[AnalysisKind.TIME_HISTORY]

    quick_settings._direction_groups["x"].setChecked(True)

    assert not sidebar.precheck_summary.property("state") == "ok"
    chip_texts = [
        sidebar.precheck_chip_row.itemAt(i).widget().text()
        for i in range(sidebar.precheck_chip_row.count() - 1)
    ]
    assert "X 방향 지진파 없음" in chip_texts
    assert "실행 미지원" in chip_texts


def test_switching_away_from_a_time_history_case_and_back_preserves_its_settings() -> None:
    page = _page()
    store = page.analysis_case_store
    sidebar = page.analysis_settings_sidebar
    sidebar._create_case(AnalysisKind.TIME_HISTORY)
    th_id = store.active_case_id()
    quick_settings = sidebar._quick_widgets[AnalysisKind.TIME_HISTORY]
    quick_settings._direction_groups["z"].setChecked(True)
    quick_settings.damping_ratio_field.setValue(0.02)

    sidebar._create_case(AnalysisKind.MODAL)
    store.set_active_case(th_id)

    settings = store.case(th_id).settings
    assert settings["active_z"] is True
    assert settings["damping_ratio"] == 0.02
    assert quick_settings._direction_groups["z"].isChecked() is True
