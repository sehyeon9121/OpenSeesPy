"""Internal forces rebuilt along a member carrying a distributed load.

Each ``local_forces`` tuple was captured from OpenSeesPy for a problem whose closed-form
answer is known, so these tests pin the reconstruction rather than the engine's output.
"""

import pytest

from openframe.core.domain import ElementResult
from openframe.features.results.diagrams import max_abs_value, member_diagrams


def _at(diagram, position: float) -> float:
    return next(point.value for point in diagram.points if point.position == pytest.approx(position))


def test_simply_supported_udl_reaches_wl2_over_8_at_midspan() -> None:
    # L=4, w=10 down. Reactions 20 each; textbook M_max = wL^2/8 = 20 at midspan.
    element = ElementResult(
        element_tag=1,
        local_forces=(0.0, 20.0, 0.0, 0.0, 20.0, 0.0),
        length=4.0,
        uniform_load=(0.0, -10.0, 0.0, -10.0),
    )

    _, shear_diagram, moment_diagram = member_diagrams(element)

    assert _at(moment_diagram, 0.0) == pytest.approx(0.0, abs=1e-9)
    assert _at(moment_diagram, 0.5) == pytest.approx(20.0)
    assert _at(moment_diagram, 1.0) == pytest.approx(0.0, abs=1e-9)
    # Shear falls linearly from +wL/2 to -wL/2 and crosses zero at midspan.
    assert _at(shear_diagram, 0.0) == pytest.approx(20.0)
    assert _at(shear_diagram, 0.5) == pytest.approx(0.0, abs=1e-9)
    assert _at(shear_diagram, 1.0) == pytest.approx(-20.0)


def test_cantilever_udl_reaches_wl2_over_2_at_the_fixed_end() -> None:
    # L=4, w=10 down, fixed at end i. Textbook M = -wL^2/2 = -80 (hogging) at the support.
    element = ElementResult(
        element_tag=1,
        local_forces=(0.0, 40.0, 80.0, 0.0, 0.0, 0.0),
        length=4.0,
        uniform_load=(0.0, -10.0, 0.0, -10.0),
    )

    _, shear_diagram, moment_diagram = member_diagrams(element)

    assert _at(moment_diagram, 0.0) == pytest.approx(-80.0)
    assert _at(moment_diagram, 0.5) == pytest.approx(-20.0)  # -w(L/2)^2/2
    assert _at(moment_diagram, 1.0) == pytest.approx(0.0, abs=1e-9)
    assert _at(shear_diagram, 0.0) == pytest.approx(40.0)
    assert _at(shear_diagram, 1.0) == pytest.approx(0.0, abs=1e-9)


def test_span_maximum_is_reported_not_the_larger_end_value() -> None:
    """The whole point of the rebuild: both ends are zero but the span is not."""
    element = ElementResult(
        element_tag=1,
        local_forces=(0.0, 20.0, 0.0, 0.0, 20.0, 0.0),
        length=4.0,
        uniform_load=(0.0, -10.0, 0.0, -10.0),
    )

    _, _, moment_diagram = member_diagrams(element)

    assert max_abs_value([moment_diagram]) == pytest.approx(20.0)


def test_triangular_load_reaches_the_textbook_max_moment_off_centre() -> None:
    """Simply supported beam under a load ramping 0 (end i) -> w (end j) - the
    classic triangular-load case, whose closed-form peak moment does NOT sit at
    midspan (unlike a UDL): M_max = w*L^2/(9*sqrt(3)) at x = L/sqrt(3) from the
    zero-load end. L=6, w=12: R_i = wL/6 = 12 (by moments about end j - the
    resultant wL/2 acts at 2L/3 from end i), R_j = wL/3 = 24 (R_i + R_j = wL/2
    checks out: 12 + 24 = 36 = 12*6/2)."""
    length, peak = 6.0, 12.0
    reaction_i = peak * length / 6.0
    element = ElementResult(
        element_tag=1,
        local_forces=(0.0, reaction_i, 0.0, 0.0, 0.0, 0.0),
        length=length,
        uniform_load=(0.0, 0.0, 0.0, -peak),
    )

    _, shear_diagram, moment_diagram = member_diagrams(element)

    expected_position = 1.0 / 3.0 ** 0.5
    expected_moment = peak * length ** 2 / (9.0 * 3.0 ** 0.5)
    turning_point = max(moment_diagram.points, key=lambda point: point.value)
    assert turning_point.value == pytest.approx(expected_moment, rel=1e-9)
    assert turning_point.position == pytest.approx(expected_position, rel=1e-9)
    assert _at(shear_diagram, 0.0) == pytest.approx(reaction_i)
    assert _at(shear_diagram, expected_position) == pytest.approx(0.0, abs=1e-9)
    assert _at(moment_diagram, 0.0) == pytest.approx(0.0, abs=1e-9)
    assert _at(moment_diagram, 1.0) == pytest.approx(0.0, abs=1e-6)


def test_axial_distributed_load_varies_along_the_member() -> None:
    # wx = -5 over L=4 -> 20 total, carried at the fixed end and zero at the free end.
    element = ElementResult(
        element_tag=1,
        local_forces=(20.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        length=4.0,
        uniform_load=(-5.0, 0.0, -5.0, 0.0),
    )

    axial_diagram, _, _ = member_diagrams(element)

    assert _at(axial_diagram, 0.0) == pytest.approx(-20.0)
    assert _at(axial_diagram, 1.0) == pytest.approx(0.0, abs=1e-9)


def test_members_without_distributed_load_keep_the_two_point_diagram() -> None:
    element = ElementResult(
        element_tag=1,
        local_forces=(0.0, 1.0, 1.0, 0.0, -1.0, 0.0),
        length=1.0,
    )

    axial_diagram, shear_diagram, moment_diagram = member_diagrams(element)

    for diagram in (axial_diagram, shear_diagram, moment_diagram):
        assert len(diagram.points) == 2


def test_missing_length_falls_back_to_end_values_instead_of_dividing_by_zero() -> None:
    element = ElementResult(
        element_tag=1,
        local_forces=(0.0, 20.0, 0.0, 0.0, 20.0, 0.0),
        length=0.0,
        uniform_load=(0.0, -10.0, 0.0, -10.0),
    )

    _, _, moment_diagram = member_diagrams(element)

    assert len(moment_diagram.points) == 2
