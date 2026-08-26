"""Metadata contract describing which OpenSees analysis components each
``AnalysisKind`` actually lets the user configure, versus which ones the
engine already decides on its own.

This module is a *description* of the existing solver code
(``infrastructure/opensees/*_solver.py``), not a new execution path. Nothing
here is read by ``AnalysisConfigStore``, ``AnalysisRequest``, the
``AnalysisModule``/``AnalysisRunner`` chain, or any solver function - those
keep running exactly as before, driven by their own hardcoded calls and
``options`` dict handling. ``ANALYSIS_CAPABILITIES`` exists so a future UI
layer (not this module) can ask "is this field something the user can
actually change for this analysis kind?" instead of guessing, and so a test
can catch that metadata drifting away from what the solver functions really
do (see ``tests/unit/test_analysis_capabilities.py``).

If a future change alters what a solver function actually calls (e.g.
Linear Static's equation solver stops being hardcoded to ``"BandGeneral"``),
this registry must be updated to match - it does not do that automatically.
"""

from dataclasses import dataclass
from enum import StrEnum

from openframe.core.domain.analysis import AnalysisKind


class FieldState(StrEnum):
    """How a single analysis component behaves for one ``AnalysisKind``."""

    #: The user can change this, and the value they pick is actually sent to
    #: and used by the solver (e.g. Nonlinear Static's Algorithm).
    EDITABLE = "editable"
    #: The engine always uses one specific value; there is no user control
    #: for it, even though SETUP may currently *display* a field for it
    #: (e.g. Linear Static's equation solver is always "BandGeneral").
    ENGINE_FIXED = "engine_fixed"
    #: The engine decides at run time via its own internal logic rather than
    #: a single fixed value or a user choice (e.g. Modal's eigen solver
    #: tries ARPACK first and falls back to FullGenLapack on failure).
    AUTOMATIC = "automatic"
    #: This component has no meaning for this analysis kind at all (e.g.
    #: Linear Static has no convergence test - it never iterates).
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class ComponentField:
    """One component's state, plus whatever extra facts are worth keeping
    next to it. ``value`` is the single headline fact (a fixed value for
    ENGINE_FIXED, usually ``None`` for EDITABLE since there is no one fixed
    answer). ``details`` holds any further named facts a component needs -
    Newmark's gamma/beta, a fallback solver's name, and so on - without
    forcing every component into the same shape."""

    state: FieldState
    value: str | None = None
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisCapabilities:
    """Which of the nine analysis components apply to one ``AnalysisKind``,
    and in what state. Static Integrator and Dynamic Time Integrator are
    kept as separate fields on purpose - they are different OpenSees
    concepts (``ops.integrator("LoadControl", ...)`` vs
    ``ops.integrator("Newmark", ...)``) that happen to share one Python
    ``ops.integrator`` call, not one component."""

    equation_solver: ComponentField
    algorithm: ComponentField
    static_integrator: ComponentField
    dynamic_integrator: ComponentField
    convergence_test: ComponentField
    constraint_handler: ComponentField
    numberer: ComponentField
    eigen_solver: ComponentField
    #: Component-level state only. Time History's actual damping input is a
    #: mix: the damping ratio itself is a user-editable number, but the
    #: Rayleigh alpha_M/beta_K coefficients computed from it are entirely
    #: automatic - this one field cannot capture that split. A field-level
    #: capability system (e.g. "damping_ratio is EDITABLE, rayleigh
    #: coefficients are AUTOMATIC") is left for Phase 3, once SETUP actually
    #: renders per-field state instead of per-component state.
    damping: ComponentField


