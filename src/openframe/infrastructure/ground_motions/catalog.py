"""Built-in and user-supplied ground-motion catalogs, backed by PEER .AT2 files."""

from pathlib import Path

from openframe.core.domain import GroundMotionRecord, GroundMotionSource
from openframe.infrastructure.ground_motions.peer_format import read_peer_at2, read_peer_header

#: Bundled PEER NGA-West2 records shipped with the program - see data/README.md
#: for provenance. Only acceleration (.AT2) files are kept: time-history analysis
#: needs the acceleration record and its DT, not the derived velocity/displacement
#: series PEER also publishes alongside it.
_BUILT_IN_DATA_DIR = Path(__file__).parent / "data"


def _record_from_header(path: Path, source: GroundMotionSource) -> GroundMotionRecord:
    header = read_peer_header(path)
    return GroundMotionRecord(
        record_id=path.stem,
        event=header.event,
        date=header.date,
        station=header.station,
        component=header.component,
        units=header.units,
        npts=header.npts,
        dt=header.dt,
        path=path,
        source=source,
    )


class BuiltInGroundMotionCatalog:
    """Scans :data:`_BUILT_IN_DATA_DIR` once and serves the parsed metadata.

    Parsing only the four header lines per file keeps this cheap enough to run
    at startup - the full value series (tens of thousands of floats each) is
    only read on demand, in :meth:`load_series`.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or _BUILT_IN_DATA_DIR
        self._records: tuple[GroundMotionRecord, ...] | None = None

    def list_records(self) -> tuple[GroundMotionRecord, ...]:
        if self._records is None:
            paths = sorted(self._data_dir.glob("*.AT2"))
            self._records = tuple(
                _record_from_header(path, GroundMotionSource.BUILT_IN) for path in paths
            )
        return self._records

    def load_series(self, record: GroundMotionRecord) -> tuple[float, ...]:
        _, values = read_peer_at2(record.path)
        return values


def load_custom_ground_motion(path: Path) -> GroundMotionRecord:
    """Build a :class:`GroundMotionRecord` for a PEER .AT2 file the user picked
    themselves, outside the built-in catalog."""
    return _record_from_header(path, GroundMotionSource.CUSTOM)
