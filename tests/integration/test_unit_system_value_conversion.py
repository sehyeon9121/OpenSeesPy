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
