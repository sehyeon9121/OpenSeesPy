"""Common structural model representation produced by every importer."""

from dataclasses import dataclass, field
from enum import StrEnum


class SupportKind(StrEnum):
    FIXED = "fixed"
    PINNED = "pinned"
    ROLLER_VERTICAL = "roller_vertical"
    ROLLER_HORIZONTAL = "roller_horizontal"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class Node:
    tag: int
    x: float
    y: float
    ndf: int = 3


@dataclass(frozen=True, slots=True)
class Element:
    tag: int
    node_i: int
    node_j: int
    element_type: str
    properties: dict[str, float | str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BoundaryCondition:
    node_tag: int
    restraints: tuple[bool, ...]

    @property
    def support_kind(self) -> SupportKind:
        normalized = tuple(self.restraints[:3])
        if normalized == (True, True, True):
            return SupportKind.FIXED
        if normalized == (True, True, False):
            return SupportKind.PINNED
        if normalized == (False, True, False):
            return SupportKind.ROLLER_VERTICAL
        if normalized == (True, False, False):
            return SupportKind.ROLLER_HORIZONTAL
        return SupportKind.CUSTOM


@dataclass(frozen=True, slots=True)
class NodalLoad:
    node_tag: int
    values: tuple[float, ...]
    pattern_tag: int | None = None


@dataclass(frozen=True, slots=True)
class UniformElementLoad:
    element_tag: int
    wx: float = 0.0
    wy: float = 0.0
    pattern_tag: int | None = None


@dataclass(slots=True)
class StructuralModel:
    ndm: int = 2
    ndf: int = 3
    nodes: dict[int, Node] = field(default_factory=dict)
    elements: dict[int, Element] = field(default_factory=dict)
    boundaries: list[BoundaryCondition] = field(default_factory=list)
    nodal_loads: list[NodalLoad] = field(default_factory=list)
    element_loads: list[UniformElementLoad] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Return validation errors without depending on a GUI dialog."""
        errors: list[str] = []
        if self.ndm != 2:
            errors.append("현재 버전은 ndm=2 모델만 지원합니다.")
        for element in self.elements.values():
            if element.node_i not in self.nodes or element.node_j not in self.nodes:
                errors.append(f"부재 {element.tag}가 존재하지 않는 절점을 참조합니다.")
        return errors
