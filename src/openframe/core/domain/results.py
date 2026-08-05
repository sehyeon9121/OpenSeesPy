"""Analysis results shared by solvers, result features and presentation."""

from dataclasses import dataclass, field
from enum import StrEnum


class AnalysisStatus(StrEnum):
    NOT_RUN = "not_run"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NodeResult:
    node_tag: int
    displacement: tuple[float, ...] = ()
    reaction: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class LoadDisplacementPoint:
    """One converged step of an incremental nonlinear analysis, for plotting a
    load-displacement (pushover) curve."""

    step: int
    control_displacement: float
    base_shear: float


@dataclass(frozen=True, slots=True)
class ElementResult:
    element_tag: int
    local_forces: tuple[float, ...] = ()
    #: Member length, needed to evaluate internal forces between the two ends.
    length: float = 0.0
    #: Distributed load (wx, wy) along the member's own axes, zero when none applies.
    uniform_load: tuple[float, float] = (0.0, 0.0)
    #: Bending stiffness EI, needed to rebuild the sag between the two ends. Zero when
    #: the element's section properties could not be read.
    flexural_rigidity: float = 0.0


@dataclass(slots=True)
class AnalysisResult:
    status: AnalysisStatus = AnalysisStatus.NOT_RUN
    node_results: dict[int, NodeResult] = field(default_factory=dict)
    element_results: dict[int, ElementResult] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    time_points: list[float] = field(default_factory=list)
    #: Empty for analyses that are not incremental (linear static, ...). Populated by
    #: nonlinear static analysis, one point per converged load step.
    load_displacement_curve: tuple[LoadDisplacementPoint, ...] = ()

