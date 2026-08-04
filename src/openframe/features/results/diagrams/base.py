"""Shared force-diagram values; no Qt drawing objects are allowed here."""

from dataclasses import dataclass
from enum import StrEnum


class DiagramKind(StrEnum):
    AXIAL = "axial"
    SHEAR = "shear"
    MOMENT = "moment"


@dataclass(frozen=True, slots=True)
class DiagramPoint:
    position: float
    value: float


@dataclass(frozen=True, slots=True)
class MemberDiagram:
    element_tag: int
    kind: DiagramKind
    points: tuple[DiagramPoint, ...]

