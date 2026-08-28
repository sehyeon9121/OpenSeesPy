import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisResult, AnalysisStatus, NodeResult, TimeHistoryStep
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter

_EXAMPLE = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "examples"
    / "cantilever_frame_3d.py"
)


def test_incremental_deformation_matches_set_result_positions() -> None:
    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(_EXAMPLE)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)

    step = TimeHistoryStep(
        time=0.1,
        node_results={
            1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
            2: NodeResult(2, displacement=(0.01, -0.005, 0.02)),
        },
    )
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, time_history=(step,))
    scale = 25.0

    reference = Quick3DSceneBridge()
    reference.set_model(model)
    reference.set_result(
        model,
        AnalysisResult(status=AnalysisStatus.COMPLETED, node_results=step.node_results),
        scale,
        show_undeformed=True,
    )

    bridge.begin_time_history_deformation(model, show_original=True, show_deformed=True)
    deformed_points = {}
    magnitudes = {}
    for tag, base in bridge._points.items():
        node_result = step.node_results.get(tag)
        displacement = node_result.displacement if node_result is not None else ()
        padded = (*displacement, 0.0, 0.0, 0.0)
        ux, uy, uz = padded[0], padded[1], padded[2]
        magnitudes[tag] = (ux * ux + uy * uy + uz * uz) ** 0.5
        offset = Quick3DSceneBridge._view_coordinates(ux, uy, uz)
        deformed_points[tag] = tuple(
            base[index] + offset[index] * scale for index in range(3)
        )
    peak = max(magnitudes.values(), default=0.0)
    ratios = {
        tag: 0.0 if peak <= 1.0e-12 else magnitude / peak for tag, magnitude in magnitudes.items()
    }
    bridge.update_deformed_node_positions(
        deformed_points, show_original=True, show_deformed=True, node_ratios=ratios
    )

    for ref_node, inc_node in zip(reference.nodes, bridge.nodes, strict=True):
        assert ref_node["tag"] == inc_node["tag"]
        assert inc_node["x"] == pytest.approx(float(ref_node["x"]))
        assert inc_node["y"] == pytest.approx(float(ref_node["y"]))
        assert inc_node["z"] == pytest.approx(float(ref_node["z"]))


def test_end_deformation_restores_default_geometry() -> None:
    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=10).load(_EXAMPLE)
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    default_node = dict(bridge.nodes[0])

    bridge.begin_time_history_deformation(model)
    bridge.update_deformed_node_positions(
        {2: (999.0, 999.0, 999.0)},
        show_original=True,
        show_deformed=True,
    )
    bridge.end_time_history_deformation()

    assert bridge.timeHistoryDeformationActive is False
    assert bridge.nodes[0]["x"] == pytest.approx(default_node["x"])
