import pytest

from openframe.core.domain import ElementResult
from openframe.features.results.diagrams import max_abs_value, member_diagrams


def test_cantilever_end_forces_produce_expected_diagrams() -> None:
    # Verified against openseespy directly: cantilever fixed at node 1, tip load -1 at
    # node 2, length 1 -> eleForce = [0, 1, 1, 0, -1, ~0].
    element = ElementResult(element_tag=1, local_forces=(0.0, 1.0, 1.0, 0.0, -1.0, -2.22e-16))

    axial_diagram, shear_diagram, moment_diagram = member_diagrams(element)

    assert [point.value for point in axial_diagram.points] == [0.0, 0.0]
    assert [point.value for point in shear_diagram.points] == pytest.approx([1.0, 1.0])
    moment_values = [point.value for point in moment_diagram.points]
    assert moment_values[0] == pytest.approx(1.0)
    assert moment_values[1] == pytest.approx(-2.22e-16, abs=1e-6)


def test_rejects_non_beam_column_force_shape() -> None:
    element = ElementResult(element_tag=2, local_forces=(1.0, 2.0, 3.0))

    with pytest.raises(ValueError):
        member_diagrams(element)


def test_max_abs_value_across_multiple_diagrams() -> None:
    elements = [
        ElementResult(element_tag=1, local_forces=(0.0, 1.0, 1.0, 0.0, -1.0, 0.0)),
        ElementResult(element_tag=2, local_forces=(5.0, 0.0, -3.0, -5.0, 0.0, 2.0)),
    ]
    diagrams = [diagram for element in elements for diagram in member_diagrams(element)[:1]]

    assert max_abs_value(diagrams) == pytest.approx(5.0)
