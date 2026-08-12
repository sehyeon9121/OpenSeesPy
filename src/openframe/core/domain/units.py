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
    def stress(self) -> str:
        return f"{self.force}/{self.length}²"

    @property
    def volumetric_force(self) -> str:
        return f"{self.force}/{self.length}³"


FORCE_UNITS = ("kN", "N", "kip")
LENGTH_UNITS = ("m", "mm", "ft", "in")
TIME_UNITS = ("s",)
DEFAULT_UNIT_SYSTEM = UnitSystem(force=FORCE_UNITS[0], length=LENGTH_UNITS[0])

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
