"""Analysis Case - a named, independently-savable analysis configuration for
the 3D free-form canvas (e.g. "LS-Dead+Live", "Pushover-X", "TH-Kobe-X").

Deliberately its own type, not a reuse of ``core.domain.analysis.AnalysisRequest``
- that dataclass is ``source_path``-shaped for the separate script-import
pipeline (``SetupWorkspace``/``AnalysisConfigStore``) and has no meaning for
this canvas's in-memory model. A model can hold many Cases of the same
``kind`` at once (two independent Pushover runs, for instance) - something
neither this canvas's old ``self._analysis_settings`` dict (one entry per
*kind*, not per case) nor the other pipeline's ``AnalysisConfigStore`` (one
kind+options total) could ever represent.

``settings`` stays a plain dict in this first pass - the per-method Quick
Settings fields it will eventually hold (control node, ground motion
selection, etc.) don't exist as UI yet, so a fully-typed per-kind dataclass
here would just be unused shape with nothing to validate against. It becomes
a real per-kind dataclass once each method's Quick Settings panel is built.
"""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from openframe.core.domain import AnalysisKind

#: Shared Korean label per method - used by both the case-creation menu and
#: the sidebar's read-only method echo, so the two can never drift apart.
#: ``RESPONSE_SPECTRUM`` has no Quick Settings page yet (this canvas's
#: analysis picker never exposed it before this refactor either) and is
#: deliberately left out of any case-creation menu built from this dict.
ANALYSIS_KIND_LABELS: dict[AnalysisKind, str] = {
    AnalysisKind.LINEAR_STATIC: "선형탄성 (Linear Elastic)",
    AnalysisKind.NONLINEAR_STATIC: "비선형 정적 (Pushover)",
    AnalysisKind.MODAL: "모드/고유치 (Modal)",
    AnalysisKind.BUCKLING: "좌굴 (Buckling)",
    AnalysisKind.TIME_HISTORY: "시간이력 (Time History)",
}


class CaseStatus(StrEnum):
    """Mirrors the Analysis Case section's own status chip text (미설정/
    경고/실행가능/완료/실패) - ``RUNNABLE``/``WARNING`` are set by
    ``analysis_precheck.run_precheck``'s result, ``COMPLETE``/``FAILED`` by
    the solve completion handler, never by the user directly."""

    UNSET = "unset"
    WARNING = "warning"
    RUNNABLE = "runnable"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(slots=True)
class AnalysisCase:
    """``kind`` is fixed at creation and never reassigned - switching
    analysis method means creating (or duplicating) a case, not mutating an
    existing one in place, so a case's own identity always matches exactly
    one method's worth of settings. ``last_precheck`` is intentionally
    excluded from ``to_dict()``/``from_dict()`` - it is a derived, transient
    view of ``settings`` plus the current model, always recomputed on load
    rather than trusted from a stale save.
    """

    case_id: str
    name: str
    kind: AnalysisKind
    status: CaseStatus = CaseStatus.UNSET
    settings: dict[str, object] = field(default_factory=dict)
    last_precheck: object | None = field(default=None, compare=False)

    @staticmethod
    def new(kind: AnalysisKind, name: str) -> "AnalysisCase":
        return AnalysisCase(case_id=uuid.uuid4().hex, name=name, kind=kind)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "kind": self.kind.value,
            "status": self.status.value,
            "settings": dict(self.settings),
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> "AnalysisCase":
        return AnalysisCase(
            case_id=str(data["case_id"]),
            name=str(data["name"]),
            kind=AnalysisKind(str(data["kind"])),
            status=CaseStatus(str(data.get("status", CaseStatus.UNSET.value))),
            settings=dict(data.get("settings") or {}),
        )
