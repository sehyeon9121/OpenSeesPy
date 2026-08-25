"""A named, reusable bundle of (load case, magnitude) rows - MIDAS' "Floor
Load Type": a student defines one once (e.g. concrete self weight + floor
finish + live load, each its own case and kN/m^2 value), then applies every
row to a floor boundary's target nodes in a single step
(``canvas_load_entries.py``'s ``apply_floor_load_type``), which mints one
``FloorLoadEntry`` per row instead of repeating the single-value Floor Load
form once per case.

Deliberately narrower than MIDAS' own dialog: no "Sub Beam Weight" column
(this app has no unmodeled-sub-beam concept to hang it on), no per-row
direction/distribution (those stay shared across the whole application, on
``FloorLoadEntry`` itself, exactly as before this type existed).
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FloorLoadTypeRow:
    """One row - how much load ``case_id`` contributes, in the same
    force/area unit ``FloorLoadEntry.magnitude`` already uses.
    ``case_id=None`` is MIDAS' "NONE": an unused row, skipped when the type
    is applied."""

    case_id: str | None = None
    magnitude: float = 0.0


@dataclass(frozen=True, slots=True)
class FloorLoadType:
    """One named type a student defines in the Floor Load Type manager -
    ``id``/``name`` split mirrors ``LoadCase``'s own (id stable across a
    rename, name display-only)."""

    id: str
    name: str
    description: str = ""
    rows: tuple[FloorLoadTypeRow, ...] = ()
