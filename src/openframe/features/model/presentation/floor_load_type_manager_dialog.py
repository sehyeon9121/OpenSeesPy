"""Floor Load Type Manager - MIDAS' "Floor Load Type" dialog: define a named
bundle of up to 8 (Load Case, magnitude) rows once, then Apply the whole
bundle to a floor boundary in a single step instead of repeating the
single-value Floor Load form once per case (see canvas_load_entries.py's
``apply_floor_load_type``, which mints one ``FloorLoadEntry`` per non-empty
row).

Same live-apply-per-click editing style as ``LoadCaseManagerDialog`` (see its
own docstring for why) - Add/Update/Duplicate/Delete each call straight into
the canvas and refresh the list, no staged Save.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
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

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, FloorLoadTypeRow, UnitSystem
from openframe.features.model.presentation.load_case_manager_dialog import LoadCaseManagerDialog
from openframe.features.model.presentation.safe_spinbox import SafeComboBox, SafeDoubleSpinBox

#: MIDAS' own Floor Load Type dialog offers exactly 8 rows.
_ROW_COUNT = 8


def _magnitude_field() -> SafeDoubleSpinBox:
    field = SafeDoubleSpinBox()
    field.setRange(-1_000_000.0, 1_000_000.0)
    field.setDecimals(10)
    return field


class FloorLoadTypeManagerDialog(QDialog):
    def __init__(
        self,
        canvas,
        unit_system: UnitSystem | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._unit_system = unit_system or DEFAULT_UNIT_SYSTEM
        self.setWindowTitle("Floor Load Type Manager")
        self.resize(520, 640)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("예: 사무실 바닥")
        form.addRow("Name", self.name_input)
        self.description_input = QLineEdit()
        form.addRow("Description", self.description_input)
        layout.addLayout(form)

        rows_grid = QGridLayout()
        rows_grid.addWidget(QLabel("Load Case"), 0, 1)
        self.magnitude_header = QLabel(f"크기 ({self._unit_system.stress})")
        rows_grid.addWidget(self.magnitude_header, 0, 2)
        self.row_case_combos: list[SafeComboBox] = []
        self.row_magnitude_spins: list[SafeDoubleSpinBox] = []
        for index in range(_ROW_COUNT):
            rows_grid.addWidget(QLabel(f"{index + 1}."), index + 1, 0)
            combo = SafeComboBox()
            combo.addItem("NONE", None)
            rows_grid.addWidget(combo, index + 1, 1)
            self.row_case_combos.append(combo)
            spin = _magnitude_field()
            rows_grid.addWidget(spin, index + 1, 2)
            self.row_magnitude_spins.append(spin)
        layout.addLayout(rows_grid)

        define_case_button = QPushButton("하중케이스 정의...")
        define_case_button.clicked.connect(self._open_load_case_manager)
        layout.addWidget(define_case_button)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._load_selection_into_form)
        layout.addWidget(self.table, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("setupSectionHint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        add_button = QPushButton("추가")
        add_button.clicked.connect(self._add_type)
        button_row.addWidget(add_button)
        update_button = QPushButton("수정")
        update_button.clicked.connect(self._update_type)
        button_row.addWidget(update_button)
        duplicate_button = QPushButton("복제")
        duplicate_button.clicked.connect(self._duplicate_type)
        button_row.addWidget(duplicate_button)
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(self._delete_type)
        button_row.addWidget(delete_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._refresh_case_combos()
        self._refresh_table()

    def _refresh_case_combos(self) -> None:
        for combo in self.row_case_combos:
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("NONE", None)
            for case in self._canvas.load_cases.values():
                combo.addItem(case.name, case.id)
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _open_load_case_manager(self) -> None:
        dialog = LoadCaseManagerDialog(self._canvas, self)
        dialog.exec()
        self._refresh_case_combos()

    def _selected_type_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(1) if item is not None else None

    def _rows_from_form(self) -> tuple[FloorLoadTypeRow, ...]:
        return tuple(
            FloorLoadTypeRow(case_id=combo.currentData(), magnitude=spin.value())
            for combo, spin in zip(self.row_case_combos, self.row_magnitude_spins)
        )

    def _load_rows_into_form(self, rows: tuple[FloorLoadTypeRow, ...]) -> None:
        for index, (combo, spin) in enumerate(zip(self.row_case_combos, self.row_magnitude_spins)):
            row = rows[index] if index < len(rows) else FloorLoadTypeRow()
            case_index = combo.findData(row.case_id)
            combo.setCurrentIndex(case_index if case_index >= 0 else 0)
            spin.setValue(row.magnitude)

    def _load_selection_into_form(self) -> None:
        type_id = self._selected_type_id()
        floor_type = self._canvas.floor_load_types.get(type_id) if type_id else None
        if floor_type is None:
            return
        self.name_input.setText(floor_type.name)
        self.description_input.setText(floor_type.description)
        self._load_rows_into_form(floor_type.rows)

    def _refresh_table(self, select_type_id: str | None = None) -> None:
        self.table.setRowCount(0)
        for floor_type in self._canvas.floor_load_types.values():
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(floor_type.name)
            name_item.setData(1, floor_type.id)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(floor_type.description))
            if floor_type.id == select_type_id:
                self.table.selectRow(row)
        self.status_label.clear()

    def _add_type(self) -> None:
        name = self.name_input.text().strip()
        type_id = self._canvas.add_floor_load_type(
            name, description=self.description_input.text().strip(), rows=self._rows_from_form()
        )
        if type_id is None:
            self.status_label.setText(f"⚠ 이름이 비어있거나 이미 사용 중입니다: '{name}'")
            return
        self._refresh_table(select_type_id=type_id)

    def _update_type(self) -> None:
        type_id = self._selected_type_id()
        if type_id is None:
            self.status_label.setText("⚠ 먼저 수정할 타입을 선택하세요.")
            return
        name = self.name_input.text().strip()
        if not self._canvas.update_floor_load_type(
            type_id,
            name=name or None,
            description=self.description_input.text().strip(),
            rows=self._rows_from_form(),
        ):
            self.status_label.setText(f"⚠ 이름을 바꿀 수 없습니다: '{name}'")
            return
        self._refresh_table(select_type_id=name or type_id)

    def _duplicate_type(self) -> None:
        type_id = self._selected_type_id()
        if type_id is None:
            self.status_label.setText("⚠ 먼저 복제할 타입을 선택하세요.")
            return
        new_name = f"{type_id}_COPY"
        result = self._canvas.duplicate_floor_load_type(type_id, new_name)
        if result is None:
            self.status_label.setText(f"⚠ '{new_name}' 이름이 이미 사용 중입니다.")
            return
        self._refresh_table(select_type_id=result)

    def _delete_type(self) -> None:
        type_id = self._selected_type_id()
        if type_id is None:
            self.status_label.setText("⚠ 먼저 삭제할 타입을 선택하세요.")
            return
        self._canvas.delete_floor_load_type(type_id)
        self._refresh_table()
