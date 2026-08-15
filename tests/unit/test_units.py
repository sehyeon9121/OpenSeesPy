"""Unit tests for core/domain/units.py's acceleration unit conversion -
Time History's Ground Motion "Unit" dropdown (g / m/s^2 / cm/s^2 / model)."""

import pytest

from openframe.core.domain.units import (
    STANDARD_GRAVITY_M_S2,
    acceleration_to_model_unit_factor,
)


def test_model_unit_is_the_identity_conversion() -> None:
    assert acceleration_to_model_unit_factor("model", "m") == 1.0
    assert acceleration_to_model_unit_factor("model", "mm") == 1.0
    assert acceleration_to_model_unit_factor("model", "ft") == 1.0


def test_m_s2_unit_is_the_identity_conversion_for_a_meter_model() -> None:
    assert acceleration_to_model_unit_factor("m/s2", "m") == pytest.approx(1.0)


def test_g_to_meter_model_is_standard_gravity() -> None:
    assert acceleration_to_model_unit_factor("g", "m") == pytest.approx(STANDARD_GRAVITY_M_S2)


def test_cm_s2_to_meter_model_divides_by_one_hundred() -> None:
    assert acceleration_to_model_unit_factor("cm/s2", "m") == pytest.approx(0.01)


def test_g_to_millimeter_model_scales_by_one_thousand() -> None:
    # 1 g = 9.80665 m/s^2 = 9806.65 mm/s^2
    assert acceleration_to_model_unit_factor("g", "mm") == pytest.approx(
        STANDARD_GRAVITY_M_S2 * 1000.0
    )


def test_g_to_feet_model_uses_the_shared_length_unit_table() -> None:
    # 1 m = 1000/304.8 ft, so 1 g in ft/s^2 = 9.80665 * 1000 / 304.8.
    expected = STANDARD_GRAVITY_M_S2 * 1000.0 / 304.8
    assert acceleration_to_model_unit_factor("g", "ft") == pytest.approx(expected)


def test_conversion_factor_is_always_positive_for_every_supported_unit() -> None:
    for unit in ("g", "m/s2", "cm/s2", "model"):
        for length_unit in ("m", "mm", "ft", "in"):
            assert acceleration_to_model_unit_factor(unit, length_unit) > 0.0
