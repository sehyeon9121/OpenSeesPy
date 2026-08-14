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
    #: Populated only for time-history steps (empty for static/modal results,
    #: which have no time axis to differentiate against). Relative to the
    #: ground, not absolute/total - see time_history_solver.py.
    velocity: tuple[float, ...] = ()
    acceleration: tuple[float, ...] = ()


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
    #: Cumulative pseudo-time (``ops.getTime()``) at this step - equal to the
    #: applied load factor for every integrator (LoadControl, DisplacementControl,
    #: ArcLength) *only when* the active pattern's TimeSeries is Linear with
    #: factor 1.0. That is guaranteed for every pattern this solver replays
    #: itself (gravity-then-push), but not for an imported script's own pattern
    #: if that script deliberately used a different TimeSeries type - see
    #: ``_current_load_factor()`` in nonlinear_static_solver.py. For ArcLength
    #: this is still the only y-axis that keeps making sense past a limit point
    #: (base_shear is still real, but the factor is what can decrease there).
    load_factor: float = 0.0
    #: Arc-length radius (``s`` in ``ops.integrator("ArcLength", s, alpha)``)
    #: actually used to converge this step - None for LoadControl/
    #: DisplacementControl, where no such radius exists.
    arc_length_radius: float | None = None
    #: Algorithm that actually converged this step - the configured ALGORITHM
    #: unless one or more fallback algorithms were needed, in which case every
    #: fallback algorithm that succeeded at some point during the step, comma-
    #: joined.
    algorithm_used: str = ""
    #: Whether this step needed any recovery at all (fallback algorithm, step
    #: bisection, or - for ArcLength - a radius reduction) to converge.
    recovered: bool = False
    #: Extra ``ops.analyze(1)`` attempts beyond the first that this step needed
    #: (``attempts - 1``) - 0 when the first attempt converged outright.
    retry_count: int = 0


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
    #: Fraction (0..1) of the total mass in each DOF direction this mode accounts
    #: for - one entry per DOF (2D: Ux,Uy,Rz; 3D: Ux,Uy,Uz,Rx,Ry,Rz), computed from
    #: the model's own lumped mass rather than assumed from solver normalization.
    mass_participation_ratio: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class TimeHistoryStep:
    """One recorded time step of a transient (time-history) analysis.

    ``node_results`` reuses ``NodeResult`` the same way ``ModeShape`` does -
    ``displacement``/``velocity``/``acceleration`` are populated for every node
    (displacement needed for the deformed-shape animation), ``reaction`` only
    for restrained nodes (a free node's reaction is always zero and not worth
    carrying at every step).
    """

    time: float
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
    #: Empty except for time-history analysis, one entry per recorded time step.
    time_history: tuple[TimeHistoryStep, ...] = ()
