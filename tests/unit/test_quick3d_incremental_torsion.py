import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from openframe.core.domain import (
    AnalysisResult,
    Element,
    Node,
    NodeResult,
    StructuralModel,
    TimeHistoryStep,
)
from openframe.features.results.deformation.deformed_3d_state import build_deformed_3d_state
from openframe.features.results.deformation.member_torsion_state import (
    build_member_torsion_state,
)
from openframe.features.viewport.presentation.quick3d_scene_bridge import Quick3DSceneBridge


def _model() -> StructuralModel:
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0),
            2: Node(2, 10.0, 0.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "elasticBeamColumn")},
    )


def _result() -> AnalysisResult:
    return AnalysisResult(
        time_history=(
            TimeHistoryStep(
                time=0.0,
                node_results={
                    1: NodeResult(1, displacement=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
                    2: NodeResult(2, displacement=(0.0, 0.0, 0.0, 0.1, 0.0, 0.0)),
                },
            ),
        )
    )


def test_torsion_marker_mode_preserves_list_identity() -> None:
    QApplication.instance() or QApplication([])
    model = _model()
    bridge = Quick3DSceneBridge()
    bridge.set_model(model)
    bridge.begin_torsion_marker_mode(model, marker_count=5)
    marker_ref = bridge.torsionMarkers
    assert len(marker_ref) == 5  # one Node delegate per station (y/z arms are children)

    deformed = build_deformed_3d_state(model, _result(), 0, 1.0)
    assert deformed is not None
    state = build_member_torsion_state(model, _result(), deformed, 0, 1.0, marker_count=5)
    assert state is not None
    bridge.update_torsion_markers(state.markers, visible=True)
    assert bridge.torsionMarkers is marker_ref
    assert bridge.torsionRevision >= 1

    bridge.update_torsion_markers(state.markers, visible=True)
    assert bridge.torsionMarkers is marker_ref
    assert bridge.torsionRevision >= 2


def test_torsion_markers_hidden_when_not_visible() -> None:
    QApplication.instance() or QApplication([])
    bridge = Quick3DSceneBridge()
    bridge.set_model(_model())
    bridge.begin_torsion_marker_mode(_model(), marker_count=3)
    bridge.update_torsion_markers((), visible=False)
    assert bridge.torsionMarkersVisible is False
