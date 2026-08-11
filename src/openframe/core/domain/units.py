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
