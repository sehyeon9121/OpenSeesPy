"""Interior turning-point detection for the whole-frame N/V/M diagrams.

Regression coverage for a real bug: the old peak detector only labelled the
single largest interior point, and only when it beat *both* end values - so a
span whose support/end moments happen to be larger than its own genuine
interior sagging peak got no interior label at all, even though that peak is
exactly the number an engineer reading that span is looking for. Reported as
"모멘트 다이어그램에서 특정 구간 최대값 표시가 없어짐".
"""

from openframe.features.results.diagrams import DiagramKind, DiagramPoint, MemberDiagram
from openframe.features.results.presentation.frame_diagram_renderer import _interior_peaks


def _diagram(*values: float) -> MemberDiagram:
    points = tuple(
        DiagramPoint(position=index / (len(values) - 1), value=value)
        for index, value in enumerate(values)
    )
    return MemberDiagram(element_tag=1, kind=DiagramKind.MOMENT, points=points)


def test_a_sagging_peak_smaller_than_both_end_moments_still_counts_as_a_peak() -> None:
    """A span with large end (support) moments and a smaller interior sagging
    peak - e.g. a fixed-end beam under UDL, |M_end| > |M_mid| - must still get
    that interior peak labelled. This is exactly the case the old "only if it
    beats both ends" gate silently dropped."""
    diagram = _diagram(-80.0, -20.0, 10.0, -20.0, -80.0)

    assert _interior_peaks(diagram) == [2]


def test_a_straight_line_with_no_turning_point_gets_no_interior_peak() -> None:
    """A member with no distributed load (pure end moments) has a linear
    moment diagram - monotonic, no interior extremum to label."""
    diagram = _diagram(-10.0, -5.0, 0.0, 5.0, 10.0)

    assert _interior_peaks(diagram) == []


def test_two_genuine_turning_points_are_both_reported() -> None:
    """A linearly-varying (trapezoidal) load can give a shear diagram with two
    zero crossings, so the moment diagram can have two interior turning
    points - both must be labelled, not just the larger one."""
    diagram = _diagram(0.0, 12.0, 4.0, -12.0, -4.0, 0.0)

    assert _interior_peaks(diagram) == [1, 3]


def test_an_interior_peak_that_also_beats_both_ends_is_still_reported() -> None:
    """The common, simple case (simply-supported beam under UDL: zero at both
    ends, one clear interior maximum) must keep working exactly as before."""
    diagram = _diagram(0.0, 15.0, 20.0, 15.0, 0.0)

    assert _interior_peaks(diagram) == [2]
