"""Numeric coordinate entry used while drawing.

Free-form structural problems are given as lengths and angles rather than pixel
positions, so every point the user can reach with the mouse must also be reachable
by typing.  These helpers turn a typed entry into a model-space point.
"""

import math
import re
from enum import StrEnum

Point = tuple[float, float]

_SEPARATOR = re.compile(r"[,\s]+")


class EntryMode(StrEnum):
    """How a two-field numeric entry is interpreted against the anchor."""

    POLAR = "polar"
    RELATIVE = "relative"
    ABSOLUTE = "absolute"


def polar_point(anchor: Point, length: float, angle_degrees: float) -> Point:
    """Return the point at ``length`` from ``anchor`` measured counter-clockwise."""
    radians = math.radians(angle_degrees)
    return (
        anchor[0] + length * math.cos(radians),
        anchor[1] + length * math.sin(radians),
    )


def relative_point(anchor: Point, dx: float, dy: float) -> Point:
    return (anchor[0] + dx, anchor[1] + dy)


def resolve_fields(
    mode: EntryMode, anchor: Point, first: float, second: float
) -> Point:
    """Resolve the two numeric fields shown next to the cursor."""
    if mode is EntryMode.POLAR:
        return polar_point(anchor, first, second)
    if mode is EntryMode.RELATIVE:
        return relative_point(anchor, first, second)
    return (first, second)


def parse_entry(
    text: str, anchor: Point, direction_degrees: float | None = None
) -> Point | None:
    """Parse a single typed entry into a model-space point.

    Accepted forms, following the conventions drafting users already know:

    - ``5<30``  length 5 at 30 degrees from the anchor
    - ``@3,4``  offset from the anchor
    - ``3,4``   absolute model coordinates
    - ``5``     length 5 along the current cursor direction

    Returns ``None`` when the text is not a complete entry, so a caller can keep
    accepting keystrokes without having to pre-validate them.
    """
    cleaned = text.strip()
    if not cleaned:
        return None

    if "<" in cleaned:
        length_text, _, angle_text = cleaned.partition("<")
        length = _number(length_text)
        angle = _number(angle_text)
        if length is None or angle is None:
            return None
        return polar_point(anchor, length, angle)

    relative = cleaned.startswith("@")
    if relative:
        cleaned = cleaned[1:].strip()

    parts = [part for part in _SEPARATOR.split(cleaned) if part]
    if len(parts) == 1:
        length = _number(parts[0])
        if length is None or direction_degrees is None:
            return None
        return polar_point(anchor, length, direction_degrees)
    if len(parts) != 2:
        return None

    first = _number(parts[0])
    second = _number(parts[1])
    if first is None or second is None:
        return None
    return relative_point(anchor, first, second) if relative else (first, second)


def direction_degrees(anchor: Point, point: Point) -> float:
    """Angle of ``point`` seen from ``anchor``, in degrees within (-180, 180]."""
    return math.degrees(math.atan2(point[1] - anchor[1], point[0] - anchor[0]))


def distance(anchor: Point, point: Point) -> float:
    return math.hypot(point[0] - anchor[0], point[1] - anchor[1])


def _number(text: str) -> float | None:
    try:
        return float(text.strip())
    except ValueError:
        return None
