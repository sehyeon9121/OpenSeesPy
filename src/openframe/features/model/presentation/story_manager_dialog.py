"""Story Manager - building floor levels, each optionally tied together as a
rigid diaphragm. Two ways in on purpose: type a new story by hand (name +
elevation), or click "자동 감지" to group every drawn node by its Z
coordinate and let Korean-building-convention names (1층/2층/지하1층) get
picked automatically (see ``canvas_stories.py``'s own docstring).

The diaphragm toggle lives directly in the table as a checkbox per row
(``setCellWidget``, not a separate form + Apply) - it is the one field a
student is expected to flip constantly while exploring "what if this floor
were rigid", so it has to be a single click, not select-row-then-edit-form.
Same live-apply-per-click style as ``LoadCaseManagerDialog`` (see its own
docstring for why) for everything else: rename by double-clicking the name
cell, delete via the row's own button - no staged Save.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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

from openframe.features.model.presentation.safe_spinbox import SafeDoubleSpinBox

_NAME_COLUMN = 0
_ELEVATION_COLUMN = 1
_NODE_COUNT_COLUMN = 2
_DIAPHRAGM_COLUMN = 3
_DELETE_COLUMN = 4


def _elevation_field() -> SafeDoubleSpinBox:
    field = SafeDoubleSpinBox()
    field.setRange(-1_000_000.0, 1_000_000.0)
    field.setDecimals(10)
    return field


class StoryManagerDialog(QDialog):
    def __init__(self, canvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self.setWindowTitle("Story Manager")
        self.resize(560, 520)

        layout = QVBoxLayout(self)

        hint = QLabel(
            "건물의 층을 정의합니다. 같은 표고(Z)의 절점들을 묶어 강체 다이아프램으로 "
            "지정하면 그 층의 절점들이 수평 방향으로 한 몸처럼 움직입니다 (횡력 해석에 필요)."
        )
        hint.setObjectName("setupSectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        auto_detect_button = QPushButton("자동 감지 (절점 Z좌표 기준)")
        auto_detect_button.clicked.connect(self._auto_detect)
        layout.addWidget(auto_detect_button)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["층 이름", "표고 (Z)", "절점 수", "강체 다이아프램", ""])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_ELEVATION_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_NODE_COUNT_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_DIAPHRAGM_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_DELETE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)
        rename_hint = QLabel("층 이름을 더블클릭하면 이름을 바꿀 수 있습니다.")
        rename_hint.setObjectName("setupSectionHint")
        layout.addWidget(rename_hint)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("예: 1층")
        form.addRow("새 층 이름", self.name_input)
        self.elevation_input = _elevation_field()
        form.addRow("표고 (Z)", self.elevation_input)
        self.diaphragm_input = QCheckBox("강체 다이아프램으로 지정")
        form.addRow(self.diaphragm_input)
        layout.addLayout(form)

        self.status_label = QLabel()
        self.status_label.setObjectName("setupSectionHint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        add_button = QPushButton("추가")
        add_button.setObjectName("loadPrimaryButton")
        add_button.clicked.connect(self._add_story)
        button_row.addWidget(add_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._refresh_table()

    def _sorted_stories(self) -> list:
        # Highest elevation first - reads top-down the same way a building's
        # own elevation does, so scanning the table feels like scanning the
        # building.
        return sorted(self._canvas.stories.values(), key=lambda story: -story.elevation)

    def _refresh_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for story in self._sorted_stories():
            row = self.table.rowCount()
            self.table.insertRow(row)

            name_item = QTableWidgetItem(story.name)
            name_item.setData(Qt.ItemDataRole.UserRole, story.id)
            self.table.setItem(row, _NAME_COLUMN, name_item)

            elevation_item = QTableWidgetItem(f"{story.elevation:g}")
            elevation_item.setFlags(elevation_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, _ELEVATION_COLUMN, elevation_item)

            node_count = len(self._canvas.nodes_at_story(story.id))
            count_item = QTableWidgetItem(str(node_count))
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, _NODE_COUNT_COLUMN, count_item)

            diaphragm_cell = QWidget()
            diaphragm_layout = QHBoxLayout(diaphragm_cell)
            diaphragm_layout.setContentsMargins(0, 0, 0, 0)
            diaphragm_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            diaphragm_checkbox = QCheckBox()
            diaphragm_checkbox.setChecked(story.rigid_diaphragm)
            diaphragm_checkbox.toggled.connect(
                lambda checked, story_id=story.id: self._toggle_diaphragm(story_id, checked)
            )
            diaphragm_layout.addWidget(diaphragm_checkbox)
            self.table.setCellWidget(row, _DIAPHRAGM_COLUMN, diaphragm_cell)

            delete_button = QPushButton("삭제")
            delete_button.clicked.connect(lambda _checked=False, story_id=story.id: self._delete_story(story_id))
            self.table.setCellWidget(row, _DELETE_COLUMN, delete_button)
        self.table.blockSignals(False)
        self.status_label.clear()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != _NAME_COLUMN:
            return
        story_id = item.data(Qt.ItemDataRole.UserRole)
        new_name = item.text().strip()
        if not new_name or new_name == story_id:
            self._refresh_table()
            return
        if not self._canvas.update_story(story_id, name=new_name):
            self.status_label.setText(f"⚠ 이름을 바꿀 수 없습니다: '{new_name}' (이미 사용 중이거나 비어 있음)")
            self._refresh_table()
            return
        self._refresh_table()

    def _toggle_diaphragm(self, story_id: str, checked: bool) -> None:
        self._canvas.update_story(story_id, rigid_diaphragm=checked)
        self.status_label.clear()

    def _delete_story(self, story_id: str) -> None:
        self._canvas.delete_story(story_id)
        self._refresh_table()

    def _add_story(self) -> None:
        name = self.name_input.text().strip()
        story_id = self._canvas.add_story(
            name, self.elevation_input.value(), rigid_diaphragm=self.diaphragm_input.isChecked()
        )
        if story_id is None:
            self.status_label.setText(f"⚠ 이름이 비어있거나 이미 사용 중입니다: '{name}'")
            return
        self.name_input.clear()
        self.diaphragm_input.setChecked(False)
        self._refresh_table()

    def _auto_detect(self) -> None:
        created = self._canvas.auto_detect_stories()
        if not created:
            self.status_label.setText("⚠ 새로 추가할 층이 없습니다 (모델이 비어 있거나 모든 표고에 이미 층이 있음).")
            return
        self._refresh_table()
        self.status_label.setText(f"✓ {len(created)}개 층을 자동으로 만들었습니다: {', '.join(created)}")
