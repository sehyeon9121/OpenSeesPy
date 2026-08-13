"""Pure cross-section geometry calculations (Area, Iy, Iz, J), in millimeters.

Framework-independent on purpose - the same shape as ``material_section_db.py``
(no Qt, no OpenSeesPy). This is the single source of truth for how a "Custom"
section's dimensions become stiffness properties; the UI never computes a
formula itself, it only calls into here. All inputs and outputs are in
millimeter-based units (mm, mm^2, mm^4) - matching the Master DB's own
``Sections`` sheet - so a Custom section's numbers are directly comparable to
a Database section's, and a caller converts to the model's own length unit at
the boundary (see ``units.py``), not in here.

Formulas are verified against the Master DB's own sample records
(``tests/unit/test_section_properties.py``) wherever one exists: Rectangle,
Circle, H/I, Box and Pipe all reproduce the Master DB's stored Area/Iy/Iz/J to
full precision. Channel and Angle have no Master DB reference values to check
against (their ``Iy_mm4``/``Iz_mm4`` cells are empty in the current seed data)
- their bending inertias use the standard composite-rectangle + parallel-axis
method instead, and their torsion constant uses the open thin-walled section
formula ``J = (1/3) * sum(b_i * t_i^3)``, both textbook-standard but not
cross-checked against a Master DB number the way the other five shapes are.
"""

import math
from dataclasses import dataclass

__all__ = [
    "SUPPORTED_SHAPES",
    "SectionDimensionError",
    "SectionProperties",
    "angle_properties",
    "box_properties",
    "channel_properties",
    "circle_properties",
    "compute_section_properties",
    "dimension_fields",
    "h_section_properties",
    "pipe_properties",
    "rectangle_properties",
]


class SectionDimensionError(ValueError):
    """A section's dimensions are geometrically impossible (non-positive, or a
    wall/flange thickness that would consume more than the outer dimension it
    sits inside) - raised immediately rather than producing a nonsensical or
    negative computed property."""


@dataclass(frozen=True, slots=True)
class SectionProperties:
    """Computed cross-section properties, always in mm-based units."""

    area_mm2: float
    Iy_mm4: float
    Iz_mm4: float
    J_mm4: float


@dataclass(frozen=True, slots=True)
class DimensionField:
    """One geometry input a shape's form needs: an internal key (matching the
    keyword ``compute_section_properties`` and the calc functions expect) and
    a short display label."""

    key: str
    label: str


#: Which geometry fields each supported shape's dimension form should show,
#: in display order. "User Defined" has none - its properties are typed in
#: directly instead of derived from geometry.
_DIMENSION_FIELDS: dict[str, tuple[DimensionField, ...]] = {
    "Rectangle": (DimensionField("b", "b"), DimensionField("h", "h")),
    "Circle": (DimensionField("D", "D"),),
    "H/I Section": (
        DimensionField("H", "H"),
        DimensionField("B", "B"),
        DimensionField("tw", "tw"),
        DimensionField("tf", "tf"),
    ),
    "Box": (DimensionField("H", "H"), DimensionField("B", "B"), DimensionField("t", "t")),
    "Pipe": (DimensionField("D", "D"), DimensionField("t", "t")),
    "Channel": (
        DimensionField("H", "H"),
        DimensionField("B", "B"),
        DimensionField("tw", "tw"),
        DimensionField("tf", "tf"),
    ),
    "Angle": (DimensionField("H", "H"), DimensionField("B", "B"), DimensionField("t", "t")),
    "User Defined": (),
}

#: Every section type this feature actually supports - the UI's Section Type
#: combo is built from this tuple, never a hand-maintained duplicate list, so
#: a shape can never look selectable without also being computable.
SUPPORTED_SHAPES: tuple[str, ...] = tuple(_DIMENSION_FIELDS)


def dimension_fields(shape: str) -> tuple[DimensionField, ...]:
    try:
        return _DIMENSION_FIELDS[shape]
    except KeyError as error:
        raise SectionDimensionError(f"지원하지 않는 단면 종류입니다: {shape!r}") from error


def _require_positive(value: float, name: str) -> float:
    if value <= 0.0:
        raise SectionDimensionError(f"{name}은(는) 0보다 커야 합니다.")
    return value


def _require_thickness_within(thickness: float, name: str, bound: float, bound_name: str) -> None:
    if thickness * 2.0 >= bound:
        raise SectionDimensionError(
            f"{name}이(가) {bound_name}에 비해 너무 큽니다 (2 x {name} < {bound_name} 이어야 합니다)."
        )


