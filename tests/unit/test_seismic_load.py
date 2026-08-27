"""Equivalent Lateral Force (ELF) procedure - core/domain/seismic_load.py.

Every numeric check here is a hand-worked example, independent of the
implementation, following the same Cs/SDS/SD1/Cvx formulas KDS 41-17's
등가정적해석법 (and ASCE 7 Ch.12, which it was harmonized from) specify.
"""

import pytest

from openframe.core.domain import Element, Node, StructuralModel
from openframe.core.domain.seismic_load import (
    SeismicLoadParameters,
    StoryWeight,
    design_spectral_accelerations,
    distribute_seismic_force_by_height,
    distribution_exponent,
    equivalent_lateral_force,
    lumped_node_weights,
    seismic_response_coefficient,
)


def test_design_spectral_accelerations_is_two_thirds_of_fa_ss_and_fv_s1() -> None:
    sds, sd1 = design_spectral_accelerations(ss=1.5, fa=1.0, s1=0.6, fv=1.5)
    assert sds == pytest.approx((2.0 / 3.0) * 1.0 * 1.5)
    assert sd1 == pytest.approx((2.0 / 3.0) * 1.5 * 0.6)


def test_response_coefficient_hand_worked_example() -> None:
    """SDS=1.0, SD1=0.6, R=8, Ie=1.0, T=1.0s:
    Cs = min(1.0/8, 0.6/(1*8)) = min(0.125, 0.075) = 0.075
    floor = max(0.044*1.0*1.0, 0.01, 0.5*0.6/8) = max(0.044, 0.01, 0.0375) = 0.044
    Cs = max(0.075, 0.044) = 0.075 (the period cap governs, not the floor)."""
    cs = seismic_response_coefficient(sds=1.0, sd1=0.6, s1=0.6, r=8.0, ie=1.0, period=1.0)
    assert cs == pytest.approx(0.075)


def test_response_coefficient_floors_at_the_minimum_when_the_period_cap_does_not_bind() -> None:
    """A very short/stiff period never triggers the SD1/(T*R/Ie) cap, so the
    0.044*SDS*Ie floor (0.044*0.5*1.0=0.022) governs over the raw SDS/(R/Ie)
    (0.5/8=0.0625)... except 0.0625 > 0.022, so here the raw value governs -
    pick numbers where the floor actually binds instead: SDS=0.05."""
    cs = seismic_response_coefficient(sds=0.05, sd1=0.02, s1=0.05, r=8.0, ie=1.0, period=0.1)
    raw = 0.05 / 8.0
    floor = max(0.044 * 0.05 * 1.0, 0.01)
    assert raw < floor
    assert cs == pytest.approx(floor)


def test_response_coefficient_uses_the_high_s1_floor_when_it_governs() -> None:
    cs = seismic_response_coefficient(sds=0.05, sd1=0.6, s1=0.65, r=2.0, ie=1.0, period=5.0)
    ordinary_floor = max(0.044 * 0.05 * 1.0, 0.01)
    high_s1_floor = 0.5 * 0.65 / (2.0 / 1.0)
    assert high_s1_floor > ordinary_floor
    assert cs == pytest.approx(high_s1_floor)


def test_response_coefficient_rejects_non_positive_r_or_ie() -> None:
    with pytest.raises(ValueError):
        seismic_response_coefficient(sds=1.0, sd1=0.6, s1=0.6, r=0.0, ie=1.0, period=1.0)
    with pytest.raises(ValueError):
        seismic_response_coefficient(sds=1.0, sd1=0.6, s1=0.6, r=8.0, ie=0.0, period=1.0)


def test_distribution_exponent_interpolates_between_one_and_two() -> None:
    assert distribution_exponent(0.3) == pytest.approx(1.0)
    assert distribution_exponent(0.5) == pytest.approx(1.0)
    assert distribution_exponent(1.0) == pytest.approx(1.25)
    assert distribution_exponent(2.5) == pytest.approx(2.0)
    assert distribution_exponent(4.0) == pytest.approx(2.0)


def test_vertical_distribution_hand_worked_example_sums_to_the_base_shear() -> None:
    """k=1.25 (T=1.0s), two equal-weight stories at 3m and 6m:
    weighted_A = 1000*3^1.25, weighted_B = 1000*6^1.25, V=150."""
    stories = {"1F": StoryWeight(height=3.0, weight=1000.0), "2F": StoryWeight(height=6.0, weight=1000.0)}
    forces = distribute_seismic_force_by_height(150.0, stories, k=1.25)

    weighted_a = 1000.0 * 3.0**1.25
    weighted_b = 1000.0 * 6.0**1.25
    denominator = weighted_a + weighted_b
    assert forces["1F"] == pytest.approx(150.0 * weighted_a / denominator)
    assert forces["2F"] == pytest.approx(150.0 * weighted_b / denominator)
    assert sum(forces.values()) == pytest.approx(150.0)


def test_vertical_distribution_a_story_at_or_below_the_base_gets_no_force() -> None:
    stories = {
        "base": StoryWeight(height=0.0, weight=500.0),
        "1F": StoryWeight(height=3.0, weight=1000.0),
    }
    forces = distribute_seismic_force_by_height(100.0, stories, k=1.0)
    assert forces["base"] == 0.0
    assert forces["1F"] == pytest.approx(100.0)


def test_vertical_distribution_with_zero_total_weight_returns_all_zero_without_dividing_by_zero() -> None:
    stories = {"1F": StoryWeight(height=3.0, weight=0.0)}
    forces = distribute_seismic_force_by_height(100.0, stories, k=1.0)
    assert forces == {"1F": 0.0}


def test_equivalent_lateral_force_end_to_end_matches_the_hand_worked_pieces() -> None:
    parameters = SeismicLoadParameters(ss=1.5, s1=0.6, fa=1.0, fv=1.5, r=8.0, ie=1.0, period=1.0)
    stories = {"1F": StoryWeight(height=3.0, weight=1000.0), "2F": StoryWeight(height=6.0, weight=1000.0)}

    cs, base_shear, story_forces = equivalent_lateral_force(parameters, total_weight=2000.0, stories=stories)

    assert cs == pytest.approx(0.075)
    assert base_shear == pytest.approx(0.075 * 2000.0)
    assert sum(story_forces.values()) == pytest.approx(base_shear)


def test_lumped_node_weights_matches_half_of_each_members_own_weight() -> None:
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, 3.0)},
        elements={
            1: Element(
                1, 1, 2, "frame", properties={"density": 20.0, "A": 0.1, "E": 2.0e8}
            )
        },
    )

    weights = lumped_node_weights(model)

    expected_half = 20.0 * 0.1 * 3.0 / 2.0
    assert weights[1] == pytest.approx(expected_half)
    assert weights[2] == pytest.approx(expected_half)


def test_lumped_node_weights_skips_elements_missing_density_or_area() -> None:
    model = StructuralModel(
        ndm=3,
        nodes={1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 0.0, 0.0, 3.0)},
        elements={1: Element(1, 1, 2, "frame", properties={"E": 2.0e8})},
    )

    assert lumped_node_weights(model) == {}
