"""Consistent unit declarations for unitless OpenSees models."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UnitSystem:
    force: str
    length: str
    time: str = "s"

    @property
    def key(self) -> str:
        return f"{self.force.lower()}_{self.length.lower()}"

    @property
    def label(self) -> str:
        return f"{self.force}, {self.length}, {self.time}"

    @property
    def moment(self) -> str:
        return f"{self.force}·{self.length}"

    @property
    def force_per_length(self) -> str:
        """A member's own distributed-load intensity (e.g. a beam UDL) -
        force per unit length along the member, not the cross-sectional
        ``stress``/``volumetric_force`` below."""
        return f"{self.force}/{self.length}"

    @property
    def stress(self) -> str:
        return f"{self.force}/{self.length}²"

    @property
    def volumetric_force(self) -> str:
        return f"{self.force}/{self.length}³"


FORCE_UNITS = ("kN", "N", "kip")
LENGTH_UNITS = ("m", "mm", "ft", "in")
TIME_UNITS = ("s",)
DEFAULT_UNIT_SYSTEM = UnitSystem(force=FORCE_UNITS[0], length=LENGTH_UNITS[0])


@dataclass(frozen=True, slots=True)
class UnitConversionFactors:
    """Multiply a value expressed in the *old* unit system by the matching
    property here to get the same physical quantity expressed in the *new*
    one - see :func:`unit_conversion_factors`. Every compound factor is
    derived from just ``length``/``force`` so it can never drift out of sync
    with them the way a hand-maintained second copy could.
    """

    length: float
    force: float

    @property
    def area(self) -> float:
        return self.length**2

    @property
    def inertia(self) -> float:
        """A cross-section's second moment of area (Iy/Iz/J) - length^4."""
        return self.length**4

    @property
    def stress(self) -> float:
        return self.force / self.length**2

    @property
    def force_per_length(self) -> float:
        return self.force / self.length

    @property
    def unit_weight(self) -> float:
        return self.force / self.length**3

    @property
    def moment(self) -> float:
        return self.force * self.length

#: Standard gravity, matching the Material & Section Master DB's own ``Meta``
#: sheet (``GRAVITY`` = 9.80665 m/s^2) - kept here so every density/unit-weight
#: conversion in the program uses the same constant instead of each caller
#: hardcoding its own "9.81".
STANDARD_GRAVITY_M_S2 = 9.80665


def density_kg_m3_to_unit_weight_kN_m3(
    density_kg_m3: float, gravity_m_s2: float = STANDARD_GRAVITY_M_S2
) -> float:
    """Convert mass density to unit weight: ``rho * g / 1000`` (kg/m^3 * m/s^2
    -> N/m^3, then /1000 -> kN/m^3). Mirrors the Master DB spreadsheet's own
    ``unit_weight_kN_m3`` formula so both sides agree by construction."""
    return density_kg_m3 * gravity_m_s2 / 1000.0


#: The Material & Section Master DB always stores geometry in millimeters and
#: stress in MPa (N/mm^2), regardless of which of these a given model happens
#: to use - these two tables are the one place that fixed DB convention meets
#: this app's own free choice of force/length unit, so every DB-value
#: conversion below goes through them instead of each caller inventing its
#: own factor.
_LENGTH_TO_MM: dict[str, float] = {"m": 1000.0, "mm": 1.0, "ft": 304.8, "in": 25.4}
#: 1 kip = 4.4482216152605 kN exactly (the internationally defined pound-force).
_FORCE_TO_N: dict[str, float] = {"kN": 1000.0, "N": 1.0, "kip": 4448.2216152605}


def unit_conversion_factors(old: UnitSystem, new: UnitSystem) -> UnitConversionFactors:
    """Every already-entered value in a model must be rescaled when the app's
    own force/length unit changes, or a number that meant "500 kN" keeps its
    digits but silently means "500 N" instead - see
    ``canvas_units.py``'s ``convert_units``, the one place every one of these
    factors actually gets applied to stored model data."""
    return UnitConversionFactors(
        length=_LENGTH_TO_MM[old.length] / _LENGTH_TO_MM[new.length],
        force=_FORCE_TO_N[old.force] / _FORCE_TO_N[new.force],
    )


