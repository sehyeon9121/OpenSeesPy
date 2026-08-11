"""Single shared source of truth for the analysis kind and its options.

MODEL's analysis-type selector, SETUP's settings panel and the Nonlinear
Settings dialog all read and write through one ``AnalysisConfigStore``
instance instead of each keeping their own copy - that is what keeps the
three views from ever disagreeing about what is actually configured.
"""

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from openframe.core.domain import AnalysisKind, AnalysisRequest


class AnalysisConfigStore(QObject):
    kind_changed = Signal(object)
    options_changed = Signal()

    def __init__(
        self,
        kind: AnalysisKind = AnalysisKind.LINEAR_STATIC,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = AnalysisKind(kind)
        self._options: dict[str, float | int | str | bool] = {}

    @property
    def kind(self) -> AnalysisKind:
        return self._kind

    def set_kind(self, kind: AnalysisKind) -> None:
        # Re-wrapped defensively: Qt's QComboBox stores userData through QVariant,
        # which can hand a StrEnum member back as a plain str on read - AnalysisKind(...)
        # is a no-op for an already-valid member, so this is free insurance against
        # a caller passing on a QVariant-degraded value (e.g. ``combo.currentData()``).
        kind = AnalysisKind(kind)
        if kind == self._kind:
            return
        self._kind = kind
        self.kind_changed.emit(kind)

    @property
    def options(self) -> dict[str, float | int | str | bool]:
        """A copy - callers must go through :meth:`set_options` to change it,
        so every change is observable through ``options_changed``."""
        return dict(self._options)

    def set_options(self, options: dict[str, float | int | str | bool]) -> None:
        if options == self._options:
            return
        self._options = dict(options)
        self.options_changed.emit()

    def to_request(self, source_path: Path) -> AnalysisRequest:
        return AnalysisRequest(source_path=source_path, kind=self._kind, options=self.options)
