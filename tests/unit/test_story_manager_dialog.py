import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox

from openframe.core.domain import UnitSystem
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
from openframe.features.model.presentation.story_manager_dialog import (
    _DIAPHRAGM_COLUMN,
    _DIAPHRAGM_ON,
    _ELEVATION_COLUMN,
    _NAME_COLUMN,
    _NODE_COUNT_COLUMN,
    StoryManagerDialog,
)


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.ndm = 3
    return canvas


def test_dialog_lists_stories_sorted_highest_elevation_first() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    canvas.add_story("2층", 3.0)

    dialog = StoryManagerDialog(canvas)

    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, _NAME_COLUMN).text() == "2층"
    assert dialog.table.item(1, _NAME_COLUMN).text() == "1층"


def test_dialog_shows_the_node_count_at_each_story() -> None:
    canvas = _canvas()
    canvas._add_node_at((0.0, 0.0, 3.0))
    canvas._add_node_at((4.0, 0.0, 3.0))
    canvas.add_story("2층", 3.0)

    dialog = StoryManagerDialog(canvas)

    assert dialog.table.item(0, _NODE_COUNT_COLUMN).text() == "2"


def test_add_button_creates_a_story_from_the_form() -> None:
    canvas = _canvas()
    dialog = StoryManagerDialog(canvas)
    dialog.name_input.setText("1층")
    dialog.elevation_input.setValue(0.0)
    dialog.diaphragm_input.setChecked(True)

    dialog._add_story()

    assert "1층" in canvas.stories
    assert canvas.stories["1층"].rigid_diaphragm is True
    assert dialog.table.rowCount() == 1


def test_add_button_rejects_a_duplicate_name() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    dialog = StoryManagerDialog(canvas)
    dialog.name_input.setText("1층")

    dialog._add_story()

    assert len(canvas.stories) == 1
    assert "이미 사용 중" in dialog.status_label.text()


def test_renaming_the_name_cell_updates_the_canvas() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    dialog = StoryManagerDialog(canvas)

    dialog.table.item(0, _NAME_COLUMN).setText("지상1층")

    assert "1층" not in canvas.stories
    assert "지상1층" in canvas.stories


def test_diaphragm_combo_in_the_table_toggles_the_canvas_story() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    dialog = StoryManagerDialog(canvas)
    combo = dialog.table.cellWidget(0, _DIAPHRAGM_COLUMN)
    assert isinstance(combo, QComboBox)

    combo.setCurrentText(_DIAPHRAGM_ON)

    assert canvas.stories["1층"].rigid_diaphragm is True


def test_delete_button_removes_the_story() -> None:
    canvas = _canvas()
    canvas.add_story("1층", 0.0)
    dialog = StoryManagerDialog(canvas)

    dialog._delete_story("1층")

    assert canvas.stories == {}
    assert dialog.table.rowCount() == 0


def test_auto_detect_button_creates_stories_and_refreshes_the_table() -> None:
    canvas = _canvas()
    canvas._add_node_at((0.0, 0.0, 0.0))
    canvas._add_node_at((0.0, 0.0, 3.0))
    dialog = StoryManagerDialog(canvas)

    dialog._auto_detect()

    assert dialog.table.rowCount() == 2
    assert "층을 자동으로 만들었습니다" in dialog.status_label.text()


def test_auto_detect_button_reports_when_nothing_new_is_found() -> None:
    canvas = _canvas()
    dialog = StoryManagerDialog(canvas)

    dialog._auto_detect()

    assert "새로 추가할 층이 없습니다" in dialog.status_label.text()


def test_elevation_labels_default_to_meters() -> None:
    dialog = StoryManagerDialog(_canvas())
    assert dialog.table.horizontalHeaderItem(_ELEVATION_COLUMN).text() == "노드 높이 Z (m)"


def test_elevation_labels_reflect_the_pages_own_unit_system() -> None:
    dialog = StoryManagerDialog(_canvas(), unit_system=UnitSystem(force="kN", length="mm"))
    assert dialog.table.horizontalHeaderItem(_ELEVATION_COLUMN).text() == "노드 높이 Z (mm)"


def test_auto_button_label_is_beginner_friendly() -> None:
    dialog = StoryManagerDialog(_canvas())
    assert dialog.auto_detect_button.text().startswith("Auto")
