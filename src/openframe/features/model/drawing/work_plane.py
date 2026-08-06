"""Work planes: place a flat 2D drawing surface somewhere in 3D model space.

Clicking in empty 3D space is ambiguous — a screen point is a ray, not a point,
until it meets something. Rather than solve that with raycasting, free-form 3D
authoring keeps the same 2D canvas and asks it to draw onto whichever plane is
active: a "1F" plan at Z=0, a "2F" plan at Z=3.5, a front elevation at Y=0, and so
on. The plane is solely responsible for turning a 2D point the user clicked into
the 3D point that point actually means, and back.
"""

from dataclasses import dataclass
from enum import StrEnum

Point3 = tuple[float, float, float]
Point2 = tuple[float, float]

_ON_PLANE_TOLERANCE = 1.0e-6


class PlaneKind(StrEnum):
    XY = "xy"
    XZ = "xz"
    YZ = "yz"


@dataclass(frozen=True, slots=True)
class WorkPlane:
    """A plane parallel to two global axes, offset along the third.

    ``kind=XY`` is a horizontal plan view (a storey level) offset along Z.
    ``kind=XZ``/``YZ`` are vertical elevations, offset along Y or X — for drawing
    a frame's face or a bracing pattern directly instead of clicking level by level.
    """

    kind: PlaneKind = PlaneKind.XY
    offset: float = 0.0
    label: str = "1F"

    def to_3d(self, u: float, v: float) -> Point3:
        # Equality, not identity: PlaneKind is a StrEnum so a plain "xy" string
        # (e.g. one that came back out of a Qt widget's item data, which does not
        # reliably preserve enum identity across the QVariant boundary) must still
        # match — `is` would silently take the wrong branch in that case.
        if self.kind == PlaneKind.XY:
            return (u, v, self.offset)
        if self.kind == PlaneKind.XZ:
            return (u, self.offset, v)
        return (self.offset, u, v)

    def to_2d(self, point: Point3) -> Point2:
        x, y, z = point
        if self.kind == PlaneKind.XY:
            return (x, y)
        if self.kind == PlaneKind.XZ:
            return (x, z)
        return (y, z)

    def distance(self, point: Point3) -> float:
        """Perpendicular distance from ``point`` to this plane."""
        x, y, z = point
        if self.kind == PlaneKind.XY:
            return abs(z - self.offset)
        if self.kind == PlaneKind.XZ:
            return abs(y - self.offset)
        return abs(x - self.offset)

    def contains(self, point: Point3, tolerance: float = _ON_PLANE_TOLERANCE) -> bool:
        return self.distance(point) <= tolerance

    def moved_to(self, offset: float) -> "WorkPlane":
        """Same orientation, a different offset — one storey up, one bay over."""
        return WorkPlane(self.kind, offset, self.label)
