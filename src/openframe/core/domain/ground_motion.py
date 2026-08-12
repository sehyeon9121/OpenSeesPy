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


@dataclass(frozen=True, slots=True)
class GroundMotion:
    """One loaded ground-motion acceleration record, ready for time-history
    analysis - the shape ``load_ground_motion()`` returns for *any* file it
    can parse (a strict PEER .AT2 header, or a looser NPTS/DT-header / plain
    two-column txt/csv/dat).

    Deliberately not the same type as :class:`GroundMotionRecord`: that one
    is catalog metadata parsed from a strict 4-line PEER header before the
    value series is even read (event/date/station/component included, from
    the built-in/custom .AT2 library). This type is what every supported
    import format can actually deliver - the acceleration series itself plus
    only the facts that are honestly derivable from it - so it has no
    event/date/station/component fields. Direction and scale factor are
    deliberately not here either: those are how a motion is *applied* to one
    particular analysis run, already owned by ``AnalysisConfigStore``.
    """

    name: str
    path: Path
    accelerations: tuple[float, ...]
    dt: float
    #: Best-effort, from a "UNITS OF ..." header line when present (PEER-style
    #: files). ``None`` for plain txt/csv/dat files, which carry no unit label
    #: at all - reporting a guessed unit would be worse than admitting it is
    #: unknown.
    unit: str | None = None

    @property
    def npts(self) -> int:
        return len(self.accelerations)

    @property
    def duration(self) -> float:
        return self.dt * max(self.npts - 1, 0)

    @property
    def pga(self) -> float:
        """Peak ground acceleration - the largest absolute value in the
        series, in whatever unit the file itself uses."""
        return max((abs(value) for value in self.accelerations), default=0.0)

    @classmethod
    def from_record(
        cls, record: GroundMotionRecord, accelerations: tuple[float, ...]
    ) -> "GroundMotion":
        """Build the same shape a Browse-imported file produces, from a
        built-in catalog entry plus its already-loaded value series - so
        SETUP's info display/preview/scaling never need to know whether a
        motion came from the catalog or the user's own disk."""
        return cls(
            name=f"{record.event} — {record.station} ({record.component})",
            path=record.path,
            accelerations=accelerations,
            dt=record.dt,
            unit=record.units,
        )
