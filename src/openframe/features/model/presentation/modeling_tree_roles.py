"""Shared Work Tree item-data roles and the drag-enabled tree widget.

Kept out of ``modeling_interface_page.py`` so the Work Tree mixin and the
Loads-tab mixin can both fill the same tree without importing the page
(which would be circular once those mixins are bases of the page).
"""

from typing import NamedTuple

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from openframe.features.model.presentation.canvas_input_events import PROPERTY_DRAG_MIME_TYPE

#: Item-data role carrying a Work Tree geometry row's ``(kind, tag)`` pair.
#: Deliberately not ``UserRole``, which the load-entry rows in the same tree
#: already claim for their entry id - keeping them apart lets one click
#: handler serve both without having to guess which kind of row it got.
_TREE_ENTITY_ROLE = Qt.ItemDataRole.UserRole + 1

#: Item-data role carrying a Work Tree 물성/섹션 row's ``("material" | "section",
#: id)`` pair, so its context menu can look the definition up without
#: colliding with ``_TREE_ENTITY_ROLE`` (canvas node/element/support rows) or
#: plain ``UserRole`` (load-entry rows).
_TREE_DEFINITION_ROLE = Qt.ItemDataRole.UserRole + 2


class _WorkTree(QTreeWidget):
    """A QTreeWidget that only ever starts a real Qt drag for a 물성/섹션 row
    (one carrying ``_TREE_DEFINITION_ROLE``) - every other row (절점/부재/
    지점/하중조합/load entries) is not a valid drop payload for anything, so
    pressing-and-dragging one just does nothing rather than starting a drag
    Qt has no drop target for. Shared by both the Work Tree and the Load
    Inspector tree (``_new_load_tree``); the latter never has a definition
    row, so this is a no-op there."""

    def startDrag(self, supportedActions) -> None:
        item = self.currentItem()
        definition = item.data(0, _TREE_DEFINITION_ROLE) if item is not None else None
        if not definition:
            return
        kind, definition_id = definition
        mime = QMimeData()
        mime.setData(PROPERTY_DRAG_MIME_TYPE, f"{kind}:{definition_id}".encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class _LoadTreeBinding(NamedTuple):
    """One (하중조합 top item, Load Case top items) tree the Loads command
    tree-population logic can fill - the ordinary Work Tree and the Loads
    tab's own dedicated Load Inspector tree each get one, so
    ``_refresh_load_tree``/entry click/context-menu logic is written once
    and applied to both instead of forked."""

    tree: QTreeWidget
    combinations_item: QTreeWidgetItem
    case_items: dict[str, QTreeWidgetItem]
