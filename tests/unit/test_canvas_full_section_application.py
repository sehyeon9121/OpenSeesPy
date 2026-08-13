import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    return StaticsDrawingCanvas()


def test_apply_full_section_stores_a_database_h_section_and_material() -> None:
    canvas = _canvas()
    a = canvas.add_node(0.0, 0.0)
    b = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(a, b)
    canvas.selected_elements = {member}

    canvas.apply_full_section_to_selection(
        shape="H/I Section",
        source="database",
        dimensions={"H": 0.3, "B": 0.3, "tw": 0.01, "tf": 0.015},
        area=0.0117,
        iy=1.993275e-4,
        iz=6.75225e-5,
        j=7.65e-7,
        elastic=2.0e8,
        density=76.98,
        section_id="SEC-H-300X300X10X15",
        material_id="STL-SM355",
        material_category="Structural Steel",
        material_grade="SM355",
    )

    element = canvas.elements[member]
    assert element.properties["E"] == 2.0e8
    assert element.properties["A"] == 0.0117
    assert element.properties["I"] == 1.993275e-4
    assert element.properties["Iz"] == 6.75225e-5
    assert element.properties["J"] == 7.65e-7
    assert element.properties["section_shape"] == "H/I Section"
    assert element.properties["section_source"] == "database"
    assert element.properties["section_id"] == "SEC-H-300X300X10X15"
    assert element.properties["material_id"] == "STL-SM355"
    assert element.properties["dim_H"] == 0.3
    assert element.properties["dim_tw"] == 0.01
    # Only a Rectangle gets width/height (the legacy preview widget's keys).
    assert "width" not in element.properties
    assert "height" not in element.properties


def test_apply_full_section_clears_stale_dimension_keys_on_shape_change() -> None:
    """Switching a member from an H-section to a plain Rectangle must not
    leave tw/tf lingering under their dim_ keys, and must not leave the old
    section_id/material_id pointing at a section this member no longer has."""
    canvas = _canvas()
    a = canvas.add_node(0.0, 0.0)
    b = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(a, b)
    canvas.selected_elements = {member}
    canvas.apply_full_section_to_selection(
        shape="H/I Section",
        source="database",
        dimensions={"H": 0.3, "B": 0.3, "tw": 0.01, "tf": 0.015},
        area=0.0117,
        iy=1.993275e-4,
        iz=6.75225e-5,
        j=7.65e-7,
        elastic=2.0e8,
        section_id="SEC-H-300X300X10X15",
    )

    canvas.apply_full_section_to_selection(
        shape="Rectangle",
        source="custom",
        dimensions={"b": 0.3, "h": 0.5},
        area=0.15,
        iy=3.125e-3,
        iz=1.125e-3,
        j=2.8e-3,
        elastic=2.5e7,
    )

    element = canvas.elements[member]
    assert element.properties["section_shape"] == "Rectangle"
    assert element.properties["width"] == 0.3
    assert element.properties["height"] == 0.5
    assert "dim_H" not in element.properties
    assert "dim_tw" not in element.properties
    assert "section_id" not in element.properties
    assert "material_id" not in element.properties


def test_apply_full_section_does_nothing_without_a_selection() -> None:
    canvas = _canvas()
    a = canvas.add_node(0.0, 0.0)
    b = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(a, b)
    canvas.selected_elements = set()

    canvas.apply_full_section_to_selection(
        shape="Rectangle",
        source="custom",
        dimensions={"b": 0.3, "h": 0.5},
        area=0.15,
        iy=3.125e-3,
        iz=1.125e-3,
        j=2.8e-3,
        elastic=2.5e7,
    )

    assert canvas.elements[member].properties == {}


def test_apply_section_to_selection_legacy_path_still_works_unchanged() -> None:
    """Regression: the pre-existing rectangle-only entry point must be
    completely untouched by the new general one."""
    canvas = _canvas()
    a = canvas.add_node(0.0, 0.0)
    b = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(a, b)
    canvas.selected_elements = {member}

    canvas.apply_section_to_selection(width=0.3, height=0.5, elastic=200_000.0, density=10.0)

    element = canvas.elements[member]
    assert element.properties["A"] == 0.15
    assert element.properties["I"] == 0.3 * 0.5**3 / 12.0
    assert element.properties["width"] == 0.3
    assert element.properties["height"] == 0.5
    assert "section_shape" not in element.properties