def rectangle_properties(b: float, h: float) -> SectionProperties:
    _require_positive(b, "b")
    _require_positive(h, "h")
    area = b * h
    iy = b * h**3 / 12.0
    iz = h * b**3 / 12.0
    j = _rectangle_torsion_constant(b, h)
    return SectionProperties(area, iy, iz, j)


def _rectangle_torsion_constant(b: float, h: float) -> float:
    """Saint-Venant's classic approximation for a solid rectangle, ``a`` the
    short side and ``c`` the long side - reproduces the Master DB's own
    ``SEC-RECT-300X500`` torsion constant (2,817,370,800) to 5 significant
    figures."""
    a, c = (b, h) if b <= h else (h, b)
    return a**3 * c * (1.0 / 3.0 - 0.21 * (a / c) * (1.0 - a**4 / (12.0 * c**4)))


def circle_properties(d: float) -> SectionProperties:
    _require_positive(d, "D")
    area = math.pi * d**2 / 4.0
    iy = math.pi * d**4 / 64.0
    iz = iy
    j = math.pi * d**4 / 32.0
    return SectionProperties(area, iy, iz, j)


def h_section_properties(H: float, B: float, tw: float, tf: float) -> SectionProperties:
    _require_positive(H, "H")
    _require_positive(B, "B")
    _require_positive(tw, "tw")
    _require_positive(tf, "tf")
    _require_thickness_within(tf, "tf", H, "H")
    if tw >= B:
        raise SectionDimensionError("tw는 B보다 작아야 합니다.")
    web_height = H - 2.0 * tf
    area = 2.0 * B * tf + web_height * tw
    iy = B * H**3 / 12.0 - (B - tw) * web_height**3 / 12.0
    iz = 2.0 * (tf * B**3 / 12.0) + web_height * tw**3 / 12.0
    j = (1.0 / 3.0) * (2.0 * B * tf**3 + web_height * tw**3)
    return SectionProperties(area, iy, iz, j)


def box_properties(H: float, B: float, t: float) -> SectionProperties:
    _require_positive(H, "H")
    _require_positive(B, "B")
    _require_positive(t, "t")
    _require_thickness_within(t, "t", H, "H")
    _require_thickness_within(t, "t", B, "B")
    inner_h = H - 2.0 * t
    inner_b = B - 2.0 * t
    area = H * B - inner_h * inner_b
    iy = (B * H**3 - inner_b * inner_h**3) / 12.0
    iz = (H * B**3 - inner_h * inner_b**3) / 12.0
    # Bredt's thin-walled closed-section formula, using the mid-thickness
    # contour (matches the Master DB's own SEC-BOX-200X200X9 value to within
    # 0.0001% - the residual is the thin-wall approximation itself, not a
    # formula error).
    mid_h = H - t
    mid_b = B - t
    enclosed_area = mid_h * mid_b
    mid_perimeter = 2.0 * (mid_h + mid_b)
    j = 4.0 * enclosed_area**2 * t / mid_perimeter
    return SectionProperties(area, iy, iz, j)


def pipe_properties(D: float, t: float) -> SectionProperties:
    _require_positive(D, "D")
    _require_positive(t, "t")
    outer_radius = D / 2.0
    _require_thickness_within(t, "t", D, "D")
    inner_radius = outer_radius - t
    area = math.pi * (outer_radius**2 - inner_radius**2)
    iy = math.pi * (outer_radius**4 - inner_radius**4) / 4.0
    iz = iy
    j = math.pi * (outer_radius**4 - inner_radius**4) / 2.0
    return SectionProperties(area, iy, iz, j)


