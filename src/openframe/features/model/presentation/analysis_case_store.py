"""``AnalysisCaseStore`` - CRUD + active-case tracking for a 3D canvas
page's ``AnalysisCase`` collection.

Every mutating method takes an explicit ``case_id`` and only ever touches
that one case's own ``AnalysisCase`` instance - this is what actually
guarantees "switching methods/editing one case never overwrites another,"
not any discipline enforced by callers. There is always at least one case
(``delete_case`` refuses to remove the last one) so a freshly-opened 3D page
never has to special-case "no case selected" anywhere in the sidebar.
"""

from PySide6.QtCore import QObject, Signal

from openframe.core.domain import AnalysisKind
from openframe.features.model.presentation.analysis_case import AnalysisCase, CaseStatus

#: Korean label seed for a freshly-created case, before the user renames it -
#: mirrors the old ``_ANALYSIS_METHOD_OPTIONS`` labels closely enough to feel
#: familiar, without trying to be a unique name (uniqueness is not enforced;
#: this is a display convenience, not an identity).
_DEFAULT_NAME_PREFIX: dict[AnalysisKind, str] = {
    AnalysisKind.LINEAR_STATIC: "LinearStatic",
    AnalysisKind.NONLINEAR_STATIC: "Pushover",
    AnalysisKind.MODAL: "Modal",
    AnalysisKind.BUCKLING: "Buckling",
    AnalysisKind.TIME_HISTORY: "TH",
    AnalysisKind.RESPONSE_SPECTRUM: "RSA",
}


class AnalysisCaseStore(QObject):
    case_added = Signal(str)
    case_removed = Signal(str)
    case_renamed = Signal(str)
    active_case_changed = Signal(str)
    precheck_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cases: dict[str, AnalysisCase] = {}
        self._order: list[str] = []
        self._active_id: str | None = None

    # -- creation / removal -------------------------------------------------
    def add_case(self, kind: AnalysisKind, name: str | None = None) -> str:
        resolved_name = name or self._next_default_name(kind)
        case = AnalysisCase.new(kind, resolved_name)
        self._cases[case.case_id] = case
        self._order.append(case.case_id)
        if self._active_id is None:
            self._active_id = case.case_id
        self.case_added.emit(case.case_id)
        if self._active_id == case.case_id:
            self.active_case_changed.emit(case.case_id)
        return case.case_id

    def duplicate_case(self, case_id: str, new_name: str | None = None) -> str | None:
        source = self._cases.get(case_id)
        if source is None:
            return None
        resolved_name = new_name or f"{source.name} copy"
        new_case = AnalysisCase.new(source.kind, resolved_name)
        new_case.settings = dict(source.settings)
        self._cases[new_case.case_id] = new_case
        self._order.append(new_case.case_id)
        self.case_added.emit(new_case.case_id)
        return new_case.case_id

    def rename_case(self, case_id: str, name: str) -> bool:
        case = self._cases.get(case_id)
        if case is None or not name:
            return False
        case.name = name
        self.case_renamed.emit(case_id)
        return True

    def delete_case(self, case_id: str) -> bool:
        """Refuses to delete the last remaining case - the sidebar always
        has something to show, so it never needs a "no case exists" empty
        state."""
        if case_id not in self._cases or len(self._cases) <= 1:
            return False
        del self._cases[case_id]
        self._order.remove(case_id)
        self.case_removed.emit(case_id)
        if self._active_id == case_id:
            self.set_active_case(self._order[0])
        return True

    # -- lookup ---------------------------------------------------------
    def list_cases(self) -> tuple[AnalysisCase, ...]:
        return tuple(self._cases[case_id] for case_id in self._order)

    def case(self, case_id: str) -> AnalysisCase:
        return self._cases[case_id]

    def has_case(self, case_id: str) -> bool:
        return case_id in self._cases

    def active_case_id(self) -> str | None:
        return self._active_id

    def set_active_case(self, case_id: str) -> None:
        if case_id not in self._cases or case_id == self._active_id:
            return
        self._active_id = case_id
        self.active_case_changed.emit(case_id)

    # -- per-case state ---------------------------------------------------
    def set_precheck(self, case_id: str, report: object) -> None:
        case = self._cases.get(case_id)
        if case is None:
            return
        case.last_precheck = report
        can_run = getattr(report, "can_run", True)
        has_issues = bool(getattr(report, "issues", ()))
        if not can_run:
            case.status = CaseStatus.WARNING
        elif has_issues:
            case.status = CaseStatus.WARNING
        elif case.status in (CaseStatus.UNSET, CaseStatus.WARNING):
            case.status = CaseStatus.RUNNABLE
        self.precheck_changed.emit(case_id)

    def set_status(self, case_id: str, status: CaseStatus) -> None:
        case = self._cases.get(case_id)
        if case is None:
            return
        case.status = status
        self.precheck_changed.emit(case_id)

    # -- serialization ----------------------------------------------------
    def to_dict(self) -> dict[str, object]:
        return {
            "cases": [self._cases[case_id].to_dict() for case_id in self._order],
            "active_case_id": self._active_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnalysisCaseStore":
        store = cls()
        raw_cases = data.get("cases")
        if isinstance(raw_cases, list):
            for raw_case in raw_cases:
                if not isinstance(raw_case, dict):
                    continue
                case = AnalysisCase.from_dict(raw_case)
                store._cases[case.case_id] = case
                store._order.append(case.case_id)
        active_id = data.get("active_case_id")
        if isinstance(active_id, str) and active_id in store._cases:
            store._active_id = active_id
        elif store._order:
            store._active_id = store._order[0]
        return store

    # -- helpers ------------------------------------------------------------
    def _next_default_name(self, kind: AnalysisKind) -> str:
        prefix = _DEFAULT_NAME_PREFIX.get(kind, kind.value)
        existing = {case.name for case in self._cases.values()}
        index = 1
        while f"{prefix}-{index}" in existing:
            index += 1
        return f"{prefix}-{index}"
