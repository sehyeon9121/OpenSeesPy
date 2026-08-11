"""SETUP page: review and configure how the selected analysis will run.

A page header (title/back-link/status) above three columns, all driven by the
one ``AnalysisConfigStore`` shared with MODEL's ``AnalysisTypeSelector``:

- LEFT: a static, non-interactive readout of the steps this analysis kind
  involves (not a wizard yet - see the project plan for why).
- CENTER: the existing ``AnalysisSettingsPanel`` (solver + the Nonlinear
  Settings dialog, unchanged) plus a pre-check row.
- RIGHT: a short, fixed contextual guide for the selected analysis kind.

Pre-check errors are exactly ``RunAnalysisService.validate()`` - the same
check that already blocks ``RunAnalysisService.execute()`` - shown here
instead of duplicated. Warnings are additional, non-blocking advice.
"""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from openframe.app.shell.page_header import PageHeader
from openframe.core.domain import AnalysisKind, AnalysisRequest, StructuralModel
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)
from openframe.features.analysis.presentation.analysis_settings_panel import (
    AnalysisSettingsPanel,
)

_KIND_LABELS: dict[AnalysisKind, str] = {
    AnalysisKind.LINEAR_STATIC: "Linear Static",
    AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
    AnalysisKind.TIME_HISTORY: "Time History",
}

_FLOW_STEPS: dict[AnalysisKind, tuple[str, ...]] = {
    AnalysisKind.LINEAR_STATIC: ("Model", "Loading", "Solver", "Pre-check", "Run"),
    AnalysisKind.NONLINEAR_STATIC: (
        "Model",
        "Loading",
        "Nonlinearity",
        "Solution Method",
        "Convergence",
        "Pre-check",
        "Run",
    ),
    AnalysisKind.TIME_HISTORY: (
        "Model",
        "Ground Motion",
        "Direction & Scale",
        "Time Step",
        "Damping",
        "Integration",
        "Pre-check",
        "Run",
    ),
}

_GUIDE_TEXT: dict[AnalysisKind, str] = {
    AnalysisKind.LINEAR_STATIC: (
        "Linear static analysis assumes forces and displacements stay proportional - "
        "no yielding, no large displacements. Fast and predictable, but it cannot trace "
        "post-yield or post-buckling behavior. Use it to check a first-pass design."
    ),
    AnalysisKind.NONLINEAR_STATIC: (
        "Nonlinear static (pushover) analysis pushes the structure incrementally and "
        "solves for equilibrium at every step, so it can capture yielding and "
        "softening a linear analysis would miss. It needs a CONTROL NODE/DOF to push "
        "and a converging solution algorithm - see NONLINEAR SETTINGS below."
    ),
    AnalysisKind.TIME_HISTORY: (
        "Time history analysis applies a real or synthetic ground-motion record over "
        "time and integrates the equation of motion step by step. It is the most "
        "realistic seismic check available here, and the most demanding to set up - "
        "this analysis type is not implemented yet."
    ),
}


