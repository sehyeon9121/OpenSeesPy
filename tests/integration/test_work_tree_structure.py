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
