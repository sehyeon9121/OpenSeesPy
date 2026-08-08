"""Each RESULT TYPE must draw something a user can tell apart from the others."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication

from openframe.core.domain import AnalysisRequest, AnalysisStatus
from openframe.features.results.presentation.result_viewport import ResultViewport
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

SOURCE = Path(__file__).parents[2] / "examples" / "portal_frame_textbook_2d.py"


def _viewport() -> ResultViewport:
    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=SOURCE))
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    viewport = ResultViewport()
    viewport.set_model(model)
    viewport.show_result(result)
    return viewport


def _overlay_kinds(viewport: ResultViewport) -> set[str]:
    kinds: set[str] = set()
    for item in viewport.scene.items():
        identity = item.data(0)
        if isinstance(identity, tuple) and identity and identity[0].startswith("result_"):
            kinds.add(identity[0])
    return kinds


def test_nodal_displacements_adds_markers_the_deformed_shape_does_not() -> None:
    viewport = _viewport()

    viewport.set_result_type("deformation")
    deformation_only = _overlay_kinds(viewport)

    viewport.set_result_type("displacement")
    with_displacements = _overlay_kinds(viewport)

    assert "result_node_displacement" not in deformation_only
    assert "result_node_displacement" in with_displacements
    assert "result_displacement_vector" in with_displacements


def test_every_moving_node_gets_a_marker() -> None:
    viewport = _viewport()
    viewport.set_result_type("displacement")

    markers = [
        item
        for item in viewport.scene.items()
        if isinstance(item.data(0), tuple)
        and item.data(0)[0] == "result_node_displacement"
    ]
    # The two pinned/roller bases do not translate; the other four nodes do.
    assert len(markers) == 5
    assert all(marker.displacement.moves for marker in markers)


def test_exactly_one_marker_is_flagged_as_the_peak() -> None:
    viewport = _viewport()
    viewport.set_result_type("displacement")

    markers = [
        item
        for item in viewport.scene.items()
        if isinstance(item.data(0), tuple)
        and item.data(0)[0] == "result_node_displacement"
    ]
    peaks = [marker for marker in markers if marker._is_peak]
    assert len(peaks) == 1
    assert peaks[0].displacement.magnitude == max(
        marker.displacement.magnitude for marker in markers
    )


def test_the_four_result_types_draw_different_overlays() -> None:
    viewport = _viewport()

    seen = {}
    for result_type in ("deformation", "displacement", "reaction", "moment"):
        viewport.set_result_type(result_type)
        seen[result_type] = _overlay_kinds(viewport)

    assert seen["deformation"] != seen["displacement"]
    assert seen["reaction"] != seen["deformation"]
    assert "result_reaction" in seen["reaction"]
    assert "result_diagram" in seen["moment"]
