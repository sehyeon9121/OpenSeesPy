"""Immutable, engine-independent load compiler output (model force/length units)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from openframe.core.domain.model import LoadCaseKind

Vector3 = tuple[float, float, float]
ZERO: Vector3 = (0.0, 0.0, 0.0)


class LoadHandling(StrEnum):
    NATIVE_ELEMENT = "native_element"
    EQUIVALENT_NODAL = "equivalent_nodal"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class LoadSource:
    origin: str
    element_tag: int | None = None
    entry_id: int | None = None
    case_id: str | None = None
    pattern_tag: int | None = None
    case_type: LoadCaseKind = LoadCaseKind.UNCLASSIFIED


@dataclass(frozen=True, slots=True)
class ElementLoadTarget:
    """Source member, or one segment of a required uniform subdivision.

    A segment target is NOT an engine element tag. Consumers must build the
    subdivision and resolve this reference before emitting a native load. All
    loads on that member, including uniform/point/self weight, use these targets.
    """

    element_tag: int
    segment_index: int | None = None
    segment_count: int = 1

    @property
    def source_span(self) -> tuple[float, float]:
        if self.segment_index is None:
            return (0.0, 1.0)
        return (
            self.segment_index / self.segment_count,
            (self.segment_index + 1) / self.segment_count,
        )


@dataclass(frozen=True, slots=True)
class CompiledNodalLoad:
    node_tag: int
    force: Vector3  # GLOBAL (Fx, Fy, Fz), independent of solver ndf
    moment: Vector3 = ZERO  # GLOBAL (Mx, My, Mz); 2D uses Mz
    source: LoadSource = LoadSource("nodal")


@dataclass(frozen=True, slots=True)
class CompiledElementLoad:
    target: ElementLoadTarget
    kind: Literal["uniform", "point"]
    components: Vector3  # LOCAL (axial x, transverse y, transverse z)
    source: LoadSource
    start_ratio: float = 0.0  # relative to TARGET, not source member
    end_ratio: float = 1.0
    position: float = 0.5  # point load only, relative to TARGET


@dataclass(frozen=True, slots=True)
class LoadCompileWarning:
    code: str
    message: str
    source: LoadSource


class LoadCompileError(ValueError):
    def __init__(self, code: str, message: str, source: LoadSource | None = None):
        self.code = code
        self.source = source
        super().__init__(f"{code}: {message}" + (f" [{source}]" if source else ""))


@dataclass(frozen=True, slots=True)
class CompiledLoadPlan:
    """Contributions retain provenance; consumers sum ONLY within the same pattern/case.

    The compiler neither mutates the model nor allocates engine tags. A failed
    compilation raises LoadCompileError and never returns a partially valid plan.
    """

    nodal_loads: tuple[CompiledNodalLoad, ...] = ()
    element_loads: tuple[CompiledElementLoad, ...] = ()
    warnings: tuple[LoadCompileWarning, ...] = ()

    @property
    def required_subdivisions(self) -> tuple[tuple[int, int], ...]:
        """(source element tag, count) that BOTH builders must create before loads."""
        return tuple(
            sorted(
                {
                    (load.target.element_tag, load.target.segment_count)
                    for load in self.element_loads
                    if load.target.segment_index is not None
                }
            )
        )
