"""Common Analysis Case sidebar - the first-pass skeleton of the
ANALYSIS CASE / QUICK SETTINGS / ASSIGNED DATA / PRE-CHECK sections shared by
every analysis method (see the approved plan at
``analysis_settings_sidebar``'s own commit for the full target design).

This pass only builds the *shell*: creating/renaming/duplicating/deleting
Analysis Cases, switching between them without one clobbering another's
settings, and a real (if currently two-rule) PRE-CHECK. Each method's actual
Quick Settings content is a placeholder page - it does not yet replace this
canvas's existing execution path (``ModelingInterfacePage.solve()``/
``_solve_nonlinear_static()``, still driven by ``self.analysis_method_
selector``/``self._analysis_settings`` exactly as before). This widget is
added *alongside* that existing UI, not instead of it, so nothing about how
Linear Static/Nonlinear Static actually run today changes in this pass.

The PRE-CHECK chip row/summary label styling is ported from
``app.shell.setup_workspace.SetupWorkspace``'s own ``precheck_chip_row``/
``_make_chip`` - the one place in this codebase that already renders
multiple simultaneous Error/Warning/Info-style status chips (every other
"status label" in this app, including this very page's own
``determinacy_status``, is a single last-message-wins QLabel).
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import AnalysisKind, StructuralModel
from openframe.features.model.presentation.analysis_case import (
    ANALYSIS_KIND_LABELS,
    AnalysisCase,
    CaseStatus,
)
from openframe.features.model.presentation.analysis_case_store import AnalysisCaseStore
from openframe.features.model.presentation.analysis_precheck import (
    PrecheckReport,
    Severity,
    run_precheck,
)
from openframe.features.model.presentation.current_page_only_stack import _CurrentPageOnlyStack
from openframe.features.model.presentation.quick_settings.time_history_quick_settings import (
    TimeHistoryQuickSettings,
)

#: (Korean status text, chip/QSS state) per CaseStatus - CaseStatus has 5
#: values but the chip vocabulary only has 4 colors (ok/warn/error/info), so
#: RUNNABLE and COMPLETE share "ok" (both mean "nothing is currently wrong"),
#: distinguished only by their own text.
_STATUS_CHIP: dict[CaseStatus, tuple[str, str]] = {
    CaseStatus.UNSET: ("미설정", "info"),
    CaseStatus.WARNING: ("경고", "warn"),
    CaseStatus.RUNNABLE: ("실행가능", "ok"),
    CaseStatus.COMPLETE: ("완료", "ok"),
    CaseStatus.FAILED: ("실패", "error"),
}

#: PrecheckIssue.severity -> precheckChip QSS "state" property value.
_SEVERITY_CHIP_STATE: dict[Severity, str] = {
    Severity.ERROR: "error",
    Severity.WARNING: "warn",
    Severity.INFO: "info",
}


def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Same white-card-on-tinted-background style every other settings
    section in this page already uses (``ModelingInterfacePage._section``) -
    duplicated rather than imported to avoid a circular import (that method
    lives on the class this sidebar is embedded inside)."""
    section = QFrame()
    section.setObjectName("propertySectionCard")
    layout = QVBoxLayout(section)
    layout.setContentsMargins(10, 9, 10, 9)
    layout.setSpacing(6)
    label = QLabel(title)
    label.setObjectName("setupSectionTitle")
    layout.addWidget(label)
    return section, layout


def _make_chip(text: str, state: str, tooltip: str | None = None) -> QLabel:
    chip = QLabel(text)
    chip.setObjectName("precheckChip")
    chip.setProperty("state", state)
    chip.setToolTip(tooltip if tooltip is not None else text)
    return chip


