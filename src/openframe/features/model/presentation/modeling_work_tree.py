"""Work Tree / Selection Status inspector for ModelingInterfacePage.

Mixin, not a standalone widget: it reads ``self.canvas`` and the page-owned
``_user_materials`` / ``_user_sections`` lists. Split out of the page so a
command that only touches the tree does not have to load 3D picking or the
Loads tab. See ``canvas_work_planes.py`` for the same mixin pattern.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openframe.features.model.presentation.current_page_only_stack import _CurrentPageOnlyStack
from openframe.features.model.presentation.modeling_tree_roles import (
    _TREE_DEFINITION_ROLE,
    _TREE_ENTITY_ROLE,
    _LoadTreeBinding,
    _WorkTree,
)
from openframe.features.model.presentation.selection_status_panel import SelectionStatusPanel
from openframe.features.viewport.items.support_item import SUPPORT_NAMES


class _WorkTreeMixin:

    def _member_group_counts(self) -> dict[str, int]:
        """Columns vs. Beams, derived on the fly from geometry (a member
        whose two ends share the same x/y is vertical) rather than a stored
        field — the domain model has no "group" concept to persist yet, and
        this is the same classification the reference design's own mock
        implementation used."""
        counts = {"Columns": 0, "Beams": 0}
        for element in self.canvas.elements.values():
            start = self.canvas.nodes.get(element.node_i)
            end = self.canvas.nodes.get(element.node_j)
            if start is None or end is None:
                continue
            is_column = abs(start.x - end.x) < 1.0e-6 and abs(start.y - end.y) < 1.0e-6
            counts["Columns" if is_column else "Beams"] += 1
        return counts


    def _new_load_tree(self, object_name: str) -> QTreeWidget:
        """A load-entry browse tree wired the same way regardless of which
        panel (Work Tree vs. Load Inspector) hosts it - see
        ``_LoadTreeBinding``/``_refresh_load_tree``. Both trees' clicks route
        through ``_on_work_tree_item_clicked`` (kept under its original name
        - tests call it directly - even though it now also serves the
        Load Inspector tree; its body only ever reads ``item``, never
        ``self.work_tree``, so sharing it is safe)."""
        tree = _WorkTree()
        tree.setObjectName(object_name)
        tree.setHeaderHidden(True)
        tree.setColumnCount(2)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tree.setIndentation(15)
        tree.setRootIsDecorated(True)
        # Only a 물성/섹션 row (_WorkTree.startDrag) ever actually starts a
        # drag - see canvas_input_events.py's dragEnterEvent/dropEvent for
        # where it lands (드래그하여 부재에 적용).
        tree.setDragEnabled(True)
        tree.itemClicked.connect(self._on_work_tree_item_clicked)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(
            lambda position, t=tree: self._show_load_tree_context_menu(t, position)
        )
        return tree


    def _build_selection_panel(self) -> QScrollArea:
        """Shared MIDAS-style work tree plus selection status on the right - swapped
        for a Loads-only ``Load Inspector`` page while the Loads workbench
        tab is active (``_activate_workbench_tab``), via ``right_panel_stack``.

        Both the 2D and 3D modeling windows use this same inspector so their
        model navigation, entity selection, and load browsing stay consistent.
        """
        panel = QFrame()
        panel.setObjectName("modelingInspectorPanel")
        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        self.work_tree_title = QLabel("워크트리")
        self.work_tree_title.setObjectName("direct2DInspectorTitle")
        # Every widget in this panel except the tree is capped at its size
        # hint (Maximum). Marking only the tree as the stretchy one is not
        # enough on its own: with a mix of default Preferred policies the
        # spare height kept landing on whichever sibling came first - first
        # the status panel, then this one-line title, which ballooned to
        # ~500px - instead of on the tree. Capping the fixed-size siblings
        # leaves the tree as the only place the free height can go.
        self.work_tree_title.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        root.addWidget(self.work_tree_title)

        self.work_tree = self._new_load_tree("modelingWorkTree")
        # Geometry groups come first: until these existed the Work Tree listed
        # only 물성/섹션/하중조합, so a model with hundreds of nodes and members
        # showed "0 / 0 / 0" and the tree said nothing about what had actually
        # been drawn. Children are built lazily (see _refresh_structure_tree)
        # because _refresh_work_tree runs on every model_changed - i.e. once
        # per node added - and eagerly rebuilding thousands of rows there
        # would make drawing progressively slower.
        self.work_tree_nodes = QTreeWidgetItem(["절점", "0"])
        self.work_tree_members = QTreeWidgetItem(["부재", "0"])
        self.work_tree_supports = QTreeWidgetItem(["지점", "0"])
        self.work_tree_materials = QTreeWidgetItem(["물성", "0"])
        self.work_tree_sections = QTreeWidgetItem(["섹션", "0"])
        self.work_tree_load_combinations = QTreeWidgetItem(["하중조합", "0"])
        self.work_tree.addTopLevelItem(self.work_tree_nodes)
        self.work_tree.addTopLevelItem(self.work_tree_members)
        self.work_tree.addTopLevelItem(self.work_tree_supports)
        self.work_tree.addTopLevelItem(self.work_tree_materials)
        self.work_tree.addTopLevelItem(self.work_tree_sections)
        self.work_tree.addTopLevelItem(self.work_tree_load_combinations)
        # Populate a geometry group the moment it is opened - _refresh_
        # structure_tree only fills groups that are already expanded.
        self.work_tree.itemExpanded.connect(self._on_work_tree_item_expanded)
        # Load Case top-level items (one per canvas.load_cases entry) live in
        # this same tree, added/removed by _refresh_load_tree - see
        # canvas_load_entries.py.
        self._work_tree_case_items: dict[str, QTreeWidgetItem] = {}
        self._selected_load_id: int | None = None
        # Stretch factor, and no trailing addStretch: the panel is 330px wide
        # and as tall as the window, but every widget here used to be given
        # only its size hint while a trailing stretch swallowed the rest - so
        # the tree sat in a ~180px box, scrolling internally, above several
        # hundred pixels of empty panel. The tree is the part that grows with
        # the model, so it is the part that should absorb the free height;
        # the status cards below keep their natural size.
        root.addWidget(self.work_tree, 1)
        self.member_info_card = self._build_member_info_card()
        self.member_info_card.setVisible(False)
        self.member_info_card.setSizePolicy(  # content-sized, same as the title above
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        root.addWidget(self.member_info_card)
        self.selection_status_panel = SelectionStatusPanel()
        self.selection_status_panel.load_edit_requested.connect(self._edit_load_entry)
        self.selection_status_panel.load_reselect_requested.connect(self._reselect_load_entry_target)
        self.selection_status_panel.load_delete_requested.connect(self._delete_load_entry_from_status)
        # Sized to its cards, never beyond: SelectionStatusPanel ends its own
        # layout with an addStretch(1) (to keep its cards pinned to the top of
        # whatever height it is given), which also made it happily swallow the
        # panel's entire spare height - ~580px for ~100px of content, starving
        # the tree above it. Maximum caps it at its size hint so the free
        # height goes to the tree's stretch instead.
        self.selection_status_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        root.addWidget(self.selection_status_panel)
        # Keeps the cards packed at the top. Needed only because the tree
        # cannot currently absorb the panel's spare height on its own: the
        # theme caps QTreeWidget#modelingWorkTree at max-height 270px, from
        # when this tree held three fixed rows rather than the whole model.
        # Without a spare-space sink here Qt scatters the leftover evenly as
        # ~130px gaps between the title, tree and status cards. Once that cap
        # is lifted the tree's own stretch takes over and this just goes to
        # zero height.
        root.addStretch(0)

        inspector = QFrame()
        inspector.setObjectName("modelingInspectorPanel")
        inspector_root = QVBoxLayout(inspector)
        inspector_root.setContentsMargins(12, 12, 12, 12)
        inspector_root.setSpacing(10)
        inspector_title = QLabel("Load Inspector")
        inspector_title.setObjectName("direct2DInspectorTitle")
        inspector_root.addWidget(inspector_title)
        # Same Load Case/하중조합 browse tree as the Work Tree, minus the
        # unrelated 물성/섹션 top items - Loads-tab-only, so it stays focused
        # on what this tab actually edits (see plan's Load Inspector design
        # decision: this is why it is a tree, not just a passive status card
        # - Edit/Duplicate/Hide/Delete/Move via right-click must keep working
        # even though the general Work Tree is hidden while this tab is open).
        self.load_inspector_tree = self._new_load_tree("loadInspectorTree")
        self.load_inspector_combinations_item = QTreeWidgetItem(["하중조합", "0"])
        self.load_inspector_tree.addTopLevelItem(self.load_inspector_combinations_item)
        self._load_inspector_case_items: dict[str, QTreeWidgetItem] = {}
        inspector_root.addWidget(self.load_inspector_tree, 1)  # same reason as the Work Tree above
        self.load_inspector_status_panel = SelectionStatusPanel()
        self.load_inspector_status_panel.load_edit_requested.connect(self._edit_load_entry)
        self.load_inspector_status_panel.load_reselect_requested.connect(
            self._reselect_load_entry_target
        )
        self.load_inspector_status_panel.load_delete_requested.connect(
            self._delete_load_entry_from_status
        )
        self.load_inspector_status_panel.setSizePolicy(  # same reason as the Work Tree panel
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        inspector_root.addWidget(self.load_inspector_status_panel)

        self._load_tree_bindings: tuple[_LoadTreeBinding, ...] = (
            _LoadTreeBinding(self.work_tree, self.work_tree_load_combinations, self._work_tree_case_items),
            _LoadTreeBinding(
                self.load_inspector_tree,
                self.load_inspector_combinations_item,
                self._load_inspector_case_items,
            ),
        )
        self.canvas.load_state_changed.connect(self._refresh_load_tree)

        self.right_panel_stack = _CurrentPageOnlyStack()
        self.right_panel_pages = {
            "default": self.right_panel_stack.addWidget(panel),
            "load_inspector": self.right_panel_stack.addWidget(inspector),
        }

        scroll = QScrollArea()
        scroll.setObjectName("modelingSelectionInspector")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(330)
        scroll.setWidget(self.right_panel_stack)
        self._refresh_work_tree()
        self._refresh_load_tree()
        return scroll


    def _refresh_work_tree(self) -> None:
        if not hasattr(self, "work_tree_materials"):
            self._refresh_element_property_selectors()
            return
        self.work_tree_materials.takeChildren()
        for material in self._user_materials:
            try:
                elastic = float(material.get("elastic", 0.0))
            except (TypeError, ValueError):
                elastic = 0.0
            item = QTreeWidgetItem(
                [str(material.get("name", "사용자 물성")), str(material.get("id", ""))]
            )
            item.setToolTip(
                0,
                f"E = {elastic:g} {self._unit_system.stress}",
            )
            item.setData(0, _TREE_DEFINITION_ROLE, ("material", material.get("id")))
            self.work_tree_materials.addChild(item)
        self.work_tree_materials.setText(1, str(len(self._user_materials)))

        self.work_tree_sections.takeChildren()
        for section in self._user_sections:
            item = QTreeWidgetItem(
                [str(section.get("name", "사용자 섹션")), str(section.get("id", ""))]
            )
            item.setToolTip(0, str(section.get("shape", "")))
            item.setData(0, _TREE_DEFINITION_ROLE, ("section", section.get("id")))
            self.work_tree_sections.addChild(item)
        self.work_tree_sections.setText(1, str(len(self._user_sections)))
        self.work_tree_materials.setExpanded(True)
        self.work_tree_sections.setExpanded(True)
        self._refresh_structure_tree()
        self._refresh_element_property_selectors()


    #: Most rows a single Work Tree geometry group lists before it stops and
    #: shows a "…외 N개" summary row instead. A real building model runs to
    #: thousands of nodes; past a few hundred rows the tree stops being a
    #: navigation aid and just costs time to build and scroll.
    _WORK_TREE_CHILD_LIMIT = 300


    def _refresh_structure_tree(self) -> None:
        """Update the 절점/부재/지점 group counts, rebuilding the rows of
        whichever groups happen to be expanded.

        Counts are always current (they are just a label), but children are
        only materialised for an open group - a closed one keeps nothing but
        its expand arrow, so the common case (all collapsed, user is drawing)
        costs three ``setText`` calls per model change.
        """
        if not hasattr(self, "work_tree_nodes"):
            return
        groups = (
            (self.work_tree_nodes, len(self.canvas.nodes), self._fill_node_tree_group),
            (self.work_tree_members, len(self.canvas.elements), self._fill_member_tree_group),
            (self.work_tree_supports, len(self.canvas.boundaries), self._fill_support_tree_group),
        )
        for item, count, fill in groups:
            item.setText(1, str(count))
            item.takeChildren()
            if count and item.isExpanded():
                fill(item)
            else:
                # takeChildren() above also removes the expand arrow, so put it
                # back by hand for a group that *can* be opened but is closed.
                item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                    if count
                    else QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator
                )


    def _on_work_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        fill = {
            id(self.work_tree_nodes): self._fill_node_tree_group,
            id(self.work_tree_members): self._fill_member_tree_group,
            id(self.work_tree_supports): self._fill_support_tree_group,
        }.get(id(item))
        if fill is not None and item.childCount() == 0:
            fill(item)


    def _add_entity_tree_row(
        self, parent: QTreeWidgetItem, kind: str, tag: int, label: str, detail: str, tooltip: str
    ) -> None:
        """One clickable geometry row. The (kind, tag) pair goes in its own
        item-data role rather than ``UserRole``, which the load-entry rows
        sharing this tree already use for their entry id - see
        ``_on_work_tree_item_clicked``, which reads whichever one is set."""
        row = QTreeWidgetItem([label, detail])
        row.setData(0, _TREE_ENTITY_ROLE, (kind, tag))
        row.setToolTip(0, tooltip)
        parent.addChild(row)


    def _note_truncated_tree_group(self, parent: QTreeWidgetItem, total: int) -> None:
        if total > self._WORK_TREE_CHILD_LIMIT:
            parent.addChild(
                QTreeWidgetItem([f"…외 {total - self._WORK_TREE_CHILD_LIMIT}개", ""])
            )


    def _fill_node_tree_group(self, parent: QTreeWidgetItem) -> None:
        for tag in sorted(self.canvas.nodes)[: self._WORK_TREE_CHILD_LIMIT]:
            node = self.canvas.nodes[tag]
            hinge = " · 활절점" if tag in self.canvas.hinge_nodes else ""
            self._add_entity_tree_row(
                parent,
                "node",
                tag,
                f"절점 {tag}",
                f"{node.x:g}, {node.y:g}, {node.z:g}",
                f"({node.x:g}, {node.y:g}, {node.z:g}){hinge}",
            )
        self._note_truncated_tree_group(parent, len(self.canvas.nodes))


    def _fill_member_tree_group(self, parent: QTreeWidgetItem) -> None:
        for tag in sorted(self.canvas.elements)[: self._WORK_TREE_CHILD_LIMIT]:
            element = self.canvas.elements[tag]
            self._add_entity_tree_row(
                parent,
                "element",
                tag,
                f"부재 {tag}",
                f"{element.node_i}→{element.node_j}",
                f"{element.element_type} · 절점 {element.node_i} → {element.node_j}",
            )
        self._note_truncated_tree_group(parent, len(self.canvas.elements))


    def _fill_support_tree_group(self, parent: QTreeWidgetItem) -> None:
        for tag in sorted(self.canvas.boundaries)[: self._WORK_TREE_CHILD_LIMIT]:
            condition = self.canvas.boundaries[tag]
            name = SUPPORT_NAMES.get(condition.support_kind, "사용자 구속")
            self._add_entity_tree_row(
                parent, "node", tag, f"절점 {tag}", name, name
            )
        self._note_truncated_tree_group(parent, len(self.canvas.boundaries))


    def _select_entity_from_tree(self, kind: str, tag: int) -> None:
        """Clicking a Work Tree row selects that entity on the canvas, so the
        tree works as a way to *find* something in a crowded model rather than
        just listing it."""
        if kind == "node" and tag in self.canvas.nodes:
            self.canvas.selected_nodes = {tag}
            self.canvas.selected_elements = set()
        elif kind == "element" and tag in self.canvas.elements:
            self.canvas.selected_elements = {tag}
            self.canvas.selected_nodes = set()
        else:
            return  # a row left over from a deleted entity - ignore, don't crash
        self.canvas.selection_changed.emit()

