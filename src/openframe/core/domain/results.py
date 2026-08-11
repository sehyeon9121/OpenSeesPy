"""Analysis results shared by solvers, result features and presentation."""

from dataclasses import dataclass, field
from enum import StrEnum


class AnalysisStatus(StrEnum):
    NOT_RUN = "not_run"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
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
    attempts: int = 1
    substeps: int = 1
    iterations: int = 0
    recovered_with: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NonlinearConvergence:
    """Execution summary for an incremental nonlinear-static solve.

    A run may have useful committed results without reaching every requested
    increment.  Keeping that state separate from a plain success/failure flag lets
    the UI show the converged branch without calling a truncated curve complete.
    """

    requested_steps: int
    completed_steps: int
    failed_step: int | None = None
    total_attempts: int = 0
    total_substeps: int = 0
    recovered_steps: tuple[int, ...] = ()

    @property
    def converged(self) -> bool:
        return self.failed_step is None and self.completed_steps == self.requested_steps


@dataclass(frozen=True, slots=True)
class ElementResult:
    element_tag: int
    local_forces: tuple[float, ...] = ()
    #: Member length, needed to evaluate internal forces between the two ends.
    length: float = 0.0
    #: Distributed load (wx_i, wy_i, wx_j, wy_j) along the member's own axes -
    #: linearly varying from end i to end j, zero (all four) when none applies.
    #: A plain uniform load has wx_i==wx_j and wy_i==wy_j.
    uniform_load: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    #: Bending stiffness EI, needed to rebuild the sag between the two ends. Zero when
    #: the element's section properties could not be read.
    flexural_rigidity: float = 0.0


@dataclass(frozen=True, slots=True)
class ModeShape:
    """One natural mode from an eigenvalue (modal) analysis.

    ``node_results`` reuses ``NodeResult`` for its displacement field so the mode
    shape can be rendered by the same deflected-shape viewer a static result
    uses - a mode shape carries no reactions or forces, so ``reaction`` stays empty
    on every entry.
    """

    mode_number: int
    #: Raw eigenvalue from ``ops.eigen`` (rad/s)^2 - kept for reference/debugging.
    eigenvalue: float
    angular_frequency: float
    frequency_hz: float
    period: float
    node_results: dict[int, NodeResult] = field(default_factory=dict)


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
    convergence: NonlinearConvergence | None = None
    #: Empty except for modal analysis, one entry per computed natural mode.
    mode_shapes: tuple[ModeShape, ...] = ()
