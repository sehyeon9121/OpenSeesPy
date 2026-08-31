"""Shared force-diagram values; no Qt drawing objects are allowed here."""

from dataclasses import dataclass
from enum import StrEnum


class DiagramKind(StrEnum):
    AXIAL = "axial"
    SHEAR = "shear"
    MOMENT = "moment"


# Which side of the member each quantity is plotted on, following the drawing
# conventions used in structural mechanics. The 2D renderer treats ``normal``
# as -local_y, so:
#   V  -> -1 plots a positive value on the +local_y side (above a beam, and on
#         the outer face of a column), matching the usual S.F.D layout.
#   N  -> +1, the mirror of V's side. User request: swap the axial diagram to
#         the opposite face from where it used to draw (sign/values unaffected).
#   M  -> +1 keeps the bending moment on the tension side (a sagging beam
#         moment is drawn below the member), which is the 인장측 작도 convention.
# Only the plotted offset is affected; printed values keep their true sign.
# Shared with the 3D spatial strips so a member is not mirrored between views.
PLOT_SIDE = {
    DiagramKind.AXIAL: 1.0,
    DiagramKind.SHEAR: -1.0,
    DiagramKind.MOMENT: 1.0,
}


@dataclass(frozen=True, slots=True)
class DiagramPoint:
    position: float
    value: float


@dataclass(frozen=True, slots=True)
class MemberDiagram:
    element_tag: int
    kind: DiagramKind
    points: tuple[DiagramPoint, ...]

