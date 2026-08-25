"""Compact searchable node picker used by response-history results."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

_VISIBLE_NODE_ROWS = 10


class NodePickerDialog(QDialog):
    """Choose one node from a searchable, ten-row scrollable list."""

    def __init__(
        self,
        node_tags: tuple[int, ...],
        initial: int | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Node")
        self.resize(320, 390)
        self._node_tags = node_tags
        self._selected_node = initial

        layout = QVBoxLayout(self)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search node number…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(lambda _text: self._refresh_list())
        layout.addWidget(self.search_box)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("timeHistoryNodePickerList")
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_current())
        self.list_widget.itemSelectionChanged.connect(self._update_apply_button)
        layout.addWidget(self.list_widget, 1)

        buttons = QDialogButtonBox()
        self.apply_button = buttons.addButton(
            "Apply", QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.apply_button.clicked.connect(self._accept_current)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_list()
        # At most ten nodes are visible; all remaining nodes are reached by
        # scrolling, rather than extending the popup down the whole screen.
        row_height = max(self.list_widget.sizeHintForRow(0), 24)
        frame = self.list_widget.frameWidth() * 2
        self.list_widget.setMaximumHeight(row_height * _VISIBLE_NODE_ROWS + frame)

    def _refresh_list(self) -> None:
        query = self.search_box.text().strip().lower()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        selected_item: QListWidgetItem | None = None
        for node_tag in self._node_tags:
            label = f"Node {node_tag}"
            if query and query not in label.lower() and query not in str(node_tag):
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, node_tag)
            self.list_widget.addItem(item)
            if node_tag == self._selected_node:
                selected_item = item
        self.list_widget.blockSignals(False)
        if selected_item is not None:
            self.list_widget.setCurrentItem(selected_item)
            self.list_widget.scrollToItem(selected_item)
        self._update_apply_button()

    def _update_apply_button(self) -> None:
        self.apply_button.setEnabled(self.list_widget.currentItem() is not None)

    def _accept_current(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self._selected_node = int(item.data(Qt.ItemDataRole.UserRole))
        self.accept()

    def selected_node(self) -> int | None:
        return self._selected_node


class SearchableNodeSelector(QComboBox):
    """Combo-compatible selector whose popup is a searchable node dialog."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaxVisibleItems(_VISIBLE_NODE_ROWS)
        self.setToolTip("Click to search or scroll through nodes")

    def showPopup(self) -> None:
        node_tags = tuple(int(self.itemData(index)) for index in range(self.count()))
        if not node_tags:
            return
        dialog = NodePickerDialog(node_tags, self.currentData(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_node()
        index = self.findData(selected)
        if index >= 0:
            self.setCurrentIndex(index)
