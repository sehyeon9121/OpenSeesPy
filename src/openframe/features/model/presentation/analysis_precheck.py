"""One common Validator for every Analysis Case - Error/Warning/Info issues,
never a per-field ad hoc check scattered across a Quick Settings widget.

This first pass only implements the two rules that don't depend on any
method-specific settings (which don't exist as UI yet - see
``analysis_case.py``'s own docstring): a model needs geometry, and a static
analysis needs a load to be meaningful. Every other rule from the full spec
(Displacement Control needs a control node, dt>0, an active Time History
direction needs its ground motion, ...) slots into ``run_precheck``'s
per-kind dispatch once its own settings field exists - the dispatch shape
here is already built for that, not a placeholder to be rewritten later.

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

    return PrecheckReport(tuple(issues))
