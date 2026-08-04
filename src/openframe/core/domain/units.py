"""Consistent unit declarations for unitless OpenSees models."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UnitSystem:
    force: str
    length: str

    @property
    def key(self) -> str:
        return f"{self.force.lower()}_{self.length.lower()}"

    @property
    def label(self) -> str:
        return f"{self.force}, {self.length}"

    @property
    def moment(self) -> str:
        return f"{self.force}·{self.length}"


FORCE_UNITS = ("kN", "N", "kip")
LENGTH_UNITS = ("m", "mm", "ft", "in")
DEFAULT_UNIT_SYSTEM = UnitSystem(force=FORCE_UNITS[0], length=LENGTH_UNITS[0])
