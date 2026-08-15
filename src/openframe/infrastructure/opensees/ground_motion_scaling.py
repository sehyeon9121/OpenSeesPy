"""Ground-motion unit conversion and scaling for Time History.

One pure function computes exactly what SETUP displays (Original PGA,
Effective Scale Factor) and exactly what the transient solver multiplies a
record's raw values by (``total_factor``, fed to ``ops.timeSeries(...,
"-factor", ...)``) - so the two never compute it differently.

Unit conversion and the user's own scaling are each applied exactly once:
``unit_factor`` converts a raw record value (in whatever acceleration unit
the user picked for that direction) into this model's own acceleration unit;
``effective_scale`` is the user-controlled multiplier layered on top of that
already-unit-converted series (either typed directly, or derived from a
Target PGA expressed in the model's own acceleration unit). ``total_factor
= unit_factor * effective_scale`` is the single combined multiplier actually
applied to the record's raw values - never applied twice, never applied out
of order.
"""

from dataclasses import dataclass

from openframe.core.domain.units import acceleration_to_model_unit_factor


@dataclass(frozen=True, slots=True)
class GroundMotionScaling:
    #: Raw-record-unit -> model-acceleration-unit multiplier (1.0 for "model").
    unit_factor: float
    #: User-controlled multiplier, applied on top of the unit-converted series -
    #: the literal Scale Factor value, or (Target PGA mode) the value that
    #: reaches Target PGA. This is what SETUP labels "Effective Scale Factor".
    effective_scale: float
    #: unit_factor * effective_scale - the single multiplier actually passed to
    #: ops.timeSeries("Path", ..., "-factor", total_factor), applied to the
    #: record's raw (un-converted, un-scaled) values.
    total_factor: float
    #: original_pga_raw * unit_factor - the record's own peak, already
    #: converted (not yet scaled) into the model's own acceleration unit. What
    #: SETUP labels "Original PGA" and what Target PGA mode is measured against.
    original_pga_model_units: float


def compute_ground_motion_scaling(
    *,
    original_pga_raw: float,
    unit: str,
    length_unit: str,
    scaling_method: str,
    scale_factor: float = 1.0,
    target_pga: float = 0.0,
) -> GroundMotionScaling:
    """``scaling_method`` is ``"factor"`` (``scale_factor`` used directly as
    ``effective_scale``) or ``"target_pga"`` (``target_pga``, already
    expressed in the model's own acceleration unit, divided by
    ``original_pga_model_units`` to derive ``effective_scale``).

    Callers must validate ``original_pga_model_units > 0`` before requesting
    Target PGA scaling - this function does the arithmetic only, it does not
    guess at what a degenerate (zero-PGA) record should do.
    """
    unit_factor = acceleration_to_model_unit_factor(unit, length_unit)
    original_pga_model_units = original_pga_raw * unit_factor
    if scaling_method == "target_pga":
        effective_scale = target_pga / original_pga_model_units
    else:
        effective_scale = scale_factor
    return GroundMotionScaling(
        unit_factor=unit_factor,
        effective_scale=effective_scale,
        total_factor=unit_factor * effective_scale,
        original_pga_model_units=original_pga_model_units,
    )
