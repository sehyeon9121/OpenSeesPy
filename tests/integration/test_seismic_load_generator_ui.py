"""3D Loads tab -> Generators -> Static Seismic Load: the ELF procedure
(``core.domain.seismic_load``, hand-derived-closed-form tested on its own in
``tests/unit/test_seismic_load.py``) actually wired into the canvas's own
Story Manager + load-entry store. This only checks the wiring - equilibrium
(every generated node force sums to the code-computed base shear) and the
per-story split, not the ELF formula itself again.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import NodalLoadEntry
from openframe.core.domain.seismic_load import (
    SeismicLoadParameters,
    StoryWeight,
    equivalent_lateral_force,
)
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.features.model.presentation.safe_spinbox import SafeComboBox


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1280, 800)
    page.show()
    page._show_category("load")
    return page


def _two_story_steel_frame(page: ModelingInterfacePage) -> None:
    """Two stories, two columns each - identical section/material at every
    level, so each level's own lumped weight comes out equal and the test's
    expected split reduces to the plain ``h**k`` ratio."""
    canvas = page.canvas
    base1 = canvas._add_node_at((0.0, 0.0, 0.0))
    base2 = canvas._add_node_at((4.0, 0.0, 0.0))
    mid1 = canvas._add_node_at((0.0, 0.0, 3.0))
    mid2 = canvas._add_node_at((4.0, 0.0, 3.0))
    top1 = canvas._add_node_at((0.0, 0.0, 6.0))
    top2 = canvas._add_node_at((4.0, 0.0, 6.0))

    columns = [
        canvas.add_member(base1, mid1),
        canvas.add_member(base2, mid2),
        canvas.add_member(mid1, top1),
        canvas.add_member(mid2, top2),
    ]
    canvas.selected_elements = set(columns)
    canvas.apply_full_section_to_selection(
        shape="Rectangle",
        source="custom",
        dimensions={"b": 0.3, "h": 0.3},
        area=0.09,
        iy=0.000675,
        iz=0.000675,
        j=0.001,
        elastic=2.0e8,
        density=25.0,
    )

    canvas.selected_nodes = {base1, base2}
    canvas.apply_support_to_selection((True,) * 6)

    canvas.add_story("1F", 3.0)
    canvas.add_story("2F", 6.0)


def test_generating_seismic_load_creates_entries_that_sum_to_the_base_shear() -> None:
    page = _page()
    _two_story_steel_frame(page)
    case_id = page.canvas.add_load_case("EQX")
    assert case_id is not None

    page.seismic_ss.setValue(1.5)
    page.seismic_s1.setValue(0.6)
    page.seismic_fa.setValue(1.0)
    page.seismic_fv.setValue(1.5)
    page.seismic_r.setValue(8.0)
    page.seismic_ie.setValue(1.0)
    page.seismic_period.setValue(1.0)
    page.seismic_direction_combo.setCurrentIndex(page.seismic_direction_combo.findData("x"))
    page._refresh_seismic_case_combo()
    page.seismic_case_combo.setCurrentIndex(page.seismic_case_combo.findData(case_id))

    page._generate_seismic_load()

    entries = [
        entry for entry in page.canvas.load_entries.values() if entry.case_id == case_id
    ]
    assert entries
    assert all(isinstance(entry.payload, NodalLoadEntry) for entry in entries)
    # Load applied entirely in the chosen (X) direction, nothing in Y/Z/moments.
    assert all(
        (entry.payload.fy, entry.payload.fz, entry.payload.mx, entry.payload.my, entry.payload.mz)
        == (0.0, 0.0, 0.0, 0.0, 0.0)
        for entry in entries
    )

    model = page.canvas.build_model()
    # Each column weighs density*A*length = 25*0.09*3 = 6.75, half (3.375)
    # lumped to each end node. z=3 nodes (mid1/mid2) sit between a 1F column
    # below and a 2F column above, so each collects a half from *both* -
    # 6.75 each, 13.5 for the whole "1F" story. z=6 nodes (top1/top2) only
    # have a 2F column below them - 3.375 each, 6.75 for "2F". The base
    # (z=0) nodes' own half-weight is real but belongs to no Story, so (per
    # _generate_seismic_load's own equilibrium note) it is excluded from W.
    column_weight = 25.0 * 0.09 * 3.0
    weight_1f = 2.0 * column_weight  # mid1/mid2: half the 1F column below + half the 2F column above, x2 nodes
    weight_2f = 1.0 * column_weight  # top1/top2: half the 2F column below only, x2 nodes
    total_weight = weight_1f + weight_2f
    parameters = SeismicLoadParameters(ss=1.5, s1=0.6, fa=1.0, fv=1.5, r=8.0, ie=1.0, period=1.0)
    stories = {
        "1F": StoryWeight(height=3.0, weight=weight_1f),
        "2F": StoryWeight(height=6.0, weight=weight_2f),
    }
    _cs, expected_base_shear, expected_story_forces = equivalent_lateral_force(
        parameters, total_weight, stories
    )

    applied_total = sum(entry.payload.fx for entry in entries)
    assert applied_total == pytest.approx(expected_base_shear, rel=1.0e-6)

    # Split by story: every node at z=3 sums to 1F's own Fx, z=6 to 2F's.
    nodes_by_z = {tag: node.z for tag, node in model.nodes.items()}
    force_at_1f = sum(
        entry.payload.fx for entry in entries for tag in entry.target if nodes_by_z[tag] == 3.0
    )
    force_at_2f = sum(
        entry.payload.fx for entry in entries for tag in entry.target if nodes_by_z[tag] == 6.0
    )
    assert force_at_1f == pytest.approx(expected_story_forces["1F"], rel=1.0e-6)
    assert force_at_2f == pytest.approx(expected_story_forces["2F"], rel=1.0e-6)


def test_regenerating_replaces_the_previous_output_instead_of_doubling_it() -> None:
    page = _page()
    _two_story_steel_frame(page)
    case_id = page.canvas.add_load_case("EQX")
    page.seismic_ss.setValue(1.0)
    page.seismic_s1.setValue(0.4)
    page.seismic_r.setValue(4.0)
    page._refresh_seismic_case_combo()
    page.seismic_case_combo.setCurrentIndex(page.seismic_case_combo.findData(case_id))

    page._generate_seismic_load()
    first_count = sum(1 for entry in page.canvas.load_entries.values() if entry.case_id == case_id)

    page._generate_seismic_load()
    second_count = sum(1 for entry in page.canvas.load_entries.values() if entry.case_id == case_id)

    assert first_count == second_count


def test_without_a_case_selected_reports_a_status_message_not_a_crash() -> None:
    page = _page()
    _two_story_steel_frame(page)

    page._generate_seismic_load()

    assert "케이스" in page.seismic_result_label.text()


def test_without_stories_defined_reports_a_status_message_not_a_crash() -> None:
    page = _page()
    canvas = page.canvas
    a = canvas._add_node_at((0.0, 0.0, 0.0))
    b = canvas._add_node_at((4.0, 0.0, 3.0))
    canvas.add_member(a, b)
    case_id = canvas.add_load_case("EQX")
    page._refresh_seismic_case_combo()
    page.seismic_case_combo.setCurrentIndex(page.seismic_case_combo.findData(case_id))

    page._generate_seismic_load()

    assert "Story Manager" in page.seismic_result_label.text()


def test_seismic_setup_uses_full_names_and_shows_derived_spectrum_values() -> None:
    page = _page()

    assert "건축물 내진설계기준" in page.seismic_code_combo.currentText()
    labels = [label.text() for label in page.findChildren(type(page.seismic_result_label))]
    assert "단주기 응답스펙트럼 가속도 Ss (g)" in labels
    assert "반응수정계수 R (Response Modification Coefficient)" in labels
    assert "내진 중요도계수 Ie (Seismic Importance Factor)" in labels

    page.seismic_ss.setValue(1.5)
    page.seismic_s1.setValue(0.6)
    page.seismic_fa.setValue(1.0)
    page.seismic_fv.setValue(1.5)

    assert "SDS = 1.0000" in page.seismic_spectrum_summary.text()
    assert "SD1 = 0.6000" in page.seismic_spectrum_summary.text()


def test_seismic_direction_scale_and_explicit_eccentricity_create_force_and_moment() -> None:
    page = _page()
    _two_story_steel_frame(page)
    case_id = page.canvas.add_load_case("EQ_NEG_Y_ECC")
    page.seismic_ss.setValue(1.5)
    page.seismic_s1.setValue(0.6)
    page.seismic_fa.setValue(1.0)
    page.seismic_fv.setValue(1.5)
    page.seismic_r.setValue(8.0)
    page.seismic_ie.setValue(1.0)
    page.seismic_period.setValue(1.0)
    page.seismic_direction_combo.setCurrentIndex(
        page.seismic_direction_combo.findData("-y")
    )
    page.seismic_scale_factor.setValue(1.25)
    page.seismic_eccentricity_sign.setCurrentIndex(
        page.seismic_eccentricity_sign.findData(1.0)
    )
    page.seismic_eccentricity.setValue(2.0)
    page._refresh_seismic_case_combo()
    page.seismic_case_combo.setCurrentIndex(page.seismic_case_combo.findData(case_id))

    page._generate_seismic_load()

    entries = [entry for entry in page.canvas.load_entries.values() if entry.case_id == case_id]
    assert entries
    assert all(entry.payload.fy < 0.0 for entry in entries)
    assert all(entry.payload.mz == pytest.approx(entry.payload.fy * 2.0) for entry in entries)
    assert sum(entry.payload.fy for entry in entries) < 0.0
    assert "우발편심 Mz" in page.seismic_result_label.text()


def test_generator_specifications_round_trip_with_the_project() -> None:
    page = _page()
    page.wind_description.setText("서측 +X 풍하중")
    page.wind_exposure_category.setCurrentIndex(
        page.wind_exposure_category.findData("C")
    )
    page.wind_exposed_width.setValue(12.5)
    page.seismic_site_class.setCurrentIndex(page.seismic_site_class.findData("S4"))
    page.seismic_system_description.setText("철골 특수모멘트골조")
    page.seismic_r.setValue(8.0)
    page.seismic_eccentricity_sign.setCurrentIndex(
        page.seismic_eccentricity_sign.findData(-1.0)
    )
    page.seismic_eccentricity.setValue(1.25)

    restored = _page()
    restored.load_project_dict(page.to_project_dict())

    assert restored.wind_description.text() == "서측 +X 풍하중"
    assert restored.wind_exposure_category.currentData() == "C"
    assert restored.wind_exposed_width.value() == pytest.approx(12.5)
    assert restored.seismic_site_class.currentData() == "S4"
    assert restored.seismic_system_description.text() == "철골 특수모멘트골조"
    assert restored.seismic_r.value() == pytest.approx(8.0)
    assert restored.seismic_eccentricity_sign.currentData() == -1.0
    assert restored.seismic_eccentricity.value() == pytest.approx(1.25)


def test_every_seismic_generator_dropdown_ignores_scroll_wheel() -> None:
    """A scroll gesture passing over a dropdown while the user scrolls the
    panel must never silently change its selection - see safe_spinbox.py.
    Every QComboBox this page builds for the seismic generator must be a
    SafeComboBox (or another wheel-ignoring variant), never a plain one."""
    page = _page()
    page._show_category("load")
    for name in (
        "seismic_code_combo",
        "seismic_case_combo",
        "seismic_site_class",
        "seismic_period_method",
        "seismic_direction_combo",
        "seismic_eccentricity_sign",
    ):
        combo = getattr(page, name)
        assert isinstance(combo, SafeComboBox), f"{name} must be a SafeComboBox"
