"""End-to-end checks that solved results match hand-calculated statics."""

from pathlib import Path

import pytest

from openframe.core.domain import AnalysisRequest, AnalysisStatus
from openframe.features.results.diagrams import member_diagrams
from openframe.infrastructure.opensees.runner import OpenSeesProcessRunner

EXAMPLES = Path(__file__).parents[2] / "examples"


def _run(source: Path):
    result = OpenSeesProcessRunner(timeout_seconds=20).run(AnalysisRequest(source_path=source))
    assert result.status == AnalysisStatus.COMPLETED, result.messages
    return result


def _values(diagram) -> list[float]:
    return [point.value for point in diagram.points]


def test_simply_supported_beam_matches_hand_calculation() -> None:
    result = _run(EXAMPLES / "simply_supported_beam_2d.py")

    # Reactions: 5 kN up at each support, balancing the 10 kN downward load.
    assert result.node_results[1].reaction[1] == pytest.approx(5.0, abs=1e-6)
    assert result.node_results[3].reaction[1] == pytest.approx(5.0, abs=1e-6)

    _, left_shear, left_moment = member_diagrams(result.element_results[1])
    _, right_shear, right_moment = member_diagrams(result.element_results[2])

    # V = +P/2 on the left half, -P/2 on the right half.
    assert _values(left_shear) == pytest.approx([5.0, 5.0], abs=1e-6)
    assert _values(right_shear) == pytest.approx([-5.0, -5.0], abs=1e-6)

    # M = 0 at the supports and +PL/4 = +10 kN.m (sagging) at midspan, continuous there.
    assert _values(left_moment) == pytest.approx([0.0, 10.0], abs=1e-6)
    assert _values(right_moment) == pytest.approx([10.0, 0.0], abs=1e-6)


def test_portal_frame_columns_report_axial_not_shear() -> None:
    """Guards the global-vs-local end-force bug: columns are vertical, so reading
    global forces would swap N and V."""
    result = _run(EXAMPLES / "portal_frame_2d.py")

    # Applied load is Fx=20, Fy=-30 at node 4, so the two columns together must carry
    # 30 kN of vertical load as axial force, and 20 kN of horizontal load as shear.
    column_axials = []
    column_shears = []
    for tag in (1, 2):
        axial_diagram, shear_diagram, _ = member_diagrams(result.element_results[tag])
        column_axials.append(_values(axial_diagram)[0])
        column_shears.append(_values(shear_diagram)[0])

    # Axial is negative because both columns are in net compression under the downward load.
    assert sum(column_axials) == pytest.approx(-30.0, abs=1e-6)
    # Shear magnitude must equal the horizontal load; its sign follows the members' local
    # y-axis, which depends on the i->j direction, so only the magnitude is meaningful here.
    assert abs(sum(column_shears)) == pytest.approx(20.0, abs=1e-6)


def test_uniformly_loaded_beam_reports_the_span_moment_not_zero() -> None:
    """A single-element UDL span: both end moments are zero, the midspan is wL^2/8."""
    result = _run(EXAMPLES / "udl_beam_2d.py")

    # Reactions carry the whole 40 kN load, 20 kN at each support.
    assert result.node_results[1].reaction[1] == pytest.approx(20.0, abs=1e-6)
    assert result.node_results[2].reaction[1] == pytest.approx(20.0, abs=1e-6)

    element = result.element_results[1]
    assert element.length == pytest.approx(4.0)
    assert element.uniform_load == pytest.approx((0.0, -10.0, 0.0, -10.0))

    _, shear_diagram, moment_diagram = member_diagrams(element)
    moments = _values(moment_diagram)
    shears = _values(shear_diagram)

    assert moments[0] == pytest.approx(0.0, abs=1e-6)
    assert moments[-1] == pytest.approx(0.0, abs=1e-6)
    assert max(moments) == pytest.approx(20.0, abs=1e-6)  # wL^2/8
    assert shears[0] == pytest.approx(20.0, abs=1e-6)
    assert shears[-1] == pytest.approx(-20.0, abs=1e-6)


def test_textbook_portal_matches_shown_support_reactions() -> None:
    result = _run(EXAMPLES / "portal_frame_textbook_2d.py")

    reaction_a = result.node_results[1].reaction
    reaction_b = result.node_results[6].reaction

    # The reference figure shows 35 kN left and 30/50 kN upward at A/B.
    assert reaction_a[0] == pytest.approx(-35.0, abs=1e-6)
    assert reaction_a[1] == pytest.approx(30.0, abs=1e-6)
    assert reaction_a[2] == pytest.approx(0.0, abs=1e-6)
    assert reaction_b[0] == pytest.approx(0.0, abs=1e-6)
    assert reaction_b[1] == pytest.approx(50.0, abs=1e-6)
    assert reaction_b[2] == pytest.approx(0.0, abs=1e-6)