def _repolish(widget: QWidget) -> None:
    """Force Qt to re-evaluate this widget's QSS ``[state=...]`` selector
    after ``setProperty`` - a plain ``setProperty`` call does not trigger a
    style refresh on its own (same idiom ``setup_workspace.py`` uses)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class AnalysisSettingsSidebar(QWidget):
    def __init__(
        self,
        store: AnalysisCaseStore,
        build_model: Callable[[], StructuralModel],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._build_model = build_model
        if not store.list_cases():
            store.add_case(AnalysisKind.LINEAR_STATIC, "LS-1")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addWidget(self._build_case_section())
        root.addWidget(self._build_quick_settings_section())
        root.addWidget(self._build_assigned_data_section())
        root.addWidget(self._build_precheck_section())

        self._store.case_added.connect(self._refresh_case_selector)
        self._store.case_removed.connect(self._refresh_case_selector)
        self._store.case_renamed.connect(self._refresh_case_selector)
        self._store.active_case_changed.connect(self._on_active_case_changed)
        self._store.precheck_changed.connect(self._on_precheck_changed)

        self._refresh_case_selector()
        self._refresh_quick_settings_page()
        self.refresh_precheck()

    # -- ANALYSIS CASE ----------------------------------------------------
    def _build_case_section(self) -> QFrame:
        section, layout = _section("ANALYSIS CASE")

        case_row = QHBoxLayout()
        self.case_selector = QComboBox()
        self.case_selector.currentIndexChanged.connect(self._on_case_selector_changed)
        case_row.addWidget(self.case_selector, 1)
        add_button = QToolButton()
        add_button.setText("+")
        add_button.setToolTip("케이스 추가/복제/이름변경/삭제")
        add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_button.setMenu(self._build_case_menu())
        case_row.addWidget(add_button)
        layout.addLayout(case_row)

        self.case_method_label = QLabel()
        self.case_method_label.setObjectName("setupSectionHint")
        layout.addWidget(self.case_method_label)

        self.case_status_chip = _make_chip("", "info")
        layout.addWidget(self.case_status_chip, 0, Qt.AlignmentFlag.AlignLeft)

        return section

    def _build_case_menu(self) -> QMenu:
        menu = QMenu(self)
        new_menu = menu.addMenu("새로 만들기")
        for kind, label in ANALYSIS_KIND_LABELS.items():
            new_menu.addAction(label, lambda checked=False, kind=kind: self._create_case(kind))
        menu.addAction("복제", self._duplicate_active_case)
        menu.addAction("이름 변경...", self._rename_active_case)
        menu.addAction("삭제", self._delete_active_case)
        return menu

    def _create_case(self, kind: AnalysisKind) -> None:
        case_id = self._store.add_case(kind)
        self._store.set_active_case(case_id)

    def _duplicate_active_case(self) -> None:
        active_id = self._store.active_case_id()
        if active_id is None:
            return
        new_id = self._store.duplicate_case(active_id)
        if new_id is not None:
            self._store.set_active_case(new_id)

    def _rename_active_case(self) -> None:
        active_id = self._store.active_case_id()
        if active_id is None:
            return
        case = self._store.case(active_id)
        name, accepted = QInputDialog.getText(self, "이름 변경", "케이스 이름", text=case.name)
        if accepted and name.strip():
            self._store.rename_case(active_id, name.strip())

    def _delete_active_case(self) -> None:
        active_id = self._store.active_case_id()
        if active_id is not None:
            self._store.delete_case(active_id)

    def _refresh_case_selector(self, _case_id: str | None = None) -> None:
        combo = self.case_selector
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for case in self._store.list_cases():
            combo.addItem(case.name, case.case_id)
        active_id = self._store.active_case_id()
        index = combo.findData(active_id if active_id is not None else previous)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self._refresh_active_case_display()

    def _on_case_selector_changed(self, _index: int) -> None:
        case_id = self.case_selector.currentData()
        if case_id is not None:
            self._store.set_active_case(case_id)

    def _on_active_case_changed(self, _case_id: str) -> None:
        self._refresh_case_selector()
        self._refresh_quick_settings_page()
        self.refresh_precheck()

    def _refresh_active_case_display(self) -> None:
        active_id = self._store.active_case_id()
        if active_id is None or not self._store.has_case(active_id):
            self.case_method_label.setText("")
            self.case_status_chip.setText("")
            return
        case = self._store.case(active_id)
        self.case_method_label.setText(ANALYSIS_KIND_LABELS.get(case.kind, case.kind.value))
        text, state = _STATUS_CHIP[case.status]
        self.case_status_chip.setText(text)
        self.case_status_chip.setProperty("state", state)
        _repolish(self.case_status_chip)

    # -- QUICK SETTINGS -----------------------------------------------------
    def _build_quick_settings_section(self) -> QFrame:
        section, layout = _section("QUICK SETTINGS")
        self.quick_settings_stack = _CurrentPageOnlyStack()
        self.quick_settings_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.quick_settings_stack.currentChanged.connect(
            lambda _index: self.quick_settings_stack.updateGeometry()
        )
        self._quick_pages: dict[AnalysisKind, int] = {}
        self._quick_widgets: dict[AnalysisKind, QWidget] = {}
        for kind, label in ANALYSIS_KIND_LABELS.items():
            page = self._build_quick_settings_page(kind, label)
            self._quick_widgets[kind] = page
            self._quick_pages[kind] = self.quick_settings_stack.addWidget(page)
        layout.addWidget(self.quick_settings_stack)
        return section

    def _build_quick_settings_page(self, kind: AnalysisKind, label: str) -> QWidget:
        if kind is AnalysisKind.TIME_HISTORY:
            page = TimeHistoryQuickSettings()
            page.settings_changed.connect(
                lambda settings, kind=kind: self._on_quick_settings_changed(kind, settings)
            )
            return page
        placeholder = QLabel(f"{label}\n설정 항목은 다음 단계에서 추가됩니다.")
        placeholder.setObjectName("setupSectionHint")
        placeholder.setWordWrap(True)
        placeholder.setMaximumWidth(240)
        return placeholder

    def _refresh_quick_settings_page(self) -> None:
        active_id = self._store.active_case_id()
        if active_id is None or not self._store.has_case(active_id):
            return
        case = self._store.case(active_id)
        page_index = self._quick_pages.get(case.kind)
        if page_index is not None:
            self.quick_settings_stack.setCurrentIndex(page_index)
            self.quick_settings_stack.updateGeometry()
        widget = self._quick_widgets.get(case.kind)
        load_settings = getattr(widget, "load_settings", None)
        if callable(load_settings):
            load_settings(case.settings)

    def _on_quick_settings_changed(self, kind: AnalysisKind, settings: dict[str, object]) -> None:
        active_id = self._store.active_case_id()
        if active_id is None or not self._store.has_case(active_id):
            return
        case = self._store.case(active_id)
        if case.kind is not kind:
            return
        case.settings = settings
        self.refresh_precheck()

    # -- ASSIGNED DATA ------------------------------------------------------
    def _build_assigned_data_section(self) -> QFrame:
        section, layout = _section("ASSIGNED DATA")
        hint = QLabel("연결된 데이터 항목은 다음 단계에서 추가됩니다.")
        hint.setObjectName("setupSectionHint")
        hint.setWordWrap(True)
        hint.setMaximumWidth(240)
        layout.addWidget(hint)
        return section

    # -- PRE-CHECK ------------------------------------------------------
    def _build_precheck_section(self) -> QFrame:
        section, layout = _section("PRE-CHECK")
        self.precheck_chip_row = QHBoxLayout()
        self.precheck_chip_row.setSpacing(6)
        self.precheck_chip_row.addStretch(1)
        layout.addLayout(self.precheck_chip_row)
        self.precheck_summary = QLabel()
        self.precheck_summary.setObjectName("precheckSummary")
        self.precheck_summary.setWordWrap(True)
        layout.addWidget(self.precheck_summary)
        return section

    def refresh_precheck(self) -> None:
        active_id = self._store.active_case_id()
        if active_id is None or not self._store.has_case(active_id):
            return
        case = self._store.case(active_id)
        report = run_precheck(case, self._build_model())
        self._store.set_precheck(active_id, report)
        self._render_precheck(report)

    def _on_precheck_changed(self, case_id: str) -> None:
        if case_id != self._store.active_case_id():
            return
        self._refresh_active_case_display()
        case = self._store.case(case_id)
        report = case.last_precheck
        if isinstance(report, PrecheckReport):
            self._render_precheck(report)

    def _render_precheck(self, report: PrecheckReport) -> None:
        while self.precheck_chip_row.count() > 1:
            item = self.precheck_chip_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for issue in report.issues:
            self.precheck_chip_row.insertWidget(
                self.precheck_chip_row.count() - 1,
                _make_chip(issue.message, _SEVERITY_CHIP_STATE[issue.severity], issue.detail),
            )

        error_count = sum(1 for issue in report.issues if issue.severity is Severity.ERROR)
        warning_count = sum(1 for issue in report.issues if issue.severity is Severity.WARNING)
        if error_count:
            self.precheck_summary.setText(f"{error_count}개 문제로 실행할 수 없습니다")
            self.precheck_summary.setProperty("state", "error")
        elif warning_count:
            self.precheck_summary.setText(f"{warning_count}개 경고가 있습니다")
            self.precheck_summary.setProperty("state", "warn")
        else:
            self.precheck_summary.setText("✓ 실행 가능")
            self.precheck_summary.setProperty("state", "ok")
        _repolish(self.precheck_summary)
