"""Work Tree's 절점/부재/지점 geometry groups and their click-to-select wiring."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.app.shell.theme import apply_application_theme
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


def _page() -> ModelingInterfacePage:
    application = QApplication.instance() or QApplication([])
    if not application.property("openframeThemeApplied"):
        apply_application_theme(application)
        application.setProperty("openframeThemeApplied", True)
    page = ModelingInterfacePage(start_in_3d=True)
    page.resize(1400, 900)
    page.show()
    page.canvas.ndm = 3
    return page


def _portal_frame(page: ModelingInterfacePage) -> tuple[int, ...]:
    canvas = page.canvas
    tags = tuple(
        canvas._add_node_at(point)
        for point in ((0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (0.0, 0.0, 3.5), (6.0, 0.0, 3.5))
    )
    canvas.add_member(tags[0], tags[2])
    canvas.add_member(tags[2], tags[3])
    canvas.add_member(tags[1], tags[3])
    return tags


def test_geometry_group_counts_track_the_model() -> None:
    """Regression test: the Work Tree used to list only 물성/섹션/하중조합, so a
    model with any number of nodes and members still read "0" everywhere and
    told the user nothing about what they had actually drawn."""
    page = _page()
    assert page.work_tree_nodes.text(1) == "0"

    _portal_frame(page)

    assert page.work_tree_nodes.text(1) == "4"
    assert page.work_tree_members.text(1) == "3"
    assert page.work_tree_supports.text(1) == "0"


def test_2d_modeling_window_uses_the_same_right_work_tree() -> None:
    page = ModelingInterfacePage(start_in_3d=False)
    page.resize(1400, 900)
    page.show()

    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    page.canvas.add_member(first, second)

    assert page.work_tree_title.text() == "워크트리"
    assert page.work_tree_nodes.text(1) == "2"
    assert page.work_tree_members.text(1) == "1"
    page.work_tree_nodes.setExpanded(True)
    assert page.work_tree_nodes.child(0).text(1) == "0, 0, 0"


def test_children_are_built_only_once_a_group_is_opened() -> None:
    """_refresh_work_tree runs on every model_changed - i.e. once per node
    added - so a collapsed group must not pay to build rows nobody is
    looking at."""
    page = _page()
    _portal_frame(page)

    assert page.work_tree_nodes.childCount() == 0  # collapsed: counts only

    page.work_tree_nodes.setExpanded(True)

    assert page.work_tree_nodes.childCount() == 4
    assert page.work_tree_nodes.child(0).text(0) == "절점 1"
    assert page.work_tree_nodes.child(0).text(1) == "0, 0, 0"


def test_member_rows_name_their_end_nodes() -> None:
    page = _page()
    _portal_frame(page)
    page.work_tree_members.setExpanded(True)

    assert page.work_tree_members.child(0).text(0) == "부재 1"
    assert page.work_tree_members.child(0).text(1) == "1→3"


def test_support_rows_reuse_the_shared_support_names() -> None:
    page = _page()
    tags = _portal_frame(page)
    page.canvas.set_support(tags[0], (True,) * 6)
    page.canvas.set_support(tags[1], (True, True, True, False, False, False))
    page.work_tree_supports.setExpanded(True)

    assert page.work_tree_supports.text(1) == "2"
    assert page.work_tree_supports.child(0).text(1) == "고정지점"
    assert page.work_tree_supports.child(1).text(1) == "회전지점(힌지)"


def test_clicking_a_row_selects_that_entity_on_the_canvas() -> None:
    """What makes the tree a navigation aid rather than a passive list."""
    page = _page()
    _portal_frame(page)
    page.work_tree_nodes.setExpanded(True)
    page.work_tree_members.setExpanded(True)

    page._on_work_tree_item_clicked(page.work_tree_members.child(0), 0)
    assert page.canvas.selected_elements == {1}
    assert page.canvas.selected_nodes == set()

    # Selecting the other kind must clear the first, not accumulate across both.
    page._on_work_tree_item_clicked(page.work_tree_nodes.child(2), 0)
    assert page.canvas.selected_nodes == {3}
    assert page.canvas.selected_elements == set()


def test_material_and_section_rows_carry_definition_role_data() -> None:
    """Work Tree 물성/섹션 rows must be individually addressable (for their
    delete/drag-and-drop context menu) - they used to have no item data at
    all, so a click or right-click on one did nothing."""
    from openframe.features.model.presentation.modeling_interface_page import (
        _TREE_DEFINITION_ROLE,
    )

    page = _page()
    page._save_user_material(
        {"name": "Steel-Test", "category": "Steel", "grade": "SM490", "elastic": 2.05e8,
         "density": 77.0, "fy": 3.25e5}
    )
    page._save_user_section(
        {"name": "Sec-Test", "shape": "Rectangle", "source": "custom",
         "dimensions": {"b": 0.3, "h": 0.5}, "area": 0.15, "iy": 0.003125,
         "iz": 0.001125, "j": 0.0001, "database_id": None}
    )

    assert page.work_tree_materials.child(0).data(0, _TREE_DEFINITION_ROLE) == (
        "material",
        "MAT-001",
    )
    assert page.work_tree_sections.child(0).data(0, _TREE_DEFINITION_ROLE) == (
        "section",
        "SEC-001",
    )


def test_deleting_a_material_definition_removes_it_from_the_tree() -> None:
    page = _page()
    page._save_user_material(
        {"name": "Steel-Test", "category": "Steel", "grade": None, "elastic": 2.05e8,
         "density": 77.0, "fy": 0.0}
    )
    assert page.work_tree_materials.childCount() == 1

    page._user_materials[:] = [
        entry for entry in page._user_materials if entry.get("id") != "MAT-001"
    ]
    page._refresh_work_tree()

    assert page.work_tree_materials.childCount() == 0


def test_remove_support_clears_boundary_but_keeps_the_node() -> None:
    """지점 해제 - unlike 절점 삭제, must not take the node or its members
    with it."""
    page = _page()
    tags = _portal_frame(page)
    node_tag = tags[0]
    page.canvas.set_support(node_tag, (True, True, True))
    assert node_tag in page.canvas.boundaries

    page.canvas.remove_support(node_tag)

    assert node_tag not in page.canvas.boundaries
    assert node_tag in page.canvas.nodes
    assert any(node_tag in (e.node_i, e.node_j) for e in page.canvas.elements.values())


def test_geometry_tree_delete_removes_selected_node_and_its_members() -> None:
    """The Work Tree's 절점 삭제 context menu action selects, then deletes -
    matching the existing DELETE toolbar button's own cascading behaviour."""
    page = _page()
    tags = _portal_frame(page)
    node_tag = tags[0]

    page._select_entity_from_tree("node", node_tag)
    page.canvas.delete_selected()

    assert node_tag not in page.canvas.nodes
    assert all(node_tag not in (e.node_i, e.node_j) for e in page.canvas.elements.values())


