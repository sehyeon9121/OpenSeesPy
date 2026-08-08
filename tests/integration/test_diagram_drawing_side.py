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
from openframe.features.analysis.statics.solver import MaterialFreeStaticsSolver
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
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


def test_compression_is_drawn_outside_the_frame_on_both_columns() -> None:
    """Compression is negative and plots on the outer face, per explicit user request
    to swap the axial diagram to the opposite side from where it used to draw.

    Both columns must land outside even though one is traversed upward and the other
    downward, which is what following the hand-solution member order achieves.
    """
    outlines = _outline_points(DiagramKind.AXIAL)

    # Left column sits at x=0, right column at x=7; outside is x < 0 or x > 7.
    for element_tag in (1, 2, 5):
        assert all(x < 0.0 or x > 7.0 for x, _ in outlines[element_tag]), (
            f"element {element_tag} axial diagram fell inside the frame"
        )


def test_member_carrying_no_axial_force_gets_no_sign_or_label() -> None:
    """Regression: 2e-12 of solver noise on the beam used to print a stray '+'.

    The beam of the textbook frame carries no horizontal thrust (only a vertical
    roller at B), so its true axial force is zero; OpenSees reports it as ~1e-12.
    """
    outlines = _outline_points(DiagramKind.AXIAL)
    assert 3 in outlines  # the beam still has a (flat) diagram outline

    QApplication.instance() or QApplication([])
    model = OpenSeesModelImporter(timeout_seconds=20).load(SOURCE)
    result = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=SOURCE))
    scene = QGraphicsScene()
    FrameDiagramRenderer().render(scene, model, result, DiagramKind.AXIAL, 50, "kN")

    beam_markers = [
        item
        for item in scene.items()
        if isinstance(item.data(0), tuple)
        and item.data(0)[0] in ("result_diagram_sign", "result_diagram_label")
        and item.data(0)[1] == 3
    ]
    assert beam_markers == []


def test_sagging_beam_moment_is_drawn_below_the_beam() -> None:
    outlines = _outline_points(DiagramKind.MOMENT)

    # Both beam halves carry positive (sagging) moment, so the BMD hangs below the member.
    for element_tag in (3, 4):
        assert any(y > BEAM_SCREEN_Y for _, y in outlines[element_tag])
        assert all(y >= BEAM_SCREEN_Y - 1e-9 for _, y in outlines[element_tag])


def _bridge_items(kind: DiagramKind):
    QApplication.instance() or QApplication([])
    canvas = StaticsDrawingCanvas()
    n1 = canvas.add_node(0.0, 0.0)
    n2 = canvas.add_node(0.0, 4.0)
    n3 = canvas.add_node(9.0, 4.0)
    n4 = canvas.add_node(9.0, 0.0)
    canvas.add_member(n1, n2)
    top = canvas.add_member(n2, n3)
    canvas.add_member(n3, n4)
    hinge = canvas.add_member_station_node(top, 1.0 / 3.0)
    branch = canvas.add_member_station_node(top, 2.0 / 3.0)
    canvas.selected_nodes = {hinge}
    canvas.set_selected_node_kind(True)
    n7 = canvas.add_node(6.0, 2.0)
    n8 = canvas.add_node(4.0, 2.0)
    canvas.add_member(branch, n7)
    canvas.add_member(n7, n8)
    canvas.set_support(n1, (True, True, False))
    canvas.set_support(n4, (True, True, False))
    canvas.set_nodal_load(n8, (0.0, -20.0, 0.0))

    model = canvas.build_model()
    result = MaterialFreeStaticsSolver().solve(model)
    scene = QGraphicsScene()
    FrameDiagramRenderer().render(scene, model, result, kind, 50, "kN·m")
    return [
        item
        for item in scene.items()
        if isinstance(item.data(0), tuple) and item.data(0)[0] == "result_diagram_bridge"
    ]


def test_a_branch_point_gets_a_bridge_between_the_two_collinear_diagram_lobes() -> None:
    """A member branching off a beam (a stem hanging below it, here) legitimately makes
    the beam's own moment jump between its two collinear halves at that node - both
    values are real, but two independently-closed polygons with nothing drawn between
    their tips at the same point used to read as "the diagram broke" (reported by a
    user as the moment "becoming 0" there) rather than "the diagram stepped"."""
    bridges = _bridge_items(DiagramKind.MOMENT)
    assert bridges, "expected a bridge connecting the two beam halves at the branch node"


def test_no_bridge_is_drawn_at_the_hinge_where_both_sides_already_agree() -> None:
    """The hinge sits between two collinear segments too, but both read 0 there (that's
    what a hinge means) - a bridge would be a zero-length no-op, so none should be drawn."""
    bridges = _bridge_items(DiagramKind.MOMENT)
    # Every bridge in this model belongs to the single branch node, not the hinge -
    # cheapest way to assert that is checking there is exactly one branch point's worth.
    assert len(bridges) == 2  # one connecting line + one connecting fill triangle
