"""Sign-convention tests anchored to textbook statics answers.

Every ``local_forces`` tuple below was captured from OpenSeesPy's
``eleResponse(tag, "localForce")`` for a problem whose exact solution is known by hand,
so these tests pin the internal-force convention rather than whatever the engine emits.
"""

import pytest

from openframe.core.domain import ElementResult
from openframe.features.results.diagrams import max_abs_value, member_diagrams


def _values(diagram) -> list[float]:
    return [point.value for point in diagram.points]


def test_cantilever_tip_load_gives_hogging_moment() -> None:
    # Cantilever, L=1, fixed at end i, downward tip load P=1.
    # Textbook: N=0, V=+1 constant, M=-1 at the fixed end (hogging) rising to 0 at the tip.
    element = ElementResult(element_tag=1, local_forces=(0.0, 1.0, 1.0, 0.0, -1.0, 0.0))

    axial_diagram, shear_diagram, moment_diagram = member_diagrams(element)

    assert _values(axial_diagram) == pytest.approx([0.0, 0.0])
    assert _values(shear_diagram) == pytest.approx([1.0, 1.0])
    assert _values(moment_diagram) == pytest.approx([-1.0, 0.0])


def test_simply_supported_central_load_gives_sagging_moment() -> None:
    # Simply supported beam, L=4, central load P=10, modelled as two 2 m elements.
    # Textbook: R=5 each, M at midspan = PL/4 = +10 (sagging), V = +5 then -5.
    left = ElementResult(element_tag=1, local_forces=(0.0, 5.0, 0.0, 0.0, -5.0, 10.0))
    right = ElementResult(element_tag=2, local_forces=(0.0, -5.0, -10.0, 0.0, 5.0, 0.0))

    _, left_shear, left_moment = member_diagrams(left)
    _, right_shear, right_moment = member_diagrams(right)

    assert _values(left_shear) == pytest.approx([5.0, 5.0])
    assert _values(right_shear) == pytest.approx([-5.0, -5.0])
    # Moment must be continuous across the shared midspan node at the textbook +PL/4.
    assert _values(left_moment) == pytest.approx([0.0, 10.0])
    assert _values(right_moment) == pytest.approx([10.0, 0.0])


def test_tension_member_reports_positive_axial_force() -> None:
    # Vertical member pulled apart by +10; tension must read positive, not negative.
    element = ElementResult(element_tag=1, local_forces=(-10.0, 0.0, 0.0, 10.0, 0.0, 0.0))

    axial_diagram, _, _ = member_diagrams(element)

    assert _values(axial_diagram) == pytest.approx([10.0, 10.0])


def test_rejects_non_beam_column_force_shape() -> None:
    element = ElementResult(element_tag=2, local_forces=(1.0, 2.0, 3.0))

    with pytest.raises(ValueError):
        member_diagrams(element)


def test_max_abs_value_across_multiple_diagrams() -> None:
    elements = [
        ElementResult(element_tag=1, local_forces=(0.0, 1.0, 1.0, 0.0, -1.0, 0.0)),
        ElementResult(element_tag=2, local_forces=(5.0, 0.0, -3.0, -5.0, 0.0, 2.0)),
    ]
    diagrams = [member_diagrams(element)[0] for element in elements]

    assert max_abs_value(diagrams) == pytest.approx(5.0)
