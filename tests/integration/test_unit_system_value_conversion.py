"""ModelingInterfacePage.set_unit_system triggers a real value conversion
(canvas.convert_units), not just a label relabel - a user reported that a
live unit toggle on an already-drawn model needs the numbers to keep their
physical meaning, not just wear a new unit string.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import NodalLoad, UnitSystem
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1280, 800)
    page.show()
    return page


def test_switching_units_rescales_node_coordinates_and_loads() -> None:
    page = _page()
    node = page.canvas._add_node_at((1.0, 2.0, 3.0))
    page.canvas.nodal_loads[node] = NodalLoad(node, (10.0, 0.0, 0.0, 0.0, 0.0, 5.0))

    page.set_unit_system(UnitSystem(force="N", length="mm"))

    converted_node = page.canvas.nodes[node]
    assert (converted_node.x, converted_node.y, converted_node.z) == pytest.approx((1000.0, 2000.0, 3000.0))
    load = page.canvas.nodal_loads[node]
    assert load.values[0] == pytest.approx(10_000.0)  # 10 kN -> 10000 N
    assert load.values[5] == pytest.approx(5_000_000.0)  # 5 kN*m -> 5e6 N*mm


def test_switching_units_and_back_round_trips_within_floating_point_noise() -> None:
    page = _page()
    node = page.canvas._add_node_at((1.5, 0.0, 0.0))

    page.set_unit_system(UnitSystem(force="N", length="mm"))
    page.set_unit_system(UnitSystem(force="kN", length="m"))

    assert page.canvas.nodes[node].x == pytest.approx(1.5)


def test_picking_the_same_unit_again_does_not_touch_stored_values() -> None:
    page = _page()
    node = page.canvas._add_node_at((1.0, 0.0, 0.0))
    undo_depth_before = len(page.canvas._undo_stack)

    page.set_unit_system(UnitSystem(force="kN", length="m"))

    assert page.canvas.nodes[node].x == 1.0
    assert len(page.canvas._undo_stack) == undo_depth_before


def test_loading_a_saved_project_does_not_double_convert_its_values() -> None:
    """A saved project's numbers are already expressed in its own saved
    unit system - load_project_dict must adopt that unit system directly
    rather than routing through set_unit_system() (which would treat the
    freshly-loaded page's still-default unit system as the "from" side and
    convert everything a second time)."""
    page = _page()
    node = page.canvas._add_node_at((1.0, 2.0, 3.0))
    page.set_unit_system(UnitSystem(force="N", length="mm"))
    saved = page.canvas.nodes[node]
    data = page.to_project_dict()

    fresh = _page()  # starts at the default kN/m unit system
    fresh.load_project_dict(data)

    assert fresh._unit_system == UnitSystem(force="N", length="mm")
    reloaded = fresh.canvas.nodes[node]
    assert (reloaded.x, reloaded.y, reloaded.z) == pytest.approx((saved.x, saved.y, saved.z))


def test_footer_length_unit_change_converts_existing_node() -> None:
    page = _page()
    node = page.canvas._add_node_at((0.0, 0.0, 5.0))

    page.unit_length.setCurrentText("mm")

    assert page.canvas.nodes[node].z == pytest.approx(5000.0)
    assert page._unit_system.length == "mm"


def test_create_node_coordinate_label_tracks_current_length_unit() -> None:
    page = _page()
    assert "[m]" in page.node_coordinate_label.text()

    page.set_unit_system(UnitSystem(force="kN", length="mm"))

    assert "[mm]" in page.node_coordinate_label.text()


def test_switching_length_unit_scales_authoring_spinboxes_and_work_planes() -> None:
    page = _page()
    page.new_plane_offset.setValue(3.0)
    page.node_dx.setValue(1.0)
    ground = page.canvas.work_plane
    page.canvas.add_level(3.0, "2F")

    page.set_unit_system(UnitSystem(force="N", length="mm"))

    assert page.new_plane_offset.value() == pytest.approx(3000.0)
    assert page.node_dx.value() == pytest.approx(1000.0)
    assert page.canvas.work_plane.offset == pytest.approx(ground.offset * 1000.0)
    assert any("3000" in page.plane_selector.itemText(i) for i in range(page.plane_selector.count()))


def test_new_node_after_unit_switch_uses_current_unit_numbers() -> None:
    """Fresh typed coordinates are raw numbers in the *current* unit - after
    switching to mm, typing 5 means 5 mm, not 5 m. Existing geometry that
    was 5 m becomes 5000 mm, so the two must not land on the same tag."""
    page = _page()
    old = page.canvas._add_node_at((0.0, 0.0, 5.0))
    page.set_unit_system(UnitSystem(force="kN", length="mm"))
    page.node_xy.setText("0, 0, 5")
    page._add_nodes_from_coordinates()

    assert page.canvas.nodes[old].z == pytest.approx(5000.0)
    new_tags = [tag for tag in page.canvas.nodes if tag != old]
    assert len(new_tags) == 1
    assert page.canvas.nodes[new_tags[0]].z == pytest.approx(5.0)
