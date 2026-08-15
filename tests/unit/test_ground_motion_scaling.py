"""Unit tests for ground_motion_scaling.py's compute_ground_motion_scaling -
the single place both SETUP's readouts (Original PGA / Effective Scale
Factor) and the transient solver's actual ops.timeSeries "-factor" agree on."""

import pytest

from openframe.core.domain.units import STANDARD_GRAVITY_M_S2
from openframe.infrastructure.opensees.ground_motion_scaling import (
    compute_ground_motion_scaling,
)


def test_model_unit_direct_scale_factor_is_a_pure_passthrough() -> None:
    result = compute_ground_motion_scaling(
        original_pga_raw=0.4,
        unit="model",
        length_unit="m",
        scaling_method="factor",
        scale_factor=2.0,
    )
    assert result.unit_factor == pytest.approx(1.0)
    assert result.effective_scale == pytest.approx(2.0)
    assert result.total_factor == pytest.approx(2.0)
    assert result.original_pga_model_units == pytest.approx(0.4)


def test_model_unit_target_pga_derives_effective_scale() -> None:
    result = compute_ground_motion_scaling(
        original_pga_raw=0.5,
        unit="model",
        length_unit="m",
        scaling_method="target_pga",
        target_pga=1.0,
    )
    assert result.effective_scale == pytest.approx(2.0)
    assert result.total_factor == pytest.approx(2.0)


def test_g_unit_direct_scale_factor_folds_unit_conversion_into_total_factor() -> None:
    result = compute_ground_motion_scaling(
        original_pga_raw=1.0,
        unit="g",
        length_unit="m",
        scaling_method="factor",
        scale_factor=1.0,
    )
    assert result.unit_factor == pytest.approx(STANDARD_GRAVITY_M_S2)
    assert result.effective_scale == pytest.approx(1.0)
    assert result.total_factor == pytest.approx(STANDARD_GRAVITY_M_S2)
    assert result.original_pga_model_units == pytest.approx(STANDARD_GRAVITY_M_S2)


def test_g_unit_target_pga_reaches_the_requested_model_unit_peak() -> None:
    """Applying total_factor to the raw record's own peak must reproduce
    target_pga exactly - the self-consistency check that makes Target PGA
    scaling actually mean what it says, regardless of the record's own unit."""
    target_pga_m_s2 = 0.5 * STANDARD_GRAVITY_M_S2  # 0.5g expressed in m/s^2
    result = compute_ground_motion_scaling(
        original_pga_raw=1.0,  # a record whose raw values are normalized to 1g peak
        unit="g",
        length_unit="m",
        scaling_method="target_pga",
        target_pga=target_pga_m_s2,
    )
    reconstructed_peak = 1.0 * result.total_factor
    assert reconstructed_peak == pytest.approx(target_pga_m_s2)


def test_cm_s2_unit_conversion_and_direct_scale_compose_multiplicatively() -> None:
    result = compute_ground_motion_scaling(
        original_pga_raw=200.0,  # cm/s^2
        unit="cm/s2",
        length_unit="m",
        scaling_method="factor",
        scale_factor=1.5,
    )
    assert result.unit_factor == pytest.approx(0.01)
    assert result.original_pga_model_units == pytest.approx(2.0)
    assert result.effective_scale == pytest.approx(1.5)
    assert result.total_factor == pytest.approx(0.015)