ANALYSIS_CAPABILITIES: dict[AnalysisKind, AnalysisCapabilities] = {
    AnalysisKind.LINEAR_STATIC: AnalysisCapabilities(
        # infrastructure/opensees/linear_static_solver.py: run_linear_static_analysis
        # takes no solver-related parameters at all - every ops.* call below is a
        # bare literal in that function, not something request.options can reach.
        equation_solver=ComponentField(FieldState.ENGINE_FIXED, "BandGeneral"),
        algorithm=ComponentField(FieldState.ENGINE_FIXED, "Linear"),
        static_integrator=ComponentField(
            FieldState.ENGINE_FIXED, "LoadControl", (("increment", "1.0"),)
        ),
        dynamic_integrator=ComponentField(FieldState.NOT_APPLICABLE),
        convergence_test=ComponentField(FieldState.NOT_APPLICABLE),
        constraint_handler=ComponentField(FieldState.ENGINE_FIXED, "Transformation"),
        numberer=ComponentField(FieldState.ENGINE_FIXED, "Plain"),
        eigen_solver=ComponentField(FieldState.NOT_APPLICABLE),
        damping=ComponentField(FieldState.NOT_APPLICABLE),
    ),
    AnalysisKind.NONLINEAR_STATIC: AnalysisCapabilities(
        # infrastructure/opensees/nonlinear_static_solver.py:
        # run_nonlinear_static_analysis(..., algorithm=..., test_type=..., system=...,
        # constraints_type=..., numberer=..., integrator_type=..., ...) - these six
        # keyword arguments are exactly what AnalysisSettingsPanel.build_options()
        # sends through AnalysisConfigStore.options, and validate() whitelists their
        # allowed values (see nonlinear_static/module.py). This is the only kind
        # where the SETUP fields are not decorative.
        equation_solver=ComponentField(FieldState.EDITABLE),
        algorithm=ComponentField(FieldState.EDITABLE),
        static_integrator=ComponentField(FieldState.EDITABLE),
        dynamic_integrator=ComponentField(FieldState.NOT_APPLICABLE),
        convergence_test=ComponentField(FieldState.EDITABLE),
        constraint_handler=ComponentField(FieldState.EDITABLE),
        numberer=ComponentField(FieldState.EDITABLE),
        eigen_solver=ComponentField(FieldState.NOT_APPLICABLE),
        damping=ComponentField(FieldState.NOT_APPLICABLE),
    ),
    AnalysisKind.MODAL: AnalysisCapabilities(
        # infrastructure/opensees/modal_solver.py: run_modal_analysis(source, *,
        # num_modes=3) - only num_modes is a real parameter. Every ops.* call other
        # than ops.eigen(...) is a bare literal, issued only to put the model in a
        # valid state before the eigenproblem is solved.
        equation_solver=ComponentField(FieldState.ENGINE_FIXED, "BandGeneral"),
        algorithm=ComponentField(
            FieldState.ENGINE_FIXED,
            "Linear",
            (("purpose", "고유치 계산 전 모델을 준비하는 내부 구성, 결과에 영향 없음"),),
        ),
        static_integrator=ComponentField(
            FieldState.ENGINE_FIXED,
            "LoadControl",
            (
                ("increment", "0.0"),
                ("purpose", "고유치 계산 전 모델을 준비하는 내부 구성, 결과에 영향 없음"),
            ),
        ),
        dynamic_integrator=ComponentField(FieldState.NOT_APPLICABLE),
        convergence_test=ComponentField(FieldState.NOT_APPLICABLE),
        constraint_handler=ComponentField(FieldState.ENGINE_FIXED, "Transformation"),
        numberer=ComponentField(FieldState.ENGINE_FIXED, "RCM"),
        eigen_solver=ComponentField(
            FieldState.AUTOMATIC,
            details=(("primary", "ARPACK"), ("fallback", "FullGenLapack")),
        ),
        damping=ComponentField(FieldState.NOT_APPLICABLE),
    ),
    AnalysisKind.TIME_HISTORY: AnalysisCapabilities(
        # infrastructure/opensees/time_history_solver.py: run_time_history_analysis(...,
        # solution=..., integrator=..., damping=..., recovery=...) - Solution Strategy,
        # Time Integration (Newmark/HHT) and Damping (None/Modal Targets/Direct
        # Coefficients) are all real, solver-consumed keyword arguments now (see
        # AnalysisSettingsPanel.build_options()'s TIME_HISTORY branch), the same way
        # Nonlinear Static's six EDITABLE fields already are.
        equation_solver=ComponentField(FieldState.EDITABLE),
        algorithm=ComponentField(FieldState.EDITABLE),
        static_integrator=ComponentField(FieldState.NOT_APPLICABLE),
        dynamic_integrator=ComponentField(
            FieldState.EDITABLE,
            details=(("choices", "Newmark, HHT"),),
        ),
        convergence_test=ComponentField(FieldState.EDITABLE),
        constraint_handler=ComponentField(FieldState.EDITABLE),
        numberer=ComponentField(FieldState.EDITABLE),
        eigen_solver=ComponentField(
            FieldState.AUTOMATIC,
            details=(
                ("primary", "ARPACK (ops.eigen)"),
                ("fallback", "FullGenLapack"),
                ("purpose", "Damping의 Modal Targets 모드에서만 내부적으로 사용, 결과에 노출되지 않음"),
            ),
        ),
        # The damping *mode* (None/Modal Targets/Direct Coefficients) and, for
        # Direct Coefficients, the four Rayleigh coefficients themselves are
        # user-editable - but Modal Targets' alpha_M/beta_K are computed from
        # the chosen modes' eigenfrequencies, not typed directly. EDITABLE
        # here describes "the user controls this component", same as
        # Nonlinear Static's own EDITABLE fields; the AUTOMATIC half of Modal
        # Targets is called out in details rather than needing a second
        # FieldState this dataclass has no room for (see its own docstring).
        damping=ComponentField(
            FieldState.EDITABLE,
            details=(
                ("choices", "None, Rayleigh - Modal Targets, Rayleigh - Direct Coefficients"),
                ("modal_targets_computed", "alpha_M, beta_K (or betaKInit/betaKComm) from mode i/j"),
            ),
        ),
    ),
    AnalysisKind.BUCKLING: AnalysisCapabilities(
        # infrastructure/opensees/buckling_solver.py: run_buckling_analysis(source, *,
        # reference_load_pattern=, reference_load_scale=, num_modes=, geometric_transform_type=,
        # eigenvalue_tolerance=) - a linearized elastic eigenvalue buckling solve, not a
        # modal (mass-matrix) eigenproblem. Two single-step linear static solves
        # (unloaded, then at the reference load) extract K_material/K_loaded via
        # ops.printA("-ret"); K_geometric = K_material - K_loaded feeds
        # scipy.linalg.eig(K_material, K_geometric) directly (never an explicit
        # inverse). GEOMETRIC TRANSFORMATION is the one real user choice, reusing
        # ModelCommandCollector's existing geom_transf_override mechanism.
        equation_solver=ComponentField(
            FieldState.ENGINE_FIXED,
            "FullGeneral",
            (("purpose", "printA(\"-ret\")로 전체 조밀 강성행렬을 뽑아내려면 필요"),),
        ),
        algorithm=ComponentField(FieldState.ENGINE_FIXED, "Linear"),
        static_integrator=ComponentField(
            FieldState.ENGINE_FIXED,
            "LoadControl",
            (
                ("unloaded_step", "0.0 (K_material)"),
                ("reference_load_step", "1.0 (K_loaded)"),
            ),
        ),
        dynamic_integrator=ComponentField(FieldState.NOT_APPLICABLE),
        convergence_test=ComponentField(FieldState.NOT_APPLICABLE),
        constraint_handler=ComponentField(FieldState.ENGINE_FIXED, "Transformation"),
        numberer=ComponentField(FieldState.ENGINE_FIXED, "RCM"),
        eigen_solver=ComponentField(
            FieldState.ENGINE_FIXED,
            "scipy.linalg.eig",
            (
                ("problem", "K_material . phi = lambda . K_geometric . phi"),
                ("purpose", "ops.eigen()의 질량행렬 기반 고유치와는 다른 문제 - 사용하지 않음"),
            ),
        ),
        damping=ComponentField(FieldState.NOT_APPLICABLE),
    ),
    AnalysisKind.RESPONSE_SPECTRUM: AnalysisCapabilities(
        # infrastructure/opensees/response_spectrum_solver.py:
        # run_response_spectrum_analysis(source, *, periods=, spectral_accelerations=,
        # acceleration_unit=, num_modes=, directions=, model_length_unit=) - like Modal,
        # only num_modes/directions are real user-facing knobs; every ops.* call other
        # than ops.eigen(...) and the per-mode equivalent-static ops.analyze(1) is a
        # bare literal issued to put the model in a valid state.
        equation_solver=ComponentField(FieldState.ENGINE_FIXED, "BandGeneral"),
        algorithm=ComponentField(FieldState.ENGINE_FIXED, "Linear"),
        static_integrator=ComponentField(
            FieldState.ENGINE_FIXED,
            "LoadControl",
            (("purpose", "모드별 등가정적하중을 1회 해석씩 적용, 매 해석 전 pseudo-time 초기화"),),
        ),
        dynamic_integrator=ComponentField(FieldState.NOT_APPLICABLE),
        convergence_test=ComponentField(FieldState.NOT_APPLICABLE),
        constraint_handler=ComponentField(FieldState.ENGINE_FIXED, "Transformation"),
        numberer=ComponentField(FieldState.ENGINE_FIXED, "RCM"),
        eigen_solver=ComponentField(
            FieldState.AUTOMATIC,
            details=(("primary", "ARPACK"), ("fallback", "FullGenLapack")),
        ),
        damping=ComponentField(
            FieldState.NOT_APPLICABLE,
            details=(
                (
                    "purpose",
                    "스펙트럼 곡선 자체에 이미 반영된 감쇠비를 그대로 사용 - 별도 감쇠 입력 없음",
                ),
            ),
        ),
    ),
}
