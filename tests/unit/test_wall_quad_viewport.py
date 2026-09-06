"""Wall quad payloads reach the Quick3D bridge as faces, not per-edge delegates."""

from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Node,
    NodeResult,
    StructuralModel,
    WallPanel,
)
from openframe.features.model.surfaces import assemble_wall_meshes
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _meshed_wall(nx: int = 2, ny: int = 2) -> StructuralModel:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 2.0, 0.0, 0.0, 6),
            3: Node(3, 2.0, 0.0, 3.0, 6),
            4: Node(4, 0.0, 0.0, 3.0, 6),
        },
        walls={
            1: WallPanel(
                tag=1,
                node_1=1,
                node_2=2,
                node_3=3,
                node_4=4,
                thickness=0.2,
                nx=nx,
                ny=ny,
                elastic_modulus=30_000_000.0,
                poisson_ratio=0.2,
            )
        },
    )
    return assemble_wall_meshes(model)


def test_bridge_creates_one_face_per_quad_and_deduped_edges() -> None:
    _app()
    model = _meshed_wall(2, 2)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    assert len(bridge.wallFaces) == 4
    # 2×2 grid: 3 vertical × 2 + 2 horizontal × 3 = 12 unique edges, not 16.
    assert len(bridge.wallEdges) == 12
    assert len(bridge.wallFaces) + len(bridge.wallEdges) < 4 * 5


def test_undeformed_wall_face_centre_matches_quad_geometry() -> None:
    _app()
    model = _meshed_wall(1, 1)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    face = bridge.wallFaces[0]
    # Structural centre (1, 0, 1.5) → view (x, z, -y) = (1, 1.5, 0).
    assert face["x"] == pytest.approx(1.0)
    assert face["y"] == pytest.approx(1.5)
    assert face["z"] == pytest.approx(0.0)
    assert face["scale_x"] == pytest.approx(2.0)
    assert face["scale_y"] == pytest.approx(3.0)


def test_deformed_wall_face_moves_in_the_displacement_direction() -> None:
    _app()
    model = _meshed_wall(1, 1)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    undeformed_x = bridge.wallFaces[0]["x"]
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            tag: NodeResult(
                tag,
                displacement=(0.2, 0.0, 0.0, 0.0, 0.0, 0.0)
                if node.z > 1.0
                else (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            )
            for tag, node in model.nodes.items()
        },
    )
    bridge.set_result(model, result, scale=1.0, show_undeformed=True)
    deformed_x = bridge.wallFaces[0]["x"]
    ghost_x = bridge.ghostWallFaces[0]["x"]

    assert deformed_x > undeformed_x
    assert ghost_x == pytest.approx(undeformed_x)
    # Top edge moved +0.2 in X, bottom stayed; centre moves +0.1.
    assert deformed_x == pytest.approx(undeformed_x + 0.1)