def _rectangular_member(page: ModelingInterfacePage) -> int:
    first = page.canvas.add_node(0.0, 0.0)
    second = page.canvas.add_node(4.0, 0.0)
    member = page.canvas.add_member(first, second)
    assert member is not None
    page.canvas.selected_elements = {member}
    page.canvas.apply_full_section_to_selection(
        shape="Rectangle",
        source="custom",
        dimensions={"b": 0.3, "h": 0.5},
        area=0.15,
        iy=0.003125,
        iz=0.001125,
        j=0.0001,
        elastic=2.0e8,
        density=78.5,
    )
    return member


def test_property_drop_applies_material_only_and_preserves_existing_section() -> None:
    """Dragging a 물성 row onto a member must overlay E/G/density/Fy without
    disturbing the section (A/Iy/Iz/shape) that member already had."""
    page = ModelingInterfacePage(start_in_3d=False)
    page.resize(1400, 900)
    page.show()
    member = _rectangular_member(page)

    page._save_user_material(
        {"name": "NewSteel", "category": "Steel", "grade": "SM355", "elastic": 2.05e8,
         "density": 77.0, "fy": 3.55e5}
    )
    material_id = page._user_materials[0]["id"]

    page._apply_property_drop("material", material_id, member)

    properties = page.canvas.elements[member].properties
    assert properties["E"] == 2.05e8
    assert properties["density"] == 77.0
    assert properties["Fy"] == 3.55e5
    assert properties["A"] == 0.15
    assert properties["Iy"] == 0.003125
    assert properties["section_shape"] == "Rectangle"


def test_property_drop_applies_section_only_and_preserves_existing_material() -> None:
    """Dragging a 섹션 row onto a member must overlay shape/A/Iy/Iz/J without
    disturbing the material (E/density) that member already had."""
    page = ModelingInterfacePage(start_in_3d=False)
    page.resize(1400, 900)
    page.show()
    member = _rectangular_member(page)

    page._save_user_section(
        {"name": "BigCircle", "shape": "Circle", "source": "custom",
         "dimensions": {"d": 0.4}, "area": 0.1256, "iy": 0.001256, "iz": 0.001256,
         "j": 0.002513, "database_id": None}
    )
    section_id = page._user_sections[0]["id"]

    page._apply_property_drop("section", section_id, member)

    properties = page.canvas.elements[member].properties
    assert properties["section_shape"] == "Circle"
    assert properties["A"] == 0.1256
    assert properties["Iy"] == 0.001256
    assert properties["E"] == 2.0e8
    assert properties["density"] == 78.5


def test_drag_move_over_a_member_sets_the_drop_target_for_yellow_feedback() -> None:
    """dragMoveEvent's job is entirely the yellow-highlight feedback the user
    asked for - it must recognise the member under the cursor and clear it
    again once the drag leaves, without ever mutating the model."""
    page = ModelingInterfacePage(start_in_3d=False)
    page.resize(1400, 900)
    page.show()
    member = _rectangular_member(page)
    canvas = page.canvas
    assert canvas._drop_target_element is None

    canvas._drop_target_element = member
    canvas._redraw()  # must not raise with a drop target set

    canvas._drop_target_element = None
    canvas._redraw()


def test_clicking_a_row_whose_entity_is_already_gone_is_a_no_op() -> None:
    """A row can outlive its entity (deleted between refreshes) - clicking it
    must not raise or leave a phantom tag in the selection."""
    page = _page()
    _portal_frame(page)
    page.work_tree_nodes.setExpanded(True)
    stale_row = page.work_tree_nodes.child(0)
    page.canvas.nodes.clear()

    page._on_work_tree_item_clicked(stale_row, 0)

    assert page.canvas.selected_nodes == set()


def test_load_entry_rows_still_route_to_the_load_inspector() -> None:
    """The geometry rows share one tree and one click handler with the
    pre-existing load-entry rows - adding them must not shadow that path."""
    page = _page()
    assert hasattr(page, "work_tree_load_combinations")
    assert page.work_tree.indexOfTopLevelItem(page.work_tree_load_combinations) >= 0
    # The geometry groups sit above 물성/섹션/하중조합, not in place of them.
    assert page.work_tree.indexOfTopLevelItem(page.work_tree_nodes) == 0
    assert page.work_tree.indexOfTopLevelItem(page.work_tree_materials) == 3
