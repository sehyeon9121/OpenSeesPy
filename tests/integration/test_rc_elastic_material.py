"""RC catalog selection through assignment, persistence and elastic analysis."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisStatus, NodalLoad, UnitSystem
from openframe.features.analysis.statics import MaterialFreeStaticsSolver
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage
from openframe.features.model.presentation.section_material_panel import SectionMaterialPanel
from openframe.features.model.presentation.selection_status_panel import SelectionStatusPanel
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _rc_panel(panel=None):
    QApplication.instance() or QApplication([])
    panel = panel or SectionMaterialPanel()
    panel.material_category_combo.setCurrentText("RC")
    panel.material_grade_combo.setCurrentIndex(panel.material_grade_combo.findData("CONC-C30"))
    panel.rc_rebar_combo.setCurrentIndex(panel.rc_rebar_combo.findData("REBAR-SD500"))
    panel.rc_stirrup_combo.setCurrentIndex(panel.rc_stirrup_combo.findData("REBAR-SD400"))
    panel.shape_combo.setCurrentText("Rectangle")
    panel._dimension_spinboxes["b"].setValue(0.3)
    panel._dimension_spinboxes["h"].setValue(0.5)
    return panel


@pytest.mark.parametrize("ndm", [2, 3])
def test_rc_database_material_reaches_elastic_solver_and_survives_reload(ndm):
    panel = _rc_panel()
    canvas = StaticsDrawingCanvas()
    if ndm == 3:
        canvas.enter_3d_mode()
    start = canvas._add_node_at((0.0, 0.0, 0.0))
    end = canvas._add_node_at((4.0, 0.0, 0.0))
    tag = canvas.add_member(start, end)
    canvas.selected_elements = {tag}
    kwargs = panel.current_application_kwargs()
    # Even a stale steel Fy passed by a caller must not become an RC hinge.
    kwargs["fy"] = 500000.0
    canvas.apply_full_section_to_selection(**kwargs)
    canvas.set_support(start, (True,) * (6 if ndm == 3 else 3))
    canvas.nodal_loads[end] = NodalLoad(end, (10.0,) + (0.0,) * (5 if ndm == 3 else 2))
    canvas.include_self_weight = False
    restored = StaticsDrawingCanvas()
    restored.load_dict(json.loads(json.dumps(canvas.to_dict())))
    props = restored.elements[tag].properties
    assert props["rc_fck_mpa"] == 30
    assert props["rc_rebar_fy_mpa"] == 500
    assert props["rc_stirrup_fy_mpa"] == 400
    assert props["rc_rebar_status"] == "PENDING"
    assert "Fy" not in props
    assert props["G"] == pytest.approx(props["E"] / (2 * (1 + panel.material_poisson_ratio.value())))

    panel.load_from_element(restored.elements[tag])
    assert panel.material_category_combo.currentText() == "RC"
    assert panel.rc_rebar_combo.currentData() == "REBAR-SD500"
    assert panel.rc_stirrup_combo.currentData() == "REBAR-SD400"
    inspector = SelectionStatusPanel()
    assert inspector._is_applied(restored.elements[tag], panel.current_edit_kwargs())
    panel.rc_rebar_combo.setCurrentIndex(panel.rc_rebar_combo.findData("REBAR-SD400"))
    assert not inspector._is_applied(restored.elements[tag], panel.current_edit_kwargs())
    result = MaterialFreeStaticsSolver().solve(restored.build_model())
    assert result.status == AnalysisStatus.COMPLETED, result
    assert result.node_results[end].displacement[0] == pytest.approx(
        10.0 * 4.0 / (props["E"] * props["A"]), rel=1e-5
    )
    assert result.node_results[start].reaction[0] == pytest.approx(-10)


def test_rc_unit_conversion_keeps_catalog_strengths_in_mpa():
    panel = _rc_panel()
    before = panel.current_application_kwargs()
    panel.set_unit_system(UnitSystem(force="N", length="mm"))
    after = panel.current_application_kwargs()
    assert after["elastic"] == pytest.approx(before["elastic"] / 1000)
    assert after["rc_material"] == before["rc_material"]


@pytest.mark.parametrize("ndm", [2, 3])
def test_saved_rc_material_applies_to_new_members_and_project_library(ndm):
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=ndm == 3)
    panel = _rc_panel(page.section_material_panel)
    panel.material_name.setText("RC C30 SD500")
    panel.section_name.setText("RC 300x500")
    panel.material_save_button.click()
    panel.section_save_button.click()
    page.element_material_selector.setCurrentIndex(1)
    page.element_section_selector.setCurrentIndex(1)
    start = page.canvas._add_node_at((0.0, 0.0, 0.0))
    end = page.canvas._add_node_at((4.0, 0.0, 0.0))
    tag = page.canvas.add_member(start, end)
    page._apply_active_element_to_new_members({tag})
    props = page.canvas.elements[tag].properties
    assert props["rc_rebar_id"] == "REBAR-SD500"
    assert props["G"] == pytest.approx(props["E"] / (2 * (1 + panel.material_poisson_ratio.value())))
    saved = json.loads(json.dumps(page.to_project_dict()))
    page.load_project_dict(saved)
    assert page._user_materials[0]["rc_material"]["rc_fck_mpa"] == 30
    assert page.canvas.elements[tag].properties["rc_rebar_id"] == "REBAR-SD500"
    panel.load_from_element(page.canvas.elements[tag])
    assert panel.current_application_kwargs()["material_id"] == "MAT-001"

    # Section-only assignment keeps RC identity; a steel material replaces it.
    page._apply_property_drop("section", "SEC-001", tag)
    assert page.canvas.elements[tag].properties["rc_fck_mpa"] == 30
    page._save_user_material({"name": "Steel", "elastic": 2e8, "fy": 355000.0,
                              "category": "Structural Steel", "grade": "SM355"})
    page._apply_property_drop("material", "MAT-002", tag)
    props = page.canvas.elements[tag].properties
    assert not any(k.startswith("rc_") for k in props)
    assert props["Fy"] == 355000.0


def test_rc_wall_uses_concrete_poisson_and_keeps_material_on_reload():
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    panel = _rc_panel(page.section_material_panel)
    panel.material_name.setText("RC wall")
    panel.material_save_button.click()
    corners = tuple(page.canvas._add_node_at(p) for p in
                    [(0, 0, 0), (2, 0, 0), (2, 0, 3), (0, 0, 3)])
    page._set_active_plate_pen(page._user_materials[0], {"thickness_mm": 200},
                               material_id="MAT-001", thickness_id="THK-001")
    wall = page.canvas.add_wall(corners)
    assert wall is not None
    assert wall.poisson_ratio == pytest.approx(panel.material_poisson_ratio.value())
    restored = StaticsDrawingCanvas()
    restored.load_dict(json.loads(json.dumps(page.canvas.to_dict())))
    assert restored.walls[wall.tag].rc_material == wall.rc_material
    assert restored.walls[wall.tag].elastic_modulus == wall.elastic_modulus