class SetupWorkspace(QFrame):
    run_requested = Signal()
    back_to_model_requested = Signal()

    def __init__(
        self,
        config_store: AnalysisConfigStore,
        run_analysis_service: RunAnalysisService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("setupWorkspace")
        self.config_store = config_store
        self._run_analysis_service = run_analysis_service
        self._model: StructuralModel | None = None
        self._source_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.page_header = PageHeader(
            title="SETUP",
            subtitle="Configure and review how the structural model will be analyzed.",
            action_text="←  Back to Model",
        )
        self.page_header.action_requested.connect(self.back_to_model_requested)
        self.page_header.set_status("READY", "ready")
        layout.addWidget(self.page_header)

        body = QSplitter(Qt.Orientation.Horizontal)
        body.setObjectName("setupWorkspaceSplitter")
        body.setChildrenCollapsible(False)

        self.flow_list = self._build_flow_list()
        body.addWidget(self.flow_list)

        center = QFrame()
        center.setObjectName("setupCenterColumn")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self.settings_panel = AnalysisSettingsPanel(store=config_store)
        center_layout.addWidget(self.settings_panel, 1)
        center_layout.addWidget(self._build_precheck_row())
        body.addWidget(center)

        self.guide_panel = self._build_guide_panel()
        body.addWidget(self.guide_panel)

        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        body.setSizes((220, 720, 300))
        layout.addWidget(body, 1)

        self.config_store.kind_changed.connect(self._refresh)
        self.config_store.options_changed.connect(self._refresh_precheck)
        self._refresh(self.config_store.kind)

    def _build_flow_list(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("setupFlowPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header("ANALYSIS FLOW"))
        self._flow_list_widget = QListWidget()
        self._flow_list_widget.setObjectName("setupFlowList")
        self._flow_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._flow_list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._flow_list_widget, 1)
        return frame

    def _build_precheck_row(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("precheckRow")
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(10)

        self.precheck_chip_row = QHBoxLayout()
        self.precheck_chip_row.setSpacing(6)
        self.precheck_chip_row.addStretch(1)
        outer.addLayout(self.precheck_chip_row)
        self.precheck_summary = QLabel("Ready to run")
        self.precheck_summary.setObjectName("precheckSummary")
        self.precheck_summary.setWordWrap(True)
        outer.addWidget(self.precheck_summary)
        self.run_button = QPushButton("▶  RUN ANALYSIS")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run_requested)
        outer.addWidget(self.run_button)
        return frame

    def _build_guide_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("setupGuidePanel")
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(320)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header("ANALYSIS GUIDE"))
        body = QFrame()
        body.setObjectName("rightSection")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 14)
        self.guide_text = QLabel()
        self.guide_text.setObjectName("secondaryText")
        self.guide_text.setWordWrap(True)
        body_layout.addWidget(self.guide_text)
        body_layout.addStretch(1)
        layout.addWidget(body, 1)
        return frame

    def set_model(self, model: StructuralModel | None) -> None:
        self._model = model
        self.settings_panel.set_model(model)
        self._refresh_precheck()

    def set_source_path(self, source_path: Path | None) -> None:
        self._source_path = source_path
        self._refresh_precheck()

    def _refresh(self, kind: AnalysisKind) -> None:
        self.page_header.set_title(f"{_KIND_LABELS.get(kind, kind)} SETUP".upper())
        self._flow_list_widget.clear()
        steps = _FLOW_STEPS.get(kind, ())
        active_index = 2 if kind in (AnalysisKind.LINEAR_STATIC, AnalysisKind.NONLINEAR_STATIC) else 1
        for index, label in enumerate(steps):
            if index < active_index:
                prefix, color = "✓", "#087f5b"
            elif index == active_index:
                prefix, color = "⚠", "#00288e"
            else:
                prefix, color = "○", "#757684"
            item = QListWidgetItem(f"{prefix}   {index + 1}. {label}")
            item.setForeground(QBrush(QColor(color)))
            item.setSizeHint(QSize(190, 34))
            font = QFont()
            font.setPointSize(8)
            font.setBold(index == active_index)
            item.setFont(font)
            self._flow_list_widget.addItem(item)
        self.guide_text.setText(_GUIDE_TEXT.get(kind, ""))
        self._refresh_precheck()

    def _refresh_precheck(self) -> None:
        while self.precheck_chip_row.count() > 1:
            item = self.precheck_chip_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        errors, warnings = self._precheck()
        for label, state in self._status_chips():
            self.precheck_chip_row.insertWidget(
                self.precheck_chip_row.count() - 1, self._make_chip(label, state)
            )
        for message in errors:
            # Errors come straight from AnalysisModule.validate() - already short,
            # user-facing sentences, so the chip text and the tooltip are the same.
            self.precheck_chip_row.insertWidget(
                self.precheck_chip_row.count() - 1, self._make_chip(message, "error", message)
            )
        for label, detail in warnings:
            self.precheck_chip_row.insertWidget(
                self.precheck_chip_row.count() - 1, self._make_chip(label, "warn", detail)
            )

        issue_count = len(errors) + len(warnings)
        noun = "issue" if issue_count == 1 else "issues"
        if errors:
            self.precheck_summary.setText(f"{issue_count} {noun} block RUN")
            self.precheck_summary.setProperty("state", "error")
        elif warnings:
            verb = "requires" if issue_count == 1 else "require"
            self.precheck_summary.setText(f"{issue_count} {noun} {verb} review")
            self.precheck_summary.setProperty("state", "warn")
        else:
            self.precheck_summary.setText("✓ Ready to run")
            self.precheck_summary.setProperty("state", "ok")
        self.precheck_summary.style().unpolish(self.precheck_summary)
        self.precheck_summary.style().polish(self.precheck_summary)
        self.run_button.setDisabled(bool(errors))

    def _status_chips(self) -> list[tuple[str, str]]:
        """Booleans this page can actually vouch for - kept honest by only
        reporting state this class already tracks, never a feature (like
        geometric nonlinearity) the solver doesn't implement yet."""
        has_model = self._source_path is not None
        chips: list[tuple[str, str]] = [
            ("Model Valid" if has_model else "No Model", "ok" if has_model else "error")
        ]
        if self._model is not None:
            has_loads = bool(self._model.nodal_loads or self._model.element_loads)
            chips.append(("Loads Detected", "ok" if has_loads else "warn"))
        solver = self.config_store.options.get("system", "BandGeneral")
        chips.append((f"Solver: {solver}", "ok"))
        return chips

    @staticmethod
    def _make_chip(text: str, state: str, tooltip: str | None = None) -> QLabel:
        chip = QLabel(text)
        chip.setObjectName("precheckChip")
        chip.setProperty("state", state)
        chip.setToolTip(tooltip if tooltip is not None else text)
        return chip

    def _precheck(self) -> tuple[list[str], list[tuple[str, str]]]:
        if self._source_path is None:
            return (["먼저 모델 파일을 불러오세요."], [])
        if self._run_analysis_service is None:
            return ([], [])
        request = AnalysisRequest(
            source_path=self._source_path,
            kind=self.config_store.kind,
            options=self.config_store.options,
        )
        errors = self._run_analysis_service.validate(request)
        return (errors, _warnings_for(request))

    def _header(self, text: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("panelHeader")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.addWidget(QLabel(text))
        return frame


def _warnings_for(request: AnalysisRequest) -> list[tuple[str, str]]:
    """Non-blocking advisories, as (short chip label, full detail) - errors that
    stop RUN live in AnalysisModule.validate() instead (see
    RunAnalysisService.validate()). Kept to one small, honest rule for now; more
    can be added per analysis kind as options grow."""
    if request.kind == AnalysisKind.NONLINEAR_STATIC and request.options.get(
        "gravity_pattern"
    ) is None:
        detail = (
            "중력 하중 패턴이 지정되지 않았습니다 - 모든 하중 패턴이 함께 증가합니다. "
            "Gravity-then-push 절차를 원하면 NONLINEAR SETTINGS에서 GRAVITY PATTERN을 지정하세요."
        )
        return [("Gravity Pattern Not Set", detail)]
    return []
