import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openseespy.opensees as ops
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from openframe.features.viewport.presentation.model_viewport import ModelViewport
from openframe.infrastructure.opensees.linear_static_solver import (
    run_linear_static_analysis,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

EXAMPLE_MODEL = Path(__file__).parents[2] / "examples" / "cantilever_frame_3d.py"


def test_imports_3d_coordinates_dofs_and_section_properties() -> None:
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)

    assert model.ndm == 3
    assert model.ndf == 6
    assert model.validate() == []
    assert model.nodes[2].z == pytest.approx(3.0)
    assert model.nodes[2].ndf == 6
    assert model.boundaries[0].restraints == (True,) * 6
    assert model.elements[1].properties == {
        "A": 0.02,
        "E": 200_000_000.0,
        "G": 76_900_000.0,
        "J": 1.6e-4,
        "Iy": 8.0e-5,
        "Iz": 8.0e-5,
        "transf_tag": "1",
    }


def test_solves_3d_frame_and_returns_six_dof_results() -> None:
    try:
        results = run_linear_static_analysis(EXAMPLE_MODEL)
    finally:
        ops.wipe()

    assert results["status"] == "completed"
    assert results["element_results"][0]["length"] == pytest.approx(3.0)
    assert len(results["element_results"][0]["local_forces"]) == 12

    free_node = next(item for item in results["node_results"] if item["node_tag"] == 2)
    assert len(free_node["displacement"]) == 6
    assert any(abs(value) > 0.0 for value in free_node["displacement"][:3])

    total_reaction = [
        sum(item["reaction"][index] for item in results["node_results"])
        for index in range(3)
    ]
    assert total_reaction == pytest.approx([-10.0, 5.0, 20.0], abs=1e-6)


def test_3d_viewport_switches_between_iso_and_orthographic_views() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    viewport = ModelViewport()

    viewport.set_model(model)
    application.processEvents()

    assert not viewport.view_selector.isHidden()
    assert viewport.view_selector.currentData() == "iso"
    assert viewport.scene.projection == "iso"
    assert any(item.data(0) == ("axis", "Z") for item in viewport.scene.items())

    viewport.view_selector.setCurrentIndex(viewport.view_selector.findData("xz"))
    application.processEvents()
    assert viewport.scene.projection == "xz"
    assert any(item.data(0) == ("element", 1) for item in viewport.scene.items())
    viewport.close()


def test_middle_mouse_drag_orbits_the_3d_model() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    viewport = ModelViewport()
    viewport.resize(800, 600)
    viewport.show()
    viewport.set_model(model)
    application.processEvents()
    initial_angles = viewport.scene.camera_angles

    target = viewport.view.viewport()
    QTest.mousePress(
        target,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(300, 250),
    )
    QTest.mouseMove(target, QPoint(340, 220), delay=1)
    QTest.mouseRelease(
        target,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(340, 220),
    )
    application.processEvents()

    assert viewport.scene.projection == "free"
    assert viewport.scene.camera_angles != initial_angles
    assert viewport.view_selector.currentData() == "free"
    viewport.close()


def test_shift_middle_mouse_drag_pans_even_after_fit() -> None:
    application = QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(EXAMPLE_MODEL)
    viewport = ModelViewport()
    viewport.resize(800, 600)
    viewport.show()
    viewport.set_model(model)
    viewport.fit_model()
    application.processEvents()

    target = viewport.view.viewport()
    viewport_center = target.rect().center()
    center_before = viewport.view.mapToScene(viewport_center)
    QTest.mousePress(
        target,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.ShiftModifier,
        QPoint(300, 250),
    )
    QTest.mouseMove(target, QPoint(350, 280), delay=1)
    QTest.mouseRelease(
        target,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.ShiftModifier,
        QPoint(350, 280),
    )
    application.processEvents()
    center_after = viewport.view.mapToScene(viewport_center)

    assert center_after != center_before
    viewport.close()
