"""SectionMaterialPanel: Database lookup/UI reflection, DB-edit-demotes-to-
CUSTOM, Reset to DB, Section+Material composition, and reselection persistence
(save/reselect keeping values) - the panel-level items from the section+
material DB integration's test list that aren't pure geometry math (that part
is tests/unit/test_section_properties.py) or full-canvas wiring (that part is
tests/integration/test_modeling_layout.py /
tests/unit/test_canvas_full_section_application.py)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import Element, UnitSystem
from openframe.features.model.presentation.canvas_property_application import (
    DEFAULT_POISSON_RATIO,
)
from openframe.features.model.presentation.section_material_panel import SectionMaterialPanel


def _panel() -> SectionMaterialPanel:
    QApplication.instance() or QApplication([])
    panel = SectionMaterialPanel()
    panel.show()
    return panel


def _select_h_section(panel: SectionMaterialPanel) -> None:
    panel.shape_combo.setCurrentText("H/I Section")
    panel.source_database.setChecked(True)
    assert panel.designation_combo.count() >= 1
    panel.designation_combo.setCurrentIndex(
        panel.designation_combo.findText("H-300x300x10x15")
    )


def test_database_h_section_lookup_reflects_dimensions_and_properties() -> None:
    """DB H형강 조회 및 UI 반영."""
    panel = _panel()
    _select_h_section(panel)

    assert panel._dimension_spinboxes["H"].value() == 0.3
    assert panel._dimension_spinboxes["B"].value() == 0.3
    assert panel._dimension_spinboxes["tw"].value() == 0.01
    assert panel._dimension_spinboxes["tf"].value() == 0.015
    assert panel._property_spinboxes["area"].value() == 0.0117
    assert panel._property_badges["area"].text() == "DB"
    assert panel._property_badges["Iy"].text() == "DB"


def test_editing_a_database_dimension_demotes_the_section_to_custom() -> None:
    """DB 값을 수정하면 CUSTOM 전환."""
    panel = _panel()
    _select_h_section(panel)
    assert panel._property_badges["area"].text() == "DB"

    panel._dimension_spinboxes["H"].setReadOnly(False)
    panel._dimension_spinboxes["H"].setValue(0.35)

    assert panel._property_badges["area"].text() == "CUSTOM"
    assert panel.current_application_kwargs()["source"] == "custom"
    assert panel.current_application_kwargs()["section_id"] is None
    # And the properties must actually have been recomputed for the new H,
    # not left stuck at the original DB numbers.
    assert panel._property_spinboxes["area"].value() != 0.0117


def test_reset_to_db_restores_the_original_designations_values() -> None:
    """Reset to DB 작동."""
    panel = _panel()
    _select_h_section(panel)
    panel._dimension_spinboxes["H"].setReadOnly(False)
    panel._dimension_spinboxes["H"].setValue(0.35)
    assert panel._property_badges["area"].text() == "CUSTOM"

    panel._reset_to_db()

    assert panel._dimension_spinboxes["H"].value() == 0.3
    assert panel._property_spinboxes["area"].value() == 0.0117
    assert panel._property_badges["area"].text() == "DB"
    assert panel.current_application_kwargs()["source"] == "database"
    assert panel.current_application_kwargs()["section_id"] == "SEC-H-300X300X10X15"


def test_section_and_material_combine_into_one_application_payload() -> None:
    """Section + Material 조합: H-300x300x10x15 + SM355."""
    panel = _panel()
    _select_h_section(panel)
    category_index = panel.material_category_combo.findText("Structural Steel")
    panel.material_category_combo.setCurrentIndex(category_index)
    grade_index = panel.material_grade_combo.findText("SM355")
    panel.material_grade_combo.setCurrentIndex(grade_index)

    kwargs = panel.current_application_kwargs()

    assert kwargs["section_id"] == "SEC-H-300X300X10X15"
    assert kwargs["material_id"] == "STL-SM355"
    assert kwargs["material_category"] == "Structural Steel"
    assert kwargs["material_grade"] == "SM355"
    assert kwargs["elastic"] > 0.0


def test_shear_modulus_display_tracks_e_and_poisson_ratio() -> None:
    """G = E / (2*(1+v)), using canvas_property_application.DEFAULT_POISSON_
    RATIO - the same fallback apply_full_section_to_selection uses when no
    shear_modulus is given - so a member solved with this panel's untouched
    default v matches one solved with no v supplied at all."""
    panel = _panel()
    # A freshly constructed panel already has some default Database material
    # selected (same as material_e/material_unit_weight/material_fy), so its
    # Poisson's ratio starts at whatever that material's own DB value is, not
    # necessarily DEFAULT_POISSON_RATIO - set it explicitly to isolate what
    # this test actually checks (the formula, not DB selection defaults).
    panel.material_poisson_ratio.setValue(DEFAULT_POISSON_RATIO)
    panel.material_e.setValue(200_000.0)
    assert float(panel.material_shear_modulus_display.text()) == pytest.approx(
        200_000.0 / (2.0 * (1.0 + DEFAULT_POISSON_RATIO))
    )

    panel.material_poisson_ratio.setValue(0.2)
    assert float(panel.material_shear_modulus_display.text()) == pytest.approx(200_000.0 / 2.4)


def test_selecting_a_database_material_fills_in_its_poisson_ratio() -> None:
    panel = _panel()
    category_index = panel.material_category_combo.findText("Structural Steel")
    panel.material_category_combo.setCurrentIndex(category_index)
    grade_index = panel.material_grade_combo.findText("SM355")
    panel.material_grade_combo.setCurrentIndex(grade_index)

    material = panel._database.get_material("STL-SM355")
    assert material.poisson_ratio is not None
    assert panel.material_poisson_ratio.value() == pytest.approx(material.poisson_ratio)


def test_current_application_kwargs_shear_modulus_matches_the_displayed_value() -> None:
    panel = _panel()
    panel.material_e.setValue(200_000.0)
    panel.material_poisson_ratio.setValue(0.2)

    kwargs = panel.current_application_kwargs()

    assert kwargs["shear_modulus"] == pytest.approx(200_000.0 / 2.4)


def test_reselecting_a_member_restores_its_non_default_poisson_ratio() -> None:
    """v = E/(2G) - 1 reversed from stored E/G must recover whatever v the
    member was actually applied with - not silently fall back to 0.3 just
    because a Database material's own default differs from it (SM355's own
    v could be anything; this member was applied with 0.2 regardless)."""
    panel = _panel()
    panel.material_e.setValue(200_000.0)
    panel.material_poisson_ratio.setValue(0.2)
    kwargs = panel.current_application_kwargs()
    assert kwargs["shear_modulus"] == pytest.approx(200_000.0 / 2.4)

    element = Element(
        tag=1,
        node_i=1,
        node_j=2,
        element_type="elasticBeamColumn",
        properties={
            "E": kwargs["elastic"],
            "G": kwargs["shear_modulus"],
            "A": kwargs["area"],
            "I": kwargs["iy"],
            "Iz": kwargs["iz"],
            "J": kwargs["j"],
            "density": kwargs["density"],
            "section_shape": kwargs["shape"],
            "section_source": kwargs["source"],
        },
    )

    fresh_panel = _panel()
    fresh_panel.load_from_element(element)

    assert fresh_panel.material_poisson_ratio.value() == pytest.approx(0.2)


def test_reselecting_a_member_restores_the_panel_from_its_stored_properties() -> None:
    """저장 후 부재 재선택 시 값 유지: an element carrying a previously-applied
    Database H-section + material is re-selected (the panel is rebuilt from
    element.properties, the same round trip a save/reopen would exercise
    since Element.properties is exactly what gets serialized)."""
    panel = _panel()
    _select_h_section(panel)
    category_index = panel.material_category_combo.findText("Structural Steel")
    panel.material_category_combo.setCurrentIndex(category_index)
    grade_index = panel.material_grade_combo.findText("SM355")
    panel.material_grade_combo.setCurrentIndex(grade_index)
    kwargs = panel.current_application_kwargs()

    element = Element(
        tag=1,
        node_i=1,
        node_j=2,
        element_type="elasticBeamColumn",
        properties={
            "E": kwargs["elastic"],
            "A": kwargs["area"],
            "I": kwargs["iy"],
            "Iz": kwargs["iz"],
            "J": kwargs["j"],
            "density": kwargs["density"],
            "section_shape": kwargs["shape"],
            "section_source": kwargs["source"],
            "section_id": kwargs["section_id"],
            "material_id": kwargs["material_id"],
            "material_category": kwargs["material_category"],
            "material_grade": kwargs["material_grade"],
            **{f"dim_{key}": value for key, value in kwargs["dimensions"].items()},
        },
    )

    fresh_panel = _panel()
    fresh_panel.load_from_element(element)

    assert fresh_panel.shape_combo.currentText() == "H/I Section"
    assert fresh_panel.source_database.isChecked()
    assert fresh_panel._dimension_spinboxes["H"].value() == 0.3
    assert fresh_panel._property_spinboxes["area"].value() == 0.0117
    assert fresh_panel.material_grade_combo.currentText() == "SM355"


def test_reselecting_a_legacy_rectangle_only_member_falls_back_correctly() -> None:
    """A member set through the pre-existing (rectangle-only) apply path has
    no section_shape key at all - re-selecting it must still show its actual
    width/height/E/density, not a blank/default panel."""
    element = Element(
        tag=1,
        node_i=1,
        node_j=2,
        element_type="elasticBeamColumn",
        properties={"E": 200_000.0, "A": 0.15, "I": 0.003125, "width": 0.3, "height": 0.5, "density": 24.0},
    )
    panel = _panel()

    panel.load_from_element(element)

    assert panel.shape_combo.currentText() == "Rectangle"
    assert panel.source_custom.isChecked()
    assert panel._dimension_spinboxes["b"].value() == 0.3
    assert panel._dimension_spinboxes["h"].value() == 0.5
    assert panel.material_e.value() == 200_000.0
    assert panel.material_unit_weight.value() == 24.0


def test_user_defined_shape_has_no_database_source_available() -> None:
    """지원되지 않는 Section을 지원하는 것처럼 표시하지 않는다: User Defined has
    no Master DB records by construction, so Database must be disabled, not
    silently empty."""
    panel = _panel()
    panel.shape_combo.setCurrentText("User Defined")
    assert not panel.source_database.isEnabled()
    assert panel.source_custom.isChecked()


def test_unit_system_change_rescales_the_displayed_dimensions_not_the_underlying_value() -> None:
    panel = _panel()
    _select_h_section(panel)
    assert panel._dimension_spinboxes["H"].value() == 0.3  # meters

    panel.set_unit_system(UnitSystem(force="kN", length="mm"))

    assert panel._dimension_spinboxes["H"].value() == 300.0  # same physical H, now in mm
    kwargs = panel.current_application_kwargs()
    assert kwargs["dimensions"]["H"] == 300.0
