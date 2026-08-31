"""Elastic peak fibre stress used by the Results Stress colour map."""

import pytest

from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    Element,
    ElementResult,
    Node,
    StructuralModel,
)
from openframe.features.results.magnitudes import member_magnitudes
from openframe.features.results.stress import fibre_stress, member_end_stress, peak_member_stress


def test_beam_peak_stress_combines_axial_and_bending() -> None:
    # Rectangle 0.3 x 0.5 -> A=0.15, I=bh^3/12=0.003125, c=0.25
    element = Element(
        tag=1,
        node_i=1,
        node_j=2,
        element_type="elasticBeamColumn",
        properties={"A": 0.15, "I": 0.003125, "height": 0.5},
    )
    # Internal N=+30 (tension), M=+10 at both ends via end-force convention
    # local: N_i=-30, V=0, M_i=-10, N_j=+30, V=0, M_j=+10
    result = ElementResult(
        element_tag=1,
        local_forces=(-30.0, 0.0, -10.0, 30.0, 0.0, 10.0),
        length=4.0,
    )

    peak = peak_member_stress(element, result, ndm=2)

    # |N/A| + |M|c/I = 30/0.15 + 10*0.25/0.003125 = 200 + 800 = 1000
    assert peak == 1000.0


def test_truss_stress_is_axial_over_area_only() -> None:
    element = Element(
        tag=1,
        node_i=1,
        node_j=2,
        element_type="truss",
        properties={"A": 0.01},
    )
    result = ElementResult(element_tag=1, local_forces=(-5.0, 5.0), length=3.0)

    assert peak_member_stress(element, result, ndm=2) == 500.0


def test_missing_area_returns_none_rather_than_inventing_stress() -> None:
    element = Element(tag=1, node_i=1, node_j=2, element_type="elasticBeamColumn")
    result = ElementResult(
        element_tag=1, local_forces=(0.0, 0.0, 0.0, 0.0, 0.0, 10.0), length=4.0
    )

    assert peak_member_stress(element, result, ndm=2) is None


def test_member_magnitudes_stress_colours_assigned_sections_only() -> None:
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0), 3: Node(3, 8.0, 0.0)},
        elements={
            1: Element(
                1,
                1,
                2,
                "elasticBeamColumn",
                properties={"A": 0.15, "I": 0.003125, "height": 0.5},
            ),
            2: Element(2, 2, 3, "elasticBeamColumn"),  # no section -> omitted
        },
    )
    result = AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        element_results={
            1: ElementResult(1, (-30.0, 0.0, -10.0, 30.0, 0.0, 10.0), length=4.0),
            2: ElementResult(2, (0.0, 0.0, 0.0, 0.0, 0.0, 40.0), length=4.0),
        },
    )

    magnitudes = member_magnitudes(model, result, "stress")

    assert magnitudes == {1: 1000.0}


def test_missing_inertia_with_nonzero_moment_is_unavailable_not_axial_only() -> None:
    """A frame carrying moment but no I used to fall back to |N/A|, which
    under-reports fibre stress. Both contour and table must omit the value.
    """
    element = Element(
        tag=1,
        node_i=1,
        node_j=2,
        element_type="elasticBeamColumn",
        properties={"A": 0.01},
    )
    result = ElementResult(
        element_tag=1, local_forces=(-30.0, 0.0, -10.0, 30.0, 0.0, 10.0), length=4.0
    )

    assert peak_member_stress(element, result, ndm=2) is None
    assert member_end_stress(element, result, end="i", ndm=2) is None
    assert fibre_stress(element, axial_force=-30.0, moment=-10.0, ndm=2) is None


def test_table_end_stress_uses_the_same_fibre_stress_helper_as_the_contour() -> None:
    element = Element(
        tag=1,
        node_i=1,
        node_j=2,
        element_type="elasticBeamColumn",
        properties={"A": 0.15, "I": 0.003125, "height": 0.5},
    )
    result = ElementResult(
        element_tag=1,
        local_forces=(-30.0, 0.0, -10.0, 30.0, 0.0, 10.0),
        length=4.0,
    )

    i_stress = member_end_stress(element, result, end="i", ndm=2)
    j_stress = member_end_stress(element, result, end="j", ndm=2)
    assert i_stress == fibre_stress(element, axial_force=-30.0, moment=-10.0, ndm=2)
    assert j_stress == fibre_stress(element, axial_force=30.0, moment=10.0, ndm=2)
    # Contour peak is the larger |σ|; with this load that is 1000 at both ends.
    assert peak_member_stress(element, result, ndm=2) == pytest.approx(1000.0)
    assert abs(i_stress) == pytest.approx(1000.0)
    assert abs(j_stress) == pytest.approx(1000.0)