def mm_to_length_unit(value_mm: float, length_unit: str) -> float:
    """A Master DB length (millimeters) expressed in this model's own length
    unit - e.g. a Database section's ``H_mm`` shown correctly whether the
    model is in mm, m, ft, or in."""
    return value_mm / _LENGTH_TO_MM[length_unit]


def length_unit_to_mm(value: float, length_unit: str) -> float:
    """Inverse of :func:`mm_to_length_unit` - a value typed in this model's
    own length unit, converted to millimeters (the Master DB's/section
    geometry calculator's canonical unit)."""
    return value * _LENGTH_TO_MM[length_unit]


def mm2_to_length_unit(value_mm2: float, length_unit: str) -> float:
    return value_mm2 / _LENGTH_TO_MM[length_unit] ** 2


def mm4_to_length_unit(value_mm4: float, length_unit: str) -> float:
    return value_mm4 / _LENGTH_TO_MM[length_unit] ** 4


def mm3_to_length_unit(value_mm3: float, length_unit: str) -> float:
    """Same conversion as ``mm2_to_length_unit``/``mm4_to_length_unit``, for a
    plastic section modulus (mm^3) - see ``section_properties.SectionProperties.
    Zy_mm3``/``Zz_mm3``."""
    return value_mm3 / _LENGTH_TO_MM[length_unit] ** 3


def mpa_to_stress_unit(value_MPa: float, force_unit: str, length_unit: str) -> float:
    """A Master DB stress (MPa, i.e. N/mm^2) expressed in this model's own
    force/length^2 combination - e.g. a Database material's ``E_MPa`` shown
    as kN/m^2 for a model using kN and m."""
    return value_MPa * _LENGTH_TO_MM[length_unit] ** 2 / _FORCE_TO_N[force_unit]


def kN_m3_to_volumetric_force_unit(value_kN_m3: float, force_unit: str, length_unit: str) -> float:
    """A Master DB unit weight (kN/m^3) expressed in this model's own
    force/length^3 combination."""
    newtons_per_mm3 = value_kN_m3 * 1000.0 / _LENGTH_TO_MM["m"] ** 3
    return newtons_per_mm3 * _LENGTH_TO_MM[length_unit] ** 3 / _FORCE_TO_N[force_unit]


#: Ground-motion acceleration units Time History's SETUP lets a user pick per
#: direction - "model" means the record's own values are already expressed in
#: this model's own length/s^2 unit (no conversion applied at all).
ACCELERATION_UNITS = ("g", "m/s2", "cm/s2", "model")
#: 1 g / 1 m/s^2 / 1 cm/s^2 expressed in meters/s^2 - the only step where a
#: literal constant is introduced; every other acceleration unit conversion
#: goes through this dict plus the length-unit tables above, so a value never
#: gets its own separately-hardcoded g/cm conversion elsewhere in the program.
_ACCELERATION_TO_M_S2: dict[str, float] = {
    "g": STANDARD_GRAVITY_M_S2,
    "m/s2": 1.0,
    "cm/s2": 0.01,
}


def acceleration_to_model_unit_factor(unit: str, length_unit: str) -> float:
    """Multiplier converting a raw acceleration value expressed in ``unit``
    (one of :data:`ACCELERATION_UNITS`) into this model's own acceleration
    unit (``length_unit`` per second squared). ``"model"`` is the identity
    conversion - the record's values are already in the model's own unit."""
    if unit == "model":
        return 1.0
    value_m_s2 = _ACCELERATION_TO_M_S2[unit]
    return mm_to_length_unit(value_m_s2 * 1000.0, length_unit)
