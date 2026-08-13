"""SelectionStatusPanel: what it shows for empty/node/member selections, read
straight from a bare ``StaticsDrawingCanvas`` (no full ``ModelingInterfacePage``
needed here) - the panel-level items from the Selection Status inspector's
test list. Full apply-flow (Pending/Applied through the real page,
splitter, project save/load) is covered separately in
``tests/integration/test_statics_modeling_page.py``.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from openframe.core.domain import DEFAULT_UNIT_SYSTEM
from openframe.features.model.presentation.selection_status_panel import SelectionStatusPanel
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _panel() -> SelectionStatusPanel:
    QApplication.instance() or QApplication([])
    panel = SelectionStatusPanel()
    panel.show()
    return panel


def _canvas() -> StaticsDrawingCanvas:
    return StaticsDrawingCanvas()


def test_empty_selection_shows_the_guidance_text() -> None:
    """1. 선택 대상이 없을 때 빈 상태."""
    panel = _panel()
    canvas = _canvas()

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    hints = panel.findChildren(QLabel, "setupSectionHint")
    assert any("선택된 대상이 없습니다" in label.text() for label in hints)


def test_rectangle_member_shows_its_actually_stored_values() -> None:
    """2. Rectangle 부재의 실제 저장값 표시 (legacy width/height/E/density path)."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(n1, n2)
    canvas.selected_elements = {member}
    canvas.apply_section_to_selection(width=0.3, height=0.5, elastic=200_000.0, density=24.0)

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    all_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "Rectangle" in all_text
    assert "0.3" in all_text  # width -> dim b
    assert "0.5" in all_text  # height -> dim h
    assert "200000" in all_text  # E
    assert "24" in all_text  # density / unit weight


def test_db_h_section_shows_designation_and_material() -> None:
    """3. DB H형강의 단면·재료 정보 표시."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(n1, n2)
    canvas.selected_elements = {member}
    canvas.apply_full_section_to_selection(
        shape="H/I Section",
        source="database",
        dimensions={"H": 0.3, "B": 0.3, "tw": 0.01, "tf": 0.015},
        area=0.0117,
        iy=0.0001993275,
        iz=0.0000675225,
        j=0.000000765,
        elastic=200_000.0,
        density=77.0,
        section_id="SEC-H-300X300X10X15",
        material_id="STL-SM355",
        material_category="Structural Steel",
        material_grade="SM355",
    )

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    all_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "H/I Section" in all_text
    assert "H-300x300x10x15" in all_text  # designation resolved from section_id
    assert "Structural Steel" in all_text
    assert "SM355" in all_text
    badges = panel.findChildren(QLabel, "selectionStatusBadge")
    assert any(badge.text() == "DB" for badge in badges)


def test_custom_section_shows_custom_badges() -> None:
    """4. Custom 단면 상태 표시."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(n1, n2)
    canvas.selected_elements = {member}
    canvas.apply_full_section_to_selection(
        shape="Rectangle",
        source="custom",
        dimensions={"b": 0.3, "h": 0.5},
        area=0.15,
        iy=0.003125,
        iz=0.001125,
        j=0.001,
        elastic=200_000.0,
        density=0.0,
    )

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    badges = panel.findChildren(QLabel, "selectionStatusBadge")
    assert any(badge.text() == "CUSTOM" for badge in badges)
    assert not any(badge.text() == "DB" for badge in badges)


def test_multiple_members_with_identical_section_show_the_common_value() -> None:
    """9. 여러 부재 공통값 표시."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    n3 = canvas.add_node(4.0, 3.0)
    m1 = canvas.add_member(n1, n2)
    m2 = canvas.add_member(n2, n3)
    canvas.selected_elements = {m1, m2}
    canvas.apply_section_to_selection(width=0.3, height=0.5, elastic=200_000.0, density=24.0)

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    all_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "2 MEMBERS SELECTED" in all_text
    assert "Mixed" not in all_text


def test_multiple_members_with_different_section_show_mixed() -> None:
    """10. 서로 다른 값은 Mixed."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    n3 = canvas.add_node(4.0, 3.0)
    m1 = canvas.add_member(n1, n2)
    m2 = canvas.add_member(n2, n3)
    canvas.selected_elements = {m1}
    canvas.apply_section_to_selection(width=0.3, height=0.5, elastic=200_000.0, density=24.0)
    canvas.selected_elements = {m2}
    canvas.apply_section_to_selection(width=0.4, height=0.6, elastic=210_000.0, density=25.0)
    canvas.selected_elements = {m1, m2}

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    all_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "Mixed" in all_text


def test_single_node_shows_coordinates_and_connected_members() -> None:
    """11. 노드 정보 표시."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(1.5, 2.5)
    n2 = canvas.add_node(4.0, 0.0)
    canvas.add_member(n1, n2)
    canvas.selected_nodes = {n1}

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    all_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert f"N{n1}" in all_text
    assert "1.5" in all_text
    assert "2.5" in all_text


def test_node_with_support_shows_restrained_and_free_dof() -> None:
    """12. 지점조건 표시."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    canvas.add_member(n1, n2)
    canvas.set_support(n1, (True, True, False))
    canvas.selected_nodes = {n1}

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    all_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "Pinned" in all_text
    assert "Ux" in all_text and "Uy" in all_text and "Rz" in all_text


def test_node_with_load_shows_load_details() -> None:
    """13. 하중 정보 표시."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    canvas.add_member(n1, n2)
    canvas.set_nodal_load(n1, (10.0, -5.0, 2.0))
    canvas.selected_nodes = {n1}

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    all_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "Nodal Load" in all_text
    assert "Fx" in all_text
    assert "10" in all_text


def test_node_selection_has_no_status_badge() -> None:
    """Node views never show Applied/Pending - that concept only applies to
    a member's section+material editor state."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    canvas.add_member(n1, n2)
    canvas.selected_nodes = {n1}

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    assert panel._status_badges == []


def test_unknown_field_missing_from_a_legacy_model_shows_a_dash() -> None:
    """9-item requirement: fields absent from an older model must not error
    and must show "-", never an invented default."""
    panel = _panel()
    canvas = _canvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(4.0, 0.0)
    member = canvas.add_member(n1, n2)
    canvas.selected_elements = {member}

    panel.refresh(canvas, pending_edit=None, unit_system=DEFAULT_UNIT_SYSTEM)

    all_text = " ".join(label.text() for label in panel.findChildren(QLabel))
    assert "—" in all_text
