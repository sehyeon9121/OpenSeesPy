"""Read PEER NGA strong-motion (.AT2) acceleration files.

Format (four header lines, then whitespace-separated values wrapped at a
fixed line width - never one value per line, so the value count only ever
matches ``NPTS`` once every line is re-joined and re-split)::

    PEER NGA STRONG MOTION DATABASE RECORD
    <event>, <date>, <station>, <component>
    ACCELERATION TIME SERIES IN UNITS OF <units>
    NPTS=<npts>, DT=<dt> SEC, ...
    <values...>
"""

import re
from dataclasses import dataclass
from pathlib import Path

_HEADER_LINES = 4
_NPTS_DT_PATTERN = re.compile(r"NPTS=\s*(\d+),\s*DT=\s*([0-9.]+)")
_UNITS_PATTERN = re.compile(r"UNITS OF\s*(\S+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PeerRecordHeader:
    event: str
    date: str
    station: str
    component: str
    units: str
    npts: int
    dt: float


class PeerFormatError(ValueError):
    """Raised when a file does not look like a PEER .AT2 record."""


def read_peer_header(path: Path) -> PeerRecordHeader:
    with path.open(encoding="utf-8", errors="replace") as handle:
        lines = [next(handle) for _ in range(_HEADER_LINES)]
    return _parse_header(lines, path)


def read_peer_at2(path: Path) -> tuple[PeerRecordHeader, tuple[float, ...]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    header = _parse_header(lines[:_HEADER_LINES], path)
    values = tuple(float(token) for line in lines[_HEADER_LINES:] for token in line.split())
    if len(values) != header.npts:
        raise PeerFormatError(
            f"{path.name}: NPTS={header.npts}이지만 실제 값 {len(values)}개를 읽었습니다."
        )
    return header, values


def _parse_header(lines: list[str], path: Path) -> PeerRecordHeader:
    if len(lines) < _HEADER_LINES:
        raise PeerFormatError(f"{path.name}: PEER 헤더가 4줄보다 짧습니다.")
    fields = [part.strip() for part in lines[1].split(",")]
    if len(fields) != 4:
        raise PeerFormatError(f"{path.name}: 두 번째 줄이 'event, date, station, component' 형식이 아닙니다.")
    event, date, station, component = fields

    units_match = _UNITS_PATTERN.search(lines[2])
    units = units_match.group(1) if units_match else "G"

    npts_dt_match = _NPTS_DT_PATTERN.search(lines[3])
    if not npts_dt_match:
        raise PeerFormatError(f"{path.name}: 네 번째 줄에서 NPTS/DT를 찾을 수 없습니다.")
    npts = int(npts_dt_match.group(1))
    dt = float(npts_dt_match.group(2))

    return PeerRecordHeader(
        event=event, date=date, station=station, component=component, units=units, npts=npts, dt=dt
    )