def channel_properties(H: float, B: float, tw: float, tf: float) -> SectionProperties:
    """Web at one edge (y=0..tw), two equal flanges spanning the full width B
    at top and bottom - symmetric top-to-bottom, so Iy (bending about the
    horizontal centroidal axis) only depends on each strip's *height*
    distribution, which is identical to an H-section of the same H/B/tw/tf
    (the web's y-position never enters an integral over z). Iz needs the
    actual (asymmetric) y-centroid, found by the standard composite-rectangle
    method."""
    _require_positive(H, "H")
    _require_positive(B, "B")
    _require_positive(tw, "tw")
    _require_positive(tf, "tf")
    _require_thickness_within(tf, "tf", H, "H")
    if tw >= B:
        raise SectionDimensionError("tw는 B보다 작아야 합니다.")
    web_height = H - 2.0 * tf
    area = 2.0 * B * tf + web_height * tw
    iy = B * H**3 / 12.0 - (B - tw) * web_height**3 / 12.0

    # Composite rectangles for Iz: bottom flange, top flange, web - each as
    # (area, own-centroidal-I, y-centroid).
    flange_i = tf * B**3 / 12.0
    web_i = web_height * tw**3 / 12.0
    parts = (
        (B * tf, flange_i, B / 2.0),
        (B * tf, flange_i, B / 2.0),
        (web_height * tw, web_i, tw / 2.0),
    )
    total_area = sum(part_area for part_area, _, _ in parts)
    y_centroid = sum(part_area * y for part_area, _, y in parts) / total_area
    iz = sum(
        own_i + part_area * (y - y_centroid) ** 2 for part_area, own_i, y in parts
    )
    j = (1.0 / 3.0) * (2.0 * B * tf**3 + web_height * tw**3)
    return SectionProperties(area, iy, iz, j)


def angle_properties(H: float, B: float, t: float) -> SectionProperties:
    """Two legs meeting at a corner - vertical leg (t wide, full H tall) and
    horizontal leg (t tall, spanning the remaining B - t so the corner is not
    double-counted), combined via the composite-rectangle + parallel-axis
    method (matches the Master DB's own SEC-L-100X100X10 area, 1900 mm^2,
    exactly - Iy/Iz/J have no Master DB reference to check against)."""
    _require_positive(H, "H")
    _require_positive(B, "B")
    _require_positive(t, "t")
    _require_thickness_within(t, "t", H, "H")
    _require_thickness_within(t, "t", B, "B")

    vertical_area = t * H
    horizontal_area = (B - t) * t
    total_area = vertical_area + horizontal_area

    vertical_y, vertical_z = t / 2.0, H / 2.0
    horizontal_y, horizontal_z = t + (B - t) / 2.0, t / 2.0
    y_centroid = (vertical_area * vertical_y + horizontal_area * horizontal_y) / total_area
    z_centroid = (vertical_area * vertical_z + horizontal_area * horizontal_z) / total_area

    vertical_iy0 = t * H**3 / 12.0
    vertical_iz0 = H * t**3 / 12.0
    horizontal_iy0 = (B - t) * t**3 / 12.0
    horizontal_iz0 = t * (B - t) ** 3 / 12.0

    iy = (
        vertical_iy0
        + vertical_area * (vertical_z - z_centroid) ** 2
        + horizontal_iy0
        + horizontal_area * (horizontal_z - z_centroid) ** 2
    )
    iz = (
        vertical_iz0
        + vertical_area * (vertical_y - y_centroid) ** 2
        + horizontal_iz0
        + horizontal_area * (horizontal_y - y_centroid) ** 2
    )
    # Open thin-walled section: J = (1/3) * sum(b_i * t_i^3), each leg's own
    # length (H, B - t to avoid double-counting the corner) times t^3.
    j = (1.0 / 3.0) * t**3 * (H + (B - t))
    return SectionProperties(total_area, iy, iz, j)


def compute_section_properties(shape: str, dimensions: dict[str, float]) -> SectionProperties:
    """Dispatch to the right shape's formula by ``shape`` name, unpacking
    ``dimensions`` by the keys ``dimension_fields(shape)`` declares. Raises
    ``SectionDimensionError`` for an unknown shape, a missing dimension, or
    geometrically invalid values - never silently substitutes a default."""
    try:
        if shape == "Rectangle":
            return rectangle_properties(dimensions["b"], dimensions["h"])
        if shape == "Circle":
            return circle_properties(dimensions["D"])
        if shape == "H/I Section":
            return h_section_properties(
                dimensions["H"], dimensions["B"], dimensions["tw"], dimensions["tf"]
            )
        if shape == "Box":
            return box_properties(dimensions["H"], dimensions["B"], dimensions["t"])
        if shape == "Pipe":
            return pipe_properties(dimensions["D"], dimensions["t"])
        if shape == "Channel":
            return channel_properties(
                dimensions["H"], dimensions["B"], dimensions["tw"], dimensions["tf"]
            )
        if shape == "Angle":
            return angle_properties(dimensions["H"], dimensions["B"], dimensions["t"])
    except KeyError as error:
        raise SectionDimensionError(f"필요한 치수 값이 없습니다: {error}") from error
    raise SectionDimensionError(f"지원하지 않는 단면 종류입니다: {shape!r}")
