import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from openframe.features.model.presentation.model_sidebar import ModelSidebar
from openframe.features.viewport.items.uniform_element_load_item import (
    UniformElementLoadItem,
)
from openframe.features.viewport.presentation.model_viewport import ModelViewport
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

SOURCE = Path(__file__).parents[2] / "examples" / "udl_beam_2d.py"


def test_uniform_element_load_is_imported_listed_and_drawn() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)

    assert len(model.element_loads) == 1
    assert model.element_loads[0].element_tag == 1
    assert (model.element_loads[0].wx, model.element_loads[0].wy) == pytest.approx(
        (0.0, -10.0)
    )

    sidebar = ModelSidebar()
    sidebar.set_model(model)
    load_item = sidebar._tree_items[("element_load", 1)]
    assert "Uniform" in load_item.text(0)
    assert "Wy=-10" in load_item.text(0)

    viewport = ModelViewport()
    viewport.set_model(model)
    drawn_loads = [
        item for item in viewport.scene.items() if isinstance(item, UniformElementLoadItem)
    ]
    assert len(drawn_loads) == 1
    assert "Wy=-10" in drawn_loads[0].toolTip()
    assert drawn_loads[0].load_scale == pytest.approx(1.0)
    assert viewport.load_view_selector.currentData() == "element"

    viewport.filter_options["load"].setChecked(False)
    assert not drawn_loads[0].isVisible()
    viewport.filter_options["load"].setChecked(True)
    assert drawn_loads[0].isVisible()

    sidebar.tree.setCurrentItem(load_item)
    assert load_item.data(0, Qt.ItemDataRole.UserRole) == ("element_load", 1)
    sidebar.close()
    viewport.close()
    application.processEvents()
