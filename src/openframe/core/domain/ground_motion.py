"""Ground-motion acceleration records available to time-history analysis."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class GroundMotionSource(StrEnum):
    BUILT_IN = "built_in"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class GroundMotionRecord:
    """Metadata for one PEER-format (.AT2) acceleration time series.

    Identical shape whether the record ships with the program or was picked
    by the user from their own disk - ``source`` is the only thing that
    distinguishes them, so time-history analysis can treat both the same way.
    """

    record_id: str
    event: str
    date: str
    station: str
    component: str
    units: str
    npts: int
    dt: float
    path: Path
    source: GroundMotionSource = GroundMotionSource.BUILT_IN

    @property
    def duration(self) -> float:
        return self.dt * max(self.npts - 1, 0)
