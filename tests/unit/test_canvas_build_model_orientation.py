"""build_model() must carry Create Element 회전각 into the analysis mesh.

The 3D canvas preview reads ``authoring_model()`` (drawn members as-is).
Solve reads ``build_model()``, which used to reconstruct each Element
without ``local_axis_angle``. A 90° H→I roll then looked rotated on screen
but still bent about the original Iy/Iz, so stress and displacement did
not change.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
)
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas


def _canvas() -> StaticsDrawingCanvas:
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    canvas.ndm = 3
    return canvas


def _cantilever(canvas: StaticsDrawingCanvas, local_axis_angle: float) -> int:
    canvas.nodes[1] = Node(1, 0.0, 0.0, 0.0, 6)
    canvas.nodes[2] = Node(2, 8.0, 0.0, 0.0, 6)
    canvas.elements[1] = Element(
        1,
        1,
        2,
        "frame",
        properties={
            "E": 200_000.0,
            "A": 1.0,
            "G": 80_000.0,
            "J": 1.0,
            "Iy": 1.0,
            "Iz": 1_000.0,
        },
        local_axis_angle=local_axis_angle,
    )
    canvas.boundaries[1] = BoundaryCondition(1, (True,) * 6)
    canvas.nodal_loads[2] = NodalLoad(2, (0.0, 0.0, -16.0, 0.0, 0.0, 0.0))
    return 1


def test_build_model_preserves_local_axis_angle() -> None:
    canvas = _canvas()
    _cantilever(canvas, 90.0)

    model = canvas.build_model()

    assert model.elements[1].local_axis_angle == pytest.approx(90.0)
    assert canvas.authoring_model().elements[1].local_axis_angle == pytest.approx(90.0)


def test_build_model_90_degree_roll_changes_tip_deflection() -> None:
    """Same closed-form pair as the solver unit test, but through the canvas
    analysis mesh the GUI actually solves. Iy=1 vs Iz=1000 so a dropped
    angle cannot hide inside numerical noise."""
    unrotated = _canvas()
    _cantilever(unrotated, 0.0)
    rotated = _canvas()
    _cantilever(rotated, 90.0)

    solver = MaterialFreeStaticsSolver()
    result_0 = solver.solve(unrotated.build_model())
    result_90 = solver.solve(rotated.build_model())
    assert result_0.status == AnalysisStatus.COMPLETED
    assert result_90.status == AnalysisStatus.COMPLETED

    uz_0 = result_0.node_results[2].displacement[2]
    uz_90 = result_90.node_results[2].displacement[2]
    e, length, load = 200_000.0, 8.0, 16.0
    assert uz_0 == pytest.approx(-load * length**3 / (3 * e * 1.0), rel=1.0e-6)
    assert uz_90 == pytest.approx(-load * length**3 / (3 * e * 1_000.0), rel=1.0e-6)
    assert abs(uz_90) < abs(uz_0) / 10.0
