"""Common structural model representation produced by every importer."""

import math
from dataclasses import dataclass, field
from enum import StrEnum

from openframe.core.domain.geometric_transform import GeometricTransform


class SupportKind(StrEnum):
    FIXED = "fixed"
    PINNED = "pinned"
    ROLLER_VERTICAL = "roller_vertical"
    ROLLER_HORIZONTAL = "roller_horizontal"
    CUSTOM = "custom"


class LoadCaseKind(StrEnum):
    """Semantic load categories explicitly declared by an imported model."""

    DEAD = "DEAD"
    LIVE = "LIVE"
    SEISMIC = "SEISMIC"
    WIND = "WIND"
    OTHER = "OTHER"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class Node:
    tag: int
    x: float
    y: float
    z: float = 0.0
    ndf: int = 3


@dataclass(frozen=True, slots=True)
class Element:
    tag: int
    node_i: int
    node_j: int
    element_type: str
    properties: dict[str, float | str] = field(default_factory=dict)
    moment_release_i: bool = False
    moment_release_j: bool = False
    #: Tag of the ``geomTransf(...)`` this element references, when it is one
    #: of the transformation-bearing beam-column types (``elasticBeamColumn``,
    #: ``dispBeamColumn``, ``forceBeamColumn``) and the reference could be
    #: parsed - look it up in ``StructuralModel.geometric_transforms``.
    #: ``None`` for non-beam-column elements or when parsing failed.
    transf_tag: int | None = None
    #: Tag of the ``beamIntegration(...)``/section this element references
    #: (``dispBeamColumn``/``forceBeamColumn`` only). ``None`` otherwise.
    integration_tag: int | None = None

    @property
    def release_count(self) -> int:
        """Released end conditions, subtracted by the determinacy count."""
        return int(self.moment_release_i) + int(self.moment_release_j)


@dataclass(frozen=True, slots=True)
class BoundaryCondition:
    """A support whose restrained directions may be rotated away from the global axes.

    ``restraints[0]`` and ``[1]`` constrain translation along a local frame rotated
    ``angle`` degrees counter-clockwise from global +X: local x' runs along the
    support surface, local y' is normal to it.  ``angle=0`` reduces exactly to the
    ordinary global-axis support this project always had, which is why every caller
    that never mentions ``angle`` keeps working unchanged.
    """

    node_tag: int
    restraints: tuple[bool, ...]
    angle: float = 0.0

    @property
    def is_inclined(self) -> bool:
        return not math.isclose(self.angle % 360.0, 0.0, abs_tol=1.0e-9)

    @property
    def support_kind(self) -> SupportKind:
        if self.is_inclined:
            return SupportKind.CUSTOM
        if len(self.restraints) >= 6:
            normalized_3d = tuple(self.restraints[:6])
            if normalized_3d == (True, True, True, True, True, True):
                return SupportKind.FIXED
            if normalized_3d == (True, True, True, False, False, False):
                return SupportKind.PINNED
            return SupportKind.CUSTOM
        normalized = tuple(self.restraints[:3])
        if normalized == (True, True, True):
            return SupportKind.FIXED
        if normalized == (True, True, False):
            return SupportKind.PINNED
        # Named for the axis the roller *restrains*, not the ground it rolls
        # along: a "vertical roller" blocks Ux (vertical rolling motion) while a
        # "horizontal roller" blocks Uy (horizontal rolling motion, resting flat
        # on the ground) — confirmed with the user, who found the opposite
        # mapping (naming by which axis stays free) counter-intuitive.
        if normalized == (True, False, False):
            return SupportKind.ROLLER_VERTICAL
        if normalized == (False, True, False):
            return SupportKind.ROLLER_HORIZONTAL
        return SupportKind.CUSTOM


@dataclass(frozen=True, slots=True)
class NodalLoad:
    node_tag: int
    values: tuple[float, ...]
    pattern_tag: int | None = None
    case_type: LoadCaseKind = LoadCaseKind.UNCLASSIFIED


@dataclass(frozen=True, slots=True)
class UniformElementLoad:
    """Linearly-varying distributed load along a member: w(x) = w_i + (w_j -
    w_i) * x/L for each axis, x measured from ``node_i``.

    A plain uniform load is simply w_i == w_j. The ``*_j`` fields default to
    the matching ``*_i`` value (not to zero) precisely so every existing call
    site that only ever set wx/wy/wz keeps meaning "uniform" without being
    touched — OpenSeesPy's own ``eleLoad -beamUniform`` has no linearly-
    varying form, so this is purely an OpenFrame-side extension for the
    determinate-structure solver and diagrams.
    """

    element_tag: int
    wx: float = 0.0
    wy: float = 0.0
    wz: float = 0.0
    wx_j: float | None = None
    wy_j: float | None = None
    wz_j: float | None = None
    pattern_tag: int | None = None
    case_type: LoadCaseKind = LoadCaseKind.UNCLASSIFIED

    def __post_init__(self) -> None:
        if self.wx_j is None:
            object.__setattr__(self, "wx_j", self.wx)
        if self.wy_j is None:
            object.__setattr__(self, "wy_j", self.wy)
        if self.wz_j is None:
            object.__setattr__(self, "wz_j", self.wz)

    @property
    def is_uniform(self) -> bool:
        return self.wx == self.wx_j and self.wy == self.wy_j and self.wz == self.wz_j


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
    #: Every ``ops.geomTransf(...)`` call collected from the model, keyed by
    #: tag - absent (``{}``) for models imported before this field existed
    #: (old payloads), which is why every reader treats it as optional.
    geometric_transforms: dict[int, GeometricTransform] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Return validation errors without depending on a GUI dialog."""
        errors: list[str] = []
        if self.ndm not in {1, 2, 3}:
            errors.append(f"지원하지 않는 모델 차원입니다: ndm={self.ndm}.")
        for element in self.elements.values():
            if element.node_i not in self.nodes or element.node_j not in self.nodes:
                errors.append(f"부재 {element.tag}가 존재하지 않는 절점을 참조합니다.")
        return errors
