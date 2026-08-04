"""Pin which side of each member the N/V/M diagrams are drawn on.

Reference is the hand-drawn solution of examples/portal_frame_textbook_2d.py:
  S.F.D  beam left half V=+30 sits ABOVE the beam, right half V=-50 BELOW.
  B.M.D  beam moments are positive (sagging) and hang BELOW the beam (tension side).
Scene coordinates are screen-space, so +y points DOWN and the beam sits at y=-4.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication, QGraphicsScene

from openframe.core.domain import AnalysisRequest, AnalysisStatus
from openframe.features.results.diagrams import DiagramKind
from openframe.features.results.presentation.frame_diagram_renderer import (
    FrameDiagramRenderer,
)
from openframe.infrastructure.opensees.model_importer import OpenSeesModelImporter
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

SOURCE = Path(__file__).parents[2] / "examples" / "portal_frame_textbook_2d.py"
BEAM_SCREEN_Y = -4.0


def _outline_points(kind: DiagramKind) -> dict[int, list[tuple[float, float]]]:
    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=SOURCE))
    assert result.status == AnalysisStatus.COMPLETED, result.messages

    scene = QGraphicsScene()
    FrameDiagramRenderer().render(scene, model, result, kind, 50, "kN")

    outlines: dict[int, list[tuple[float, float]]] = {}
    for item in scene.items():
        identity = item.data(0)
        if isinstance(identity, tuple) and identity and identity[0] == "result_diagram_outline":
            path = item.path()
            outlines[identity[1]] = [
                (path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount())
            ]
    return outlines


def test_positive_shear_is_drawn_above_the_beam() -> None:
    outlines = _outline_points(DiagramKind.SHEAR)

    # Element 3 is the left half of the beam, V = +30 -> must plot ABOVE (smaller screen y).
    assert all(y < BEAM_SCREEN_Y for _, y in outlines[3])
    # Element 4 is the right half, V = -50 -> must plot BELOW.
    assert all(y > BEAM_SCREEN_Y for _, y in outlines[4])


def test_positive_shear_on_left_column_is_drawn_outside_the_frame() -> None:
    outlines = _outline_points(DiagramKind.SHEAR)

    # Element 1 is the lower left column (x = 0) with V = +35; the textbook draws it on the
    # outer face, i.e. to the left of the column.
    assert all(x < 0.0 for x, _ in outlines[1])


def test_compression_is_drawn_inside_the_frame_on_both_columns() -> None:
    """Compression is negative and plots on the inner face, as in the reference figure.

    Both columns must land inside even though one is traversed upward and the other
    downward, which is what following the hand-solution member order achieves.
    """
    outlines = _outline_points(DiagramKind.AXIAL)

    # Left column sits at x=0, right column at x=7; inside is 0 < x < 7.
    for element_tag in (1, 2, 5):
        assert all(0.0 < x < 7.0 for x, _ in outlines[element_tag]), (
            f"element {element_tag} axial diagram fell outside the frame"
        )


def test_sagging_beam_moment_is_drawn_below_the_beam() -> None:
    outlines = _outline_points(DiagramKind.MOMENT)

    # Both beam halves carry positive (sagging) moment, so the BMD hangs below the member.
    for element_tag in (3, 4):
        assert any(y > BEAM_SCREEN_Y for _, y in outlines[element_tag])
        assert all(y >= BEAM_SCREEN_Y - 1e-9 for _, y in outlines[element_tag])
