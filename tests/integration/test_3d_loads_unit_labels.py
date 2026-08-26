"""Unit labels on the 3D Loads tab's case-based forms (nodal/member/floor) -
a user reported that changing the app's unit system left the Floor Load
Type Manager's magnitude column showing a stale "kN/m²" forever. Auditing
the rest of the Loads tab turned up the same gap on every numeric field
there (they simply never showed a unit at all before this fix), so this
file covers the whole tab, not just the one dialog.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import UnitSystem
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page() -> ModelingInterfacePage:
    QApplication.instance() or QApplication([])
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1400, 900)
    page.show()
    page._activate_load_tool()
    return page


def test_nodal_force_and_moment_labels_show_the_default_units() -> None:
    page = _page()
    assert page.load3d_nodal_field_labels["fx"].text() == "Fx (kN)"
    assert page.load3d_nodal_field_labels["mz"].text() == "Mz (kN·m)"


def test_floor_magnitude_label_shows_stress_units() -> None:
    page = _page()
    assert page.load3d_floor_magnitude_label.text() == "크기 (직접 입력) (kN/m²)"


def test_member_uniform_subtype_shows_force_per_length() -> None:
    page = _page()
    index = page.load3d_member_subtype_combo.findData("member_uniform")
    page.load3d_member_subtype_combo.setCurrentIndex(index)

    assert page.load3d_member_start_value_label.text() == "시작값 (kN/m)"
    assert page.load3d_member_end_value_label.text() == "끝값 (kN/m)"


def test_member_point_subtype_shows_plain_force() -> None:
    page = _page()
    index = page.load3d_member_subtype_combo.findData("member_point")
    page.load3d_member_subtype_combo.setCurrentIndex(index)

    assert page.load3d_member_start_value_label.text() == "시작값 (kN)"


def test_member_moment_subtype_shows_moment_units() -> None:
    page = _page()
    index = page.load3d_member_subtype_combo.findData("member_moment")
    page.load3d_member_subtype_combo.setCurrentIndex(index)

    assert page.load3d_member_start_value_label.text() == "시작값 (kN·m)"


def test_changing_the_unit_system_updates_every_load3d_label() -> None:
    page = _page()
    uniform_index = page.load3d_member_subtype_combo.findData("member_uniform")
    page.load3d_member_subtype_combo.setCurrentIndex(uniform_index)

    page.set_unit_system(UnitSystem(force="N", length="mm"))

    assert page.load3d_nodal_field_labels["fx"].text() == "Fx (N)"
    assert page.load3d_nodal_field_labels["mz"].text() == "Mz (N·mm)"
    assert page.load3d_floor_magnitude_label.text() == "크기 (직접 입력) (N/mm²)"
    assert page.load3d_member_start_value_label.text().endswith("(N/mm)")


def test_floor_load_type_manager_button_opens_with_the_pages_current_units() -> None:
    from openframe.features.model.presentation.floor_load_type_manager_dialog import (
        FloorLoadTypeManagerDialog,
    )

    page = _page()
    page.set_unit_system(UnitSystem(force="kip", length="ft"))

    dialog = FloorLoadTypeManagerDialog(page.canvas, unit_system=page._unit_system, parent=page)

    assert dialog.magnitude_header.text() == "크기 (kip/ft²)"
