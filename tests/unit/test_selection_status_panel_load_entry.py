"""SelectionStatusPanel.show_load_entry - the Load properties view, a
separate entry point from refresh()'s node/element dispatch (see
canvas_load_entries.py's own docstring for why a selected load isn't part of
canvas.selected_nodes/selected_elements at all)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    LoadCase,
    LoadCaseKind,
    LoadEntry,
    MemberDistributedLoadEntry,
    NodalLoadEntry,
)
from openframe.features.model.presentation.selection_status_panel import SelectionStatusPanel


def _panel() -> SelectionStatusPanel:
    QApplication.instance() or QApplication([])
    panel = SelectionStatusPanel()
    panel.show()
    return panel


def _labels(panel: SelectionStatusPanel) -> list[str]:
    return [label.text() for label in panel.findChildren(QLabel)]


def test_shows_nodal_load_id_case_type_and_magnitude() -> None:
    panel = _panel()
    case = LoadCase(id="LL_OFFICE", name="LL_OFFICE", kind=LoadCaseKind.LIVE)
    entry = LoadEntry(id=1, case_id="LL_OFFICE", kind="nodal", target=(5,), payload=NodalLoadEntry(fz=-10.0))

    panel.show_load_entry(entry, case, "NL-001", DEFAULT_UNIT_SYSTEM)

    text = _labels(panel)
    assert "NL-001" in text
    assert "LL_OFFICE" in text
    assert any("N5" in label for label in text)
    assert any("Fz" in label and "-10" in label for label in text)


def test_shows_distributed_load_range_and_uniform_magnitude() -> None:
    panel = _panel()
    entry = LoadEntry(
        id=2,
        case_id="DL_SELF",
        kind="member_uniform",
        target=(7,),
        payload=MemberDistributedLoadEntry(direction="y", start_value=-2.0, end_value=-2.0),
    )

    panel.show_load_entry(entry, None, "ML-001", DEFAULT_UNIT_SYSTEM)

    text = _labels(panel)
    assert any("M7" in label for label in text)
    assert any("-2" in label for label in text)
    assert any("0" in label and "1" in label for label in text)  # full-span range 0~1


def test_edit_reselect_and_delete_buttons_emit_the_entrys_id() -> None:
    panel = _panel()
    entry = LoadEntry(id=42, case_id="DL_SELF", kind="nodal", target=(1,), payload=NodalLoadEntry(fz=-1.0))
    panel.show_load_entry(entry, None, "NL-001", DEFAULT_UNIT_SYSTEM)

    seen: dict[str, int] = {}
    panel.load_edit_requested.connect(lambda entry_id: seen.setdefault("edit", entry_id))
    panel.load_reselect_requested.connect(lambda entry_id: seen.setdefault("reselect", entry_id))
    panel.load_delete_requested.connect(lambda entry_id: seen.setdefault("delete", entry_id))

    for button in panel.findChildren(QPushButton):
        if button.text() in {"수정", "대상 다시 선택", "삭제"}:
            button.click()

    assert seen == {"edit": 42, "reselect": 42, "delete": 42}
