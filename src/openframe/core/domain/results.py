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
class BucklingMode:
    """One mode from an elastic global eigenvalue buckling analysis.

    Deliberately its own dataclass rather than a reuse of ``ModeShape`` - a
    buckling factor is not a natural frequency, and this analysis never forms a
    mass matrix, so period/frequency_hz/mass_participation_ratio would all be
    meaningless here (and are simply absent, not zeroed out, so nothing can
    mistake this for a modal result - see AnalysisResult.buckling_modes).
    """

    mode_number: int
    #: The factor this mode's reference load state must be scaled by to reach
    #: this buckling mode - Critical Load = buckling_load_factor * reference load.
    #: Identical to raw_eigenvalue for every mode actually reported here (both
    #: kept, per spec, as separate named facts rather than one value doing
    #: double duty).
    buckling_load_factor: float
    #: The solved generalized eigenvalue (K_material . phi = lambda . K_geometric
    #: . phi), already filtered to finite/effectively-real/positive - never a
    #: raw, unfiltered scipy.linalg.eig output.
    raw_eigenvalue: float
    #: Raw eigenvector mapped to nodes/DOFs, arbitrary scale/sign (whatever
    #: scipy.linalg.eig returned) - kept alongside the normalized version below
    #: so nothing about the original solution is lost to the display normalization.
    node_results: dict[int, NodeResult] = field(default_factory=dict)
    #: Same shape as node_results, scaled so the largest-magnitude translational
    #: component is 1.0 (or, if every translational component is ~0, the
    #: largest-magnitude component of any kind) - for rendering the buckled
    #: shape at a consistent, legible amplitude. The eigenvector's sign is
    #: arbitrary either way; this does not attempt to fix a "positive" direction.
    normalized_node_results: dict[int, NodeResult] = field(default_factory=dict)
    #: Human-readable identity of the load pattern(s) this mode's factor scales -
    #: e.g. "Pattern 2" or "All Patterns" (see buckling_solver.py's pattern
    #: selection) - not a tag alone, since more than one pattern can be combined.
    reference_load_case: str = ""
    reference_load_scale: float = 1.0


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
    #: The dt actually used for this step - equal to the user's configured
    #: Analysis Time Step unless Adaptive Recovery reduced it to converge.
    actual_dt: float = 0.0
    #: The algorithm that actually converged this step - the configured
    #: Algorithm unless one or more fallback algorithms were needed, in which
    #: case every fallback algorithm that succeeded, comma-joined (mirrors
    #: LoadDisplacementPoint.algorithm_used).
    algorithm_used: str = ""
    #: Whether this step needed any recovery at all (algorithm fallback or a
    #: dt reduction) to converge.
    recovered: bool = False
    #: Extra ``ops.analyze(1, dt)`` attempts beyond the first this step
    #: needed (mirrors LoadDisplacementPoint.retry_count).
    retry_count: int = 0
    #: How many times Adaptive Recovery halved the step dt (via
    #: reduction_factor) before this step converged - 0 if it converged at
    #: the caller's current working dt on the first try.
    dt_reduction_count: int = 0


@dataclass(frozen=True, slots=True)
class TimeHistoryDirectionSummary:
    """One active ground-motion direction, as actually applied to the run -
    what SETUP's direction table configured, echoed back as a result fact
    rather than re-derived from options the UI may have since changed."""

    dof: int
    record_name: str
    effective_scale: float


@dataclass(frozen=True, slots=True)
class TimeHistorySettings:
    """Whole-run configuration summary for a transient analysis - one entry
    per active ground-motion direction plus the integrator/damping/time-step
    settings that applied to every step, so a saved/exported result can be
    read back without re-opening SETUP. ``rayleigh_*`` are the coefficients
    actually passed to ``ops.rayleigh(...)`` (all zero for damping_mode
    "none"), not merely the Modal Targets inputs that produced them.
    """

    directions: tuple[TimeHistoryDirectionSummary, ...] = ()
    integrator_type: str = ""
    #: e.g. (("gamma", 0.5), ("beta", 0.25)) or (("alpha", 0.9), ("gamma", 0.6), ("beta", 0.3025)).
    integrator_params: tuple[tuple[str, float], ...] = ()
    damping_mode: str = ""
    rayleigh_alpha_m: float = 0.0
    rayleigh_beta_k: float = 0.0
    rayleigh_beta_k_init: float = 0.0
    rayleigh_beta_k_comm: float = 0.0
    initial_dt: float = 0.0
    minimum_dt: float = 0.0
    maximum_dt: float = 0.0
    end_time: float = 0.0
    status: str = "completed"


@dataclass(frozen=True, slots=True)
class ResponseSpectrumSettings:
    """Whole-run configuration summary for a response spectrum analysis -
    echoed back as a result fact (mirrors ``TimeHistorySettings``) so
    Result Tables can show what produced ``node_results``/``element_results``
    without re-opening SETUP. Every value in those two dicts is an SRSS
    combination across modes and directions and therefore has no sign - see
    this dataclass's own presence (not ``None``) as the signal Result Tables
    uses to show its own-sign-lost disclaimer, the same way a populated
    ``buckling_modes`` tuple signals the buckling-specific caveat."""

    num_modes: int = 0
    directions: tuple[str, ...] = ()
    combination_method: str = "SRSS"
    periods: tuple[float, ...] = ()
    spectral_accelerations: tuple[float, ...] = ()
    acceleration_unit: str = "g"


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
    #: Empty except for elastic eigenvalue buckling analysis, one entry per
    #: computed buckling mode - never populated alongside mode_shapes for the
    #: same result (see AnalysisKind.BUCKLING vs AnalysisKind.MODAL).
    buckling_modes: tuple[BucklingMode, ...] = ()
    #: None except for time-history analysis - the whole-run ground-motion/
    #: integrator/damping/time-step configuration that produced ``time_history``.
    time_history_settings: TimeHistorySettings | None = None
    #: None except for response spectrum analysis - see ResponseSpectrumSettings.
    #: node_results/element_results carry the SRSS-combined values themselves,
    #: same shape as a plain static result.
    response_spectrum_settings: ResponseSpectrumSettings | None = None
