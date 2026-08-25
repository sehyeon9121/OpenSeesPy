"""Load Case Manager - add/duplicate/rename/delete the named load cases the
Loads tab's Load Case dropdown offers.

Modal but non-committal about editing style: every button calls straight
into ``StaticsDrawingCanvas``'s ``add_load_case``/``duplicate_load_case``/
``rename_load_case``/``delete_load_case`` (``canvas_load_entries.py``) and
applies immediately - matching how every other property panel in this app
(section/material 적용, support 적용, ...) applies on click rather than
staging changes behind a separate Save, so a student never wonders whether
closing this dialog without an extra step discarded anything.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import LoadCaseKind
from openframe.features.model.presentation.model_sidebar import LOAD_CASE_PRESENTATION

_TYPE_OPTIONS: tuple[LoadCaseKind, ...] = (
    LoadCaseKind.DEAD,
    LoadCaseKind.LIVE,
    LoadCaseKind.ROOF_LIVE,
    LoadCaseKind.WIND,
    LoadCaseKind.SEISMIC,
    LoadCaseKind.SNOW,
    LoadCaseKind.OTHER,
)


class LoadCaseManagerDialog(QDialog):
    def __init__(self, canvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self.setWindowTitle("Load Case Manager")
        self.resize(560, 420)

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._load_selection_into_form)
        layout.addWidget(self.table, 1)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("예: LL_OFFICE")
        form.addRow("Name", self.name_input)
        self.type_input = QComboBox()
        for kind in _TYPE_OPTIONS:
            self.type_input.addItem(LOAD_CASE_PRESENTATION[kind][0], kind.value)
        form.addRow("Type", self.type_input)
        self.description_input = QLineEdit()
        form.addRow("Description", self.description_input)
        layout.addLayout(form)

        self.status_label = QLabel()
        self.status_label.setObjectName("setupSectionHint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        add_button = QPushButton("추가")
        add_button.clicked.connect(self._add_case)
        button_row.addWidget(add_button)
        duplicate_button = QPushButton("복제")
        duplicate_button.clicked.connect(self._duplicate_case)
        button_row.addWidget(duplicate_button)
        rename_button = QPushButton("이름 변경")
        rename_button.clicked.connect(self._rename_case)
        button_row.addWidget(rename_button)
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(self._delete_case)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._refresh_table()

    def _selected_case_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(1) if item is not None else None

    def _load_selection_into_form(self) -> None:
        case_id = self._selected_case_id()
        case = self._canvas.load_cases.get(case_id) if case_id else None
        if case is None:
            return
        self.name_input.setText(case.name)
        index = self.type_input.findData(case.kind.value)
        if index >= 0:
            self.type_input.setCurrentIndex(index)
        self.description_input.setText(case.description)

    def _refresh_table(self, select_case_id: str | None = None) -> None:
        self.table.setRowCount(0)
        for case in self._canvas.load_cases.values():
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(case.name)
            name_item.setData(1, case.id)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(LOAD_CASE_PRESENTATION[case.kind][0]))
            self.table.setItem(row, 2, QTableWidgetItem(case.description))
            if case.id == select_case_id:
                self.table.selectRow(row)
        self.status_label.clear()

    def _add_case(self) -> None:
        name = self.name_input.text().strip()
        kind = LoadCaseKind(self.type_input.currentData())
        case_id = self._canvas.add_load_case(name, kind=kind, description=self.description_input.text().strip())
        if case_id is None:
            self.status_label.setText(f"⚠ 이름이 비어있거나 이미 사용 중입니다: '{name}'")
            return
        self._refresh_table(select_case_id=case_id)

    def _duplicate_case(self) -> None:
        case_id = self._selected_case_id()
        if case_id is None:
            self.status_label.setText("⚠ 먼저 복제할 하중케이스를 선택하세요.")
            return
        new_name = f"{case_id}_COPY"
        result = self._canvas.duplicate_load_case(case_id, new_name)
        if result is None:
            self.status_label.setText(f"⚠ '{new_name}' 이름이 이미 사용 중입니다.")
            return
        self._refresh_table(select_case_id=result)

    def _rename_case(self) -> None:
        case_id = self._selected_case_id()
        new_name = self.name_input.text().strip()
        if case_id is None:
            self.status_label.setText("⚠ 먼저 이름을 바꿀 하중케이스를 선택하세요.")
            return
        if not self._canvas.rename_load_case(case_id, new_name):
            self.status_label.setText(f"⚠ 이름을 바꿀 수 없습니다: '{new_name}'")
            return
        self._refresh_table(select_case_id=new_name)

    def _delete_case(self) -> None:
        case_id = self._selected_case_id()
        if case_id is None:
            self.status_label.setText("⚠ 먼저 삭제할 하중케이스를 선택하세요.")
            return
        self._canvas.delete_load_case(case_id)
        self._refresh_table()
