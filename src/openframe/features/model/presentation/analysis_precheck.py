"""One common Validator for every Analysis Case - Error/Warning/Info issues,
never a per-field ad hoc check scattered across a Quick Settings widget.

Two rules apply regardless of method-specific settings: a model needs
geometry, and a static analysis needs a load to be meaningful. Time History
now has its own settings-dependent rules (§_precheck_time_history) since its
Quick Settings page exists; the remaining per-kind rules from the full spec
(Displacement Control needs a control node, Rayleigh damping needs two
reference modes, ...) slot into this same dispatch once each kind's own
settings fields exist - the dispatch shape is already built for that, not a
placeholder to be rewritten later.

Deliberately does not consult ``core.domain.analysis_capabilities``'s
``ANALYSIS_CAPABILITIES`` registry - that describes the *other* pipeline's
solver capabilities (``infrastructure/opensees/*_solver.py``), not what
``MaterialFreeStaticsSolver`` actually implements for this canvas (e.g. it
only ever runs Nonlinear Static with ``integrator_type="LoadControl"``).
Trusting that registry here would report a feature as available when this
canvas's own solver does not support it.
"""

from dataclasses import dataclass
from enum import StrEnum

from openframe.core.domain import AnalysisKind, StructuralModel
from openframe.features.model.application.structural_precheck import (
    StructuralPrecheckIssue,
    run_structural_precheck,
)
from openframe.features.model.presentation.analysis_case import AnalysisCase


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class PrecheckIssue:
    severity: Severity
    code: str
    message: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.detail:
            object.__setattr__(self, "detail", self.message)


@dataclass(frozen=True, slots=True)
class PrecheckReport:
    issues: tuple[PrecheckIssue, ...] = ()

    @property
    def can_run(self) -> bool:
        return not any(issue.severity is Severity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity is Severity.WARNING for issue in self.issues)


_STATIC_KINDS = (AnalysisKind.LINEAR_STATIC, AnalysisKind.NONLINEAR_STATIC)

#: Kinds with zero execution wiring in this canvas today (see this module's
#: own docstring and the plan's §10) - PRE-CHECK says so as an INFO chip
#: rather than leaving Run just quietly disabled with no explanation.
_NOT_WIRED_KINDS = (AnalysisKind.MODAL, AnalysisKind.BUCKLING, AnalysisKind.TIME_HISTORY)

_DIRECTIONS = ("x", "y", "z")

#: Solver-policy notes from ``run_structural_precheck``. They are not modeling
#: errors. PRE-CHECK chips and ``AnalysisCaseStore.set_precheck`` treat *any*
#: issue as a case "경고", so putting these on the default screen would make a
#: valid mixed truss look broken. Keep them on the service for a later
#: diagnostic; do not map them into chips here.
_STRUCTURAL_POLICY_CODES = frozenset({"truss_rotational_dof"})


def run_precheck(case: AnalysisCase, model: StructuralModel) -> PrecheckReport:
    issues: list[PrecheckIssue] = []

    if not model.nodes or not model.elements:
        issues.append(
            PrecheckIssue(
                Severity.ERROR,
                "empty_model",
                "모델 없음",
                "절점과 부재를 먼저 작성하세요.",
            )
        )
        return PrecheckReport(tuple(issues))

    if case.kind in _STATIC_KINDS:
        has_loads = bool(model.nodal_loads or model.element_loads)
        if not has_loads:
            issues.append(
                PrecheckIssue(
                    Severity.ERROR,
                    "no_load",
                    "하중 없음",
                    "하중이 없는 정적해석은 실행할 수 없습니다 - 하중을 먼저 입력하세요.",
                )
            )

    if case.kind is AnalysisKind.TIME_HISTORY:
        issues.extend(_precheck_time_history(case.settings))

    if case.kind in _NOT_WIRED_KINDS:
        issues.append(
            PrecheckIssue(
                Severity.INFO,
                "not_wired",
                "실행 미지원",
                "이 해석 방법은 아직 이 캔버스에서 실행에 연결되지 않았습니다 - 설정은 저장되며, "
                "다음 단계에서 실행이 연결될 예정입니다.",
            )
        )

    # Topology findings from the domain model itself (isolated nodes, floating
    # components, zero-length members). Mapped onto this chip type so PRE-CHECK
    # can show them without the structural layer depending on Qt or AnalysisCase.
    issues.extend(
        _to_precheck_issue(issue)
        for issue in run_structural_precheck(model)
        if issue.code not in _STRUCTURAL_POLICY_CODES
    )

    return PrecheckReport(tuple(issues))


def _to_precheck_issue(issue: StructuralPrecheckIssue) -> PrecheckIssue:
    return PrecheckIssue(
        Severity(issue.severity),
        issue.code,
        issue.title,
        issue.message,
    )


def _precheck_time_history(settings: dict[str, object]) -> list[PrecheckIssue]:
    issues: list[PrecheckIssue] = []

    any_active = False
    for direction in _DIRECTIONS:
        if not settings.get(f"active_{direction}"):
            continue
        any_active = True
        if settings.get(f"ground_motion_{direction}") is None:
            issues.append(
                PrecheckIssue(
                    Severity.ERROR,
                    f"missing_ground_motion_{direction}",
                    f"{direction.upper()} 방향 지진파 없음",
                    f"{direction.upper()} 방향이 활성화되어 있지만 지진파가 선택되지 않았습니다.",
                )
            )
    if not any_active:
        issues.append(
            PrecheckIssue(
                Severity.ERROR,
                "no_active_direction",
                "방향 없음",
                "X/Y/Z 중 최소 한 방향은 활성화해야 합니다.",
            )
        )

    output_dt = settings.get("output_dt", 0.0)
    analysis_dt = settings.get("analysis_dt", 0.0)
    if not (isinstance(output_dt, (int, float)) and output_dt > 0.0):
        issues.append(
            PrecheckIssue(Severity.ERROR, "invalid_output_dt", "출력 dt 오류", "출력 간격 dt는 0보다 커야 합니다.")
        )
    if not (isinstance(analysis_dt, (int, float)) and analysis_dt > 0.0):
        issues.append(
            PrecheckIssue(Severity.ERROR, "invalid_analysis_dt", "해석 dt 오류", "해석 적분 간격 dt는 0보다 커야 합니다.")
        )

    start_time = settings.get("start_time", 0.0)
    end_time = settings.get("end_time", 0.0)
    if isinstance(start_time, (int, float)) and isinstance(end_time, (int, float)) and end_time <= start_time:
        issues.append(
            PrecheckIssue(
                Severity.ERROR,
                "invalid_time_window",
                "시간 범위 오류",
                "종료 시간은 시작 시간보다 커야 합니다.",
            )
        )

    return issues
