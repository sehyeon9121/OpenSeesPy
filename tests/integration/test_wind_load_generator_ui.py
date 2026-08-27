"""3D Loads tab -> Generators -> Wind Load: the static wind pressure
procedure (``core.domain.wind_load``, hand-derived-closed-form tested on
its own in ``tests/unit/test_wind_load.py``) wired into Story Manager +
the load-entry store. This only checks the wiring, not the formula again.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from openframe.core.domain import NodalLoadEntry
from openframe.core.domain.wind_load import WindLoadParameters, wind_force_by_story
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.features.model.presentation.safe_spinbox import SafeComboBox


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1280, 800)
    page.show()
    page._show_category("load")
    return page


def _two_story_frame_with_stories(page: ModelingInterfacePage) -> None:
    canvas = page.canvas
    base1 = canvas._add_node_at((0.0, 0.0, 0.0))
    base2 = canvas._add_node_at((4.0, 0.0, 0.0))
    mid1 = canvas._add_node_at((0.0, 0.0, 3.0))
    mid2 = canvas._add_node_at((4.0, 0.0, 3.0))
    top1 = canvas._add_node_at((0.0, 0.0, 6.0))
    top2 = canvas._add_node_at((4.0, 0.0, 6.0))
    canvas.add_member(base1, mid1)
    canvas.add_member(base2, mid2)
    canvas.add_member(mid1, top1)
    canvas.add_member(mid2, top2)
    canvas.add_story("1F", 3.0)
    canvas.add_story("2F", 6.0)


def _set_kz(page: ModelingInterfacePage, values: dict[str, float]) -> None:
    for row in range(page.wind_kz_table.rowCount()):
        name_item = page.wind_kz_table.item(row, 0)
        story_id = name_item.data(Qt.ItemDataRole.UserRole)
        if story_id in values:
            page.wind_kz_table.item(row, 1).setText(str(values[story_id]))


def test_generating_wind_load_creates_entries_matching_the_domain_calculation() -> None:
    page = _page()
    _two_story_frame_with_stories(page)
    case_id = page.canvas.add_load_case("WLX")
    assert case_id is not None

    page.wind_q0.setValue(1.2)
    page.wind_gust_factor.setValue(0.85)
    page.wind_pressure_coefficient.setValue(1.3)
    page.wind_exposed_width.setValue(10.0)
    page.wind_direction_combo.setCurrentIndex(page.wind_direction_combo.findData("x"))
    page._refresh_wind_kz_table()
    _set_kz(page, {"1F": 0.85, "2F": 1.0})
    page._refresh_wind_case_combo()
    page.wind_case_combo.setCurrentIndex(page.wind_case_combo.findData(case_id))

    page._generate_wind_load()

    entries = [entry for entry in page.canvas.load_entries.values() if entry.case_id == case_id]
    assert entries
    assert all(isinstance(entry.payload, NodalLoadEntry) for entry in entries)
    assert all(
        (entry.payload.fy, entry.payload.fz, entry.payload.mx, entry.payload.my, entry.payload.mz)
        == (0.0, 0.0, 0.0, 0.0, 0.0)
        for entry in entries
    )

    parameters = WindLoadParameters(
        reference_pressure=1.2, gust_factor=0.85, pressure_coefficient=1.3, exposed_width=10.0
    )
    expected_forces = wind_force_by_story(
        parameters, {"1F": 0.85, "2F": 1.0}, {"1F": 3.0, "2F": 6.0}
    )
    applied_total = sum(entry.payload.fx for entry in entries)
    assert applied_total == pytest.approx(sum(expected_forces.values()), rel=1.0e-6)

    model = page.canvas.build_model()
    nodes_by_z = {tag: node.z for tag, node in model.nodes.items()}
    force_at_1f = sum(
        entry.payload.fx for entry in entries for tag in entry.target if nodes_by_z[tag] == 3.0
    )
    force_at_2f = sum(
        entry.payload.fx for entry in entries for tag in entry.target if nodes_by_z[tag] == 6.0
    )
    assert force_at_1f == pytest.approx(expected_forces["1F"], rel=1.0e-6)
    assert force_at_2f == pytest.approx(expected_forces["2F"], rel=1.0e-6)
    # Even split across the two nodes sharing each story.
    per_node_1f = {
        entry.payload.fx for entry in entries for tag in entry.target if nodes_by_z[tag] == 3.0
    }
    assert len(per_node_1f) == 1


def test_regenerating_wind_load_replaces_rather_than_doubles() -> None:
    page = _page()
    _two_story_frame_with_stories(page)
    case_id = page.canvas.add_load_case("WLX")
    page.wind_q0.setValue(1.0)
    page.wind_exposed_width.setValue(8.0)
    page._refresh_wind_case_combo()
    page.wind_case_combo.setCurrentIndex(page.wind_case_combo.findData(case_id))

    page._generate_wind_load()
    first_count = sum(1 for entry in page.canvas.load_entries.values() if entry.case_id == case_id)
    page._generate_wind_load()
    second_count = sum(1 for entry in page.canvas.load_entries.values() if entry.case_id == case_id)

    assert first_count == second_count


def test_without_exposed_width_reports_a_status_message_not_a_crash() -> None:
    page = _page()
    _two_story_frame_with_stories(page)
    case_id = page.canvas.add_load_case("WLX")
    page._refresh_wind_case_combo()
    page.wind_case_combo.setCurrentIndex(page.wind_case_combo.findData(case_id))

    page._generate_wind_load()

    assert "노출 폭" in page.wind_result_label.text()


def test_kz_table_tracks_story_manager_and_preserves_edits_on_refresh() -> None:
    page = _page()
    _two_story_frame_with_stories(page)
    assert page.wind_kz_table.rowCount() == 2

    _set_kz(page, {"1F": 0.77})
    page.canvas.add_story("3F", 9.0)

    assert page.wind_kz_table.rowCount() == 3
    values = {}
    for row in range(page.wind_kz_table.rowCount()):
        name_item = page.wind_kz_table.item(row, 0)
        values[name_item.data(Qt.ItemDataRole.UserRole)] = page.wind_kz_table.item(row, 1).text()
    assert values["1F"] == "0.77"
    assert values["3F"] == "1.0"


def test_wind_setup_uses_full_names_and_converts_basic_speed_to_model_pressure() -> None:
    page = _page()

    assert "건축물 설계하중" in page.wind_code_combo.currentText()
    labels = [label.text() for label in page.findChildren(type(page.wind_pressure_summary))]
    assert "기본풍속 V0 (m/s)" in labels
    assert "가스트영향계수 Gf (Gust Effect Factor)" in labels
    assert "순풍압계수 Cp (Net Pressure Coefficient)" in labels

    page.wind_calculation_method.setCurrentIndex(
        page.wind_calculation_method.findData("velocity")
    )
    page.wind_basic_speed.setValue(26.0)
    page.wind_air_density.setValue(1.225)
    page.wind_directionality_factor.setValue(1.0)
    page.wind_topographic_factor.setValue(1.0)
    page.wind_importance_factor.setValue(1.0)

    # 0.5 * rho * V² = 414.05 Pa = 0.41405 kN/m² in the default unit system.
    assert page.wind_q0.value() == pytest.approx(0.41405, rel=1.0e-4)
    assert page.wind_q0.isReadOnly()


def test_negative_wind_direction_and_scale_are_applied_to_generated_entries() -> None:
    page = _page()
    _two_story_frame_with_stories(page)
    case_id = page.canvas.add_load_case("WL_NEG_X")
    page.wind_q0.setValue(1.0)
    page.wind_exposed_width.setValue(8.0)
    page.wind_direction_combo.setCurrentIndex(page.wind_direction_combo.findData("-x"))
    page.wind_scale_factor.setValue(1.5)
    page._refresh_wind_case_combo()
    page.wind_case_combo.setCurrentIndex(page.wind_case_combo.findData(case_id))

    page._generate_wind_load()

    entries = [entry for entry in page.canvas.load_entries.values() if entry.case_id == case_id]
    assert entries
    assert all(entry.payload.fx < 0.0 for entry in entries)
    expected = wind_force_by_story(
        WindLoadParameters(
            reference_pressure=1.0,
            gust_factor=0.85,
            pressure_coefficient=1.3,
            exposed_width=8.0,
        ),
        {"1F": 1.0, "2F": 1.0},
        {"1F": 3.0, "2F": 6.0},
    )
    assert sum(entry.payload.fx for entry in entries) == pytest.approx(
        -1.5 * sum(expected.values())
    )


def test_every_wind_generator_dropdown_ignores_scroll_wheel() -> None:
    """A scroll gesture passing over a dropdown while the user scrolls the
    panel must never silently change its selection - see safe_spinbox.py.
    Every QComboBox this page builds for the wind generator must be a
    SafeComboBox (or another wheel-ignoring variant), never a plain one."""
    page = _page()
    page._show_category("load")
    for name in (
        "wind_code_combo",
        "wind_case_combo",
        "wind_calculation_method",
        "wind_exposure_category",
        "wind_structure_type",
        "wind_direction_combo",
    ):
        combo = getattr(page, name)
        assert isinstance(combo, SafeComboBox), f"{name} must be a SafeComboBox"
