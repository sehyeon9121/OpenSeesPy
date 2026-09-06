"""3D result overlay must tessellate a frame's Hermite centreline."""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    BoundaryCondition,
    Element,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.deformation.deflected_shape import deflected_polyline
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge


def _point_line_distance(
    point: tuple[float, float, float],
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> float:
    direction = tuple(end[index] - start[index] for index in range(3))
    span = math.sqrt(sum(component * component for component in direction))
    if span <= 1.0e-12:
        return math.dist(point, start)
    offset = tuple(point[index] - start[index] for index in range(3))
    along = sum(offset[index] * direction[index] for index in range(3)) / (span * span)
    projected = tuple(start[index] + along * direction[index] for index in range(3))
    return math.dist(point, projected)


def test_deformed_3d_cantilever_is_not_drawn_as_a_straight_chord() -> None:
    """The reported 오류3.ofsm picture: yellow member as a perfect stick from
    the origin to the displaced tip. Analysis is a real 6-DOF cantilever;
    the overlay has to follow the rebuilt cubic, not the two end nodes.
    """
    QApplication.instance() or QApplication([])
    length = 5.0
    tip_ux = 0.03029510400218319
    tip_ry = 1.5 * tip_ux / length
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 0.0, 0.0, length, 6),
        },
        elements={1: Element(1, 2, 1, "frame")},
        boundaries=[BoundaryCondition(1, (True, True, True, True, True, True))],
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
            2: NodeResult(2, displacement=(tip_ux, 0.0, 0.0, 0.0, tip_ry, 0.0)),
        },
    )
    polyline = list(deflected_polyline(model, result, 1, scale=1.0))
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    bridge.set_result(
        model,
        result,
        1.0,
        show_undeformed=True,
        member_polylines={1: polyline},
    )

    nodes = {int(node["tag"]): node for node in bridge.nodes}
    start = (float(nodes[1]["x"]), float(nodes[1]["y"]), float(nodes[1]["z"]))
    end = (float(nodes[2]["x"]), float(nodes[2]["y"]), float(nodes[2]["z"]))
    assert len(bridge.members) > 1
    bow = [
        _point_line_distance(
            (float(part["x"]), float(part["y"]), float(part["z"])),
            start,
            end,
        )
        for part in bridge.members
    ]
    assert max(bow) > 1.0e-4
