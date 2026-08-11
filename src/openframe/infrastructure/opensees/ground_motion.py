"""Parse a ground-motion (acceleration time-history) file for transient analysis.

Supports the two shapes users actually run into:

1. PEER NGA-style: a header block containing an ``NPTS=`` / ``DT=`` line (any
   spacing/case - "NPTS= 3939, DT= .0050 SEC" and similar all match), followed
   by the acceleration values, any number of columns per line, until NPTS
   values have been read.
2. Plain two-column (time, acceleration) text/CSV - dt is inferred from the
   first two time values, and only the second column is kept (a ground-motion
   record has one acceleration value per time step, not per-node data).

Anything else raises a clear, actionable error rather than guessing.
"""

from __future__ import annotations

import re
from pathlib import Path

_NPTS_DT_PATTERN = re.compile(
    r"NPTS\s*[=:]\s*(?P<npts>\d+).*?DT\s*[=:]\s*(?P<dt>[\d.eE+-]+)",
    re.IGNORECASE | re.DOTALL,
)
_NUMBER_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_ground_motion(path: Path, *, dt: float | None = None) -> tuple[float, list[float]]:
    """Return ``(dt, accelerations)`` read from ``path``.

    ``dt`` is only used as a fallback for a single-column (accel-only) file -
    a PEER-style header or a two-column file both carry their own timing and
    ignore it.
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    header_match = _NPTS_DT_PATTERN.search(text)
    if header_match is not None:
        npts = int(header_match.group("npts"))
        file_dt = float(header_match.group("dt"))
        remainder = text[header_match.end() :]
        values = [float(token) for token in _NUMBER_PATTERN.findall(remainder)]
        if len(values) < npts:
            raise ValueError(
                f"헤더에 NPTS={npts}로 적혀 있지만 실제로는 {len(values)}개의 값만 "
                "읽었습니다. 파일이 잘렸거나 형식이 예상과 다를 수 있습니다."
            )
        return file_dt, values[:npts]

    rows = _parse_numeric_rows(text)
    if not rows:
        raise ValueError(
            "지진파 파일에서 숫자 데이터를 찾지 못했습니다. NPTS/DT 헤더가 있는 "
            "표준 형식이거나, (시간, 가속도) 두 열짜리 텍스트/CSV 파일이어야 합니다."
        )

    column_count = len(rows[0])
    if column_count >= 2:
        times = [row[0] for row in rows]
        accelerations = [row[1] for row in rows]
        inferred_dt = times[1] - times[0]
        if inferred_dt <= 0.0:
            raise ValueError("시간 열이 증가하는 순서가 아닙니다 - 첫 두 값의 시간 간격이 0 이하입니다.")
        return inferred_dt, accelerations

    if dt is None or dt <= 0.0:
        raise ValueError(
            "단일 열(가속도만 있는) 파일은 시간 간격(dt)을 직접 입력해야 합니다."
        )
    return dt, [row[0] for row in rows]


def _parse_numeric_rows(text: str) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in text.splitlines():
        tokens = _NUMBER_PATTERN.findall(line)
        if not tokens:
            continue
        try:
            rows.append([float(token) for token in tokens])
        except ValueError:
            continue
    if not rows:
        return []
    # Keep only the rows matching the most common column count in the file -
    # stray header/footer lines that happen to contain numbers (a station
    # elevation, a date) are the usual source of a differently-shaped row.
    counts = [len(row) for row in rows]
    common_count = max(set(counts), key=counts.count)
    return [row for row in rows if len(row) == common_count]
