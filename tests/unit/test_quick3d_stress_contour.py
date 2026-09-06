"""3D stress overlay must grade |σ| along a member, not paint the peak."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    BoundaryCondition,
    Element,
    ElementResult,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.stress import member_stress_stations
from openframe.features.viewport.presentation.quick3d_scene_bridge import (
    Quick3DSceneBridge,
    _color_for_ratio,
)


def _cantilever() -> tuple[StructuralModel, AnalysisResult]:
    length = 5.0
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, 0.0, 0.0, length, 6),
        },
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties={
                    "A": 0.15,
                    "Iy": 0.003125,
                    "Iz": 0.003125,
                    "height": 0.5,
                    "width": 0.5,
                },
            )
        },
        boundaries=[BoundaryCondition(1, (True, True, True, True, True, True))],
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
            2: NodeResult(2, displacement=(0.03, 0.0, 0.0, 0.0, 0.009, 0.0)),
        },
        element_results={
            1: ElementResult(
                1,
                local_forces=(
                    0.0, 0.0, 0.0, 0.0, 0.0, -10.0,
                    0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                ),
                length=length,
            )
        },
    )
    return model, result


def test_stress_contour_is_not_one_colour_along_a_cantilever() -> None:
    """The reported picture: the whole column one solid red even though σ
    falls from the fix to the free tip. Each tessellated cube has to pick
    up the station it sits on, not the member peak.
    """
    QApplication.instance() or QApplication([])
    model, result = _cantilever()
    stations = member_stress_stations(model.elements[1], result.element_results[1], ndm=3)
    assert stations is not None
    peak = max(stations)

    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    bridge.set_result(
        model,
        result,
        1.0,
        show_undeformed=True,
        member_magnitudes={1: peak},
        member_station_magnitudes={1: stations},
    )

    colors = [str(part["color"]) for part in bridge.members]
    assert len(colors) > 1
    assert colors[0] != colors[-1]
    assert colors[0] == _color_for_ratio(
        0.5 * (stations[0] + stations[1]) / peak
    )
    assert colors[-1] == _color_for_ratio(
        0.5 * (stations[-2] + stations[-1]) / peak
    )


def test_constant_axial_stress_stays_one_colour() -> None:
    """A truss is N/A everywhere; tessellating it into a fake gradient
    would invent variation the solver never produced.
    """
    QApplication.instance() or QApplication([])
    model = StructuralModel(
        ndm=3,
        ndf=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0, 3), 2: Node(2, 0.0, 0.0, 3.0, 3)},
        elements={1: Element(1, 1, 2, "truss", properties={"A": 0.01})},
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(1, displacement=(0.0, 0.0, 0.0)),
            2: NodeResult(2, displacement=(0.0, 0.0, 0.001)),
        },
        element_results={1: ElementResult(1, local_forces=(-5.0, 5.0), length=3.0)},
    )
    stations = member_stress_stations(model.elements[1], result.element_results[1], ndm=3)
    assert stations == (500.0, 500.0)

    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    bridge.set_result(
        model,
        result,
        1.0,
        show_undeformed=False,
        member_magnitudes={1: 500.0},
        member_station_magnitudes={1: stations},
    )

    colors = {str(part["color"]) for part in bridge.members}
    assert colors == {_color_for_ratio(1.0)}
