"""Searchable/sortable picker for the built-in ground-motion catalog.

Replaces a bare combo box - all bundled records stacked in one dropdown,
hard to scan and hard to search - with a small dialog: a search box, a
name-sort toggle, and a scrollable list, confirmed with an explicit Apply
button rather than closing on the first click (so browsing doesn't commit a
selection by accident).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from openframe.core.domain import GroundMotionRecord


def _record_label(record: GroundMotionRecord) -> str:
    return f"{record.event} — {record.station} ({record.component})"


class GroundMotionPickerDialog(QDialog):
    """Modal picker over ``records``, pre-selecting ``initial`` if given.

    Call :meth:`exec` then, if it returned ``Accepted``, read
    :meth:`selected_record` for the record the user confirmed with Apply.
    """

    def __init__(
        self,
        records: tuple[GroundMotionRecord, ...],
        initial: GroundMotionRecord | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Ground Motion")
        self.resize(440, 520)
        self._records = records
        self._selected_record = initial
        self._sort_ascending = True

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search by event, station, component…")
        self.search_box.textChanged.connect(lambda _text: self._refresh_list())
        search_row.addWidget(self.search_box, 1)
        self.sort_button = QPushButton("Sort: A → Z")
        self.sort_button.clicked.connect(self._toggle_sort)
        search_row.addWidget(self.sort_button)
        layout.addLayout(search_row)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._accept_current())
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget, 1)

        self.result_count_label = QLabel()
        self.result_count_label.setObjectName("secondaryText")
        layout.addWidget(self.result_count_label)

        button_box = QDialogButtonBox()
        self.apply_button = button_box.addButton(
            "Apply", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = button_box.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.apply_button.clicked.connect(self._accept_current)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(button_box)

        self._refresh_list()

    def _toggle_sort(self) -> None:
        self._sort_ascending = not self._sort_ascending
        self.sort_button.setText("Sort: A → Z" if self._sort_ascending else "Sort: Z → A")
        self._refresh_list()

    def _refresh_list(self) -> None:
        query = self.search_box.text().strip().lower()
        records = sorted(
            self._records,
            key=lambda record: _record_label(record).lower(),
            reverse=not self._sort_ascending,
        )
        if query:
            records = [
                record
                for record in records
                if query in _record_label(record).lower()
                or query in record.record_id.lower()
            ]

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        selected_item = None
        for record in records:
            item = QListWidgetItem(_record_label(record))
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.list_widget.addItem(item)
            if self._selected_record is not None and record.record_id == self._selected_record.record_id:
                selected_item = item
        self.list_widget.blockSignals(False)

        if selected_item is not None:
            self.list_widget.setCurrentItem(selected_item)
        self.result_count_label.setText(f"{len(records)} of {len(self._records)} records")
        self.apply_button.setEnabled(self.list_widget.currentItem() is not None)

    def _on_selection_changed(self) -> None:
        self.apply_button.setEnabled(bool(self.list_widget.selectedItems()))

    def _accept_current(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self._selected_record = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def selected_record(self) -> GroundMotionRecord | None:
        return self._selected_record
