"""Stitch-inspired structural analysis application shell."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from openframe.app.shell.analysis_progress_banner import AnalysisProgressBanner
from openframe.app.shell.analysis_results_sidebar import AnalysisResultsSidebar
from openframe.app.shell.app_header import AppHeader
from openframe.app.shell.modeling_workflow import ModelingWorkflowBar
from openframe.app.shell.start_workspace import StartWorkspace
from openframe.app.shell.workspace_navigation import WorkspaceNavigation
from openframe.core.domain import (
    AnalysisKind,
    AnalysisRequest,
    AnalysisResult,
    AnalysisStatus,
    StructuralModel,
    UnitSystem,
)
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.presentation.analysis_run_thread import AnalysisRunThread
from openframe.features.model.application.open_model import OpenModelService
from openframe.features.model.presentation.model_load_thread import ModelLoadThread
from openframe.features.model.presentation.model_sidebar import ModelSidebar
from openframe.features.results.presentation.results_workspace import ResultsWorkspace
from openframe.features.viewport.presentation.model_viewport import ModelViewport


@dataclass(slots=True)
class _WorkspaceSession:
    key: str
    title: str
    source_path: Path
    model: StructuralModel
    result: AnalysisResult | None = None
    section: str = "model"


class MainWindow(QMainWindow):
    def __init__(
        self,
        open_model_service: OpenModelService | None = None,
        run_analysis_service: RunAnalysisService | None = None,
    ) -> None:
        super().__init__()
        self._open_model_service = open_model_service
        self._run_analysis_service = run_analysis_service
        self._model_load_thread: ModelLoadThread | None = None
        self._analysis_run_thread: AnalysisRunThread | None = None
        self._current_model_source: Path | None = None
        self._model_generation = 0
        self._resume_section = "model"
        self._has_active_workspace = False
        self._workspace_sessions: dict[str, _WorkspaceSession] = {}
        self._current_session_key: str | None = None
        self.setWindowTitle("OpenFrame Studio")
        self.resize(1440, 860)
        self.setMinimumSize(980, 620)

        root = QWidget()
        root.setObjectName("applicationRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.header = AppHeader()
        self.navigation = WorkspaceNavigation()
        self.analysis_progress = AnalysisProgressBanner(self)
        self.start_workspace = StartWorkspace()
        self.model_sidebar = ModelSidebar()
        self.viewport = ModelViewport()
        self.analysis_sidebar = AnalysisResultsSidebar()
        self.analysis_settings = self.analysis_sidebar.settings
        self.model_inspector = self.analysis_sidebar.inspector
        self.results_workspace = ResultsWorkspace()
        self.view = self.viewport.view
        self.scene = self.viewport.scene

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self.model_sidebar)
        self.workspace_splitter.addWidget(self.viewport)
        self.workspace_splitter.addWidget(self.analysis_sidebar)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes((255, 850, 300))

        self.modeling_workflow = ModelingWorkflowBar()
        self.workspace = QWidget()
        self.workspace.setObjectName("modelingWorkspace")
        modeling_layout = QVBoxLayout(self.workspace)
        modeling_layout.setContentsMargins(0, 0, 0, 0)
        modeling_layout.setSpacing(0)
        modeling_layout.addWidget(self.modeling_workflow)
        modeling_layout.addWidget(self.workspace_splitter, 1)

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.setObjectName("workspaceStack")
        self.workspace_stack.addWidget(self.start_workspace)
        self.workspace_stack.addWidget(self.workspace)
        self.workspace_stack.addWidget(self.results_workspace)
        self.workspace_stack.setCurrentWidget(self.start_workspace)

        root_layout.addWidget(self.header)
        workspace_shell = QWidget()
        workspace_shell.setObjectName("workspaceShell")
        workspace_shell_layout = QHBoxLayout(workspace_shell)
        workspace_shell_layout.setContentsMargins(0, 0, 0, 0)
        workspace_shell_layout.setSpacing(0)
        workspace_shell_layout.addWidget(self.navigation)
        workspace_shell_layout.addWidget(self.workspace_stack, 1)
        root_layout.addWidget(workspace_shell, 1)
        self.setCentralWidget(root)

        self._build_status_bar()
        self._connect_actions()
        self._show_start_workspace()

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        status.showMessage("준비됨")
        self.status_model = QLabel("● 모델 대기")
        self.status_model.setObjectName("statusModel")
        self.status_counts = QLabel("절점 0  |  요소 0")
        self.status_units = QLabel("2D · NDF 3  |  kN, m")
        status.addPermanentWidget(self.status_model)
        status.addPermanentWidget(self.status_counts)
        status.addPermanentWidget(self.status_units)
        self.setStatusBar(status)

    def _connect_actions(self) -> None:
        self.header.upload_requested.connect(self._choose_model_file)
        self.header.run_requested.connect(self._run_analysis)
        self.header.export_requested.connect(
            lambda: self._show_pending_workflow("OpenSeesPy 코드 내보내기")
        )
        self.header.home_requested.connect(self._show_start_workspace)
        self.start_workspace.import_opensees_requested.connect(self._start_import_workspace)
        self.start_workspace.new_model_requested.connect(self._start_new_model_workspace)
        self.start_workspace.template_requested.connect(
            lambda: self._show_pending_workflow("Template Browser")
        )
        self.start_workspace.open_project_requested.connect(
            lambda: self._show_pending_workflow("Open Project")
        )
        self.start_workspace.resume_workspace_requested.connect(self._resume_workspace)
        self.start_workspace.session_requested.connect(self._activate_workspace_session)
        self.navigation.current_changed.connect(self._change_workspace_section)
        self.analysis_settings.analysis_kind_changed.connect(self._set_analysis_kind)
        self.viewport.unit_system_changed.connect(self._set_unit_system)
        self.viewport.entity_selected.connect(self._entity_selected_from_viewport)
        self.model_sidebar.entity_selected.connect(self._entity_selected_from_tree)
        self.modeling_workflow.step_selected.connect(self._select_modeling_step)
        self.analysis_settings.hide()

    def _select_modeling_step(self, step: str) -> None:
        """Expose the authoring order now; feature editors are connected later."""
        navigation_sections = {"loads": "loads", "analysis": "analysis"}
        section = navigation_sections.get(step, "model")
        self.navigation.set_current_section(section)
        self._change_workspace_section(section)
        step_names = {
            key: label for key, label, _tooltip in self.modeling_workflow.STEPS
        }
        self.statusBar().showMessage(
            f"{step_names[step]} 단계 · 편집 기능은 다음 구현 단계에서 연결됩니다"
        )

    def _set_unit_system(self, unit_system: UnitSystem) -> None:
        self.model_inspector.set_unit_system(unit_system)
        self.results_workspace.set_unit_system(unit_system)
        self.statusBar().showMessage(f"Model units changed | {unit_system.label}")
        self.status_units.setText(f"{self.viewport._model.ndm if self.viewport._model else 2}D · "
                                  f"NDF {self.viewport._model.ndf if self.viewport._model else 3}"
                                  f"  |  {unit_system.label}")

    def _show_start_workspace(self) -> None:
        if self.workspace_stack.currentWidget() is not self.start_workspace:
            self._resume_section = self.navigation.current_section()
            self._store_current_session_section(self._resume_section)
        self._refresh_start_sessions()
        self.workspace_stack.setCurrentWidget(self.start_workspace)
        self.navigation.hide()
        self.header.set_welcome_mode(True)
        self.statusBar().showMessage("Choose how to start a project")

    def _show_pending_workflow(self, workflow: str) -> None:
        self.statusBar().showMessage(f"{workflow} interface is ready for feature connection")

    def _start_import_workspace(self) -> None:
        self._has_active_workspace = True
        if self._workspace_sessions:
            self._refresh_start_sessions()
        else:
            self.start_workspace.set_current_session(
                "OpenSeesPy Import", "Waiting for a .py source file"
            )
        self.modeling_workflow.set_current_step("geometry")
        self._show_model_workspace()
        self.statusBar().showMessage(
            "OpenSeesPy import workspace | Select UPLOAD .PY to choose a model"
        )

    def _start_new_model_workspace(self) -> None:
        """Open the authoring shell at its first prerequisite step."""
        self._has_active_workspace = True
        self._current_model_source = None
        self.header.set_project_title("새 구조 모델")
        self.modeling_workflow.set_current_step("setup")
        self._show_model_workspace()
        self.statusBar().showMessage(
            "기본 설정 단계 · 모델 차원, 자유도와 단위 설정 기능을 연결할 예정입니다"
        )

    def _show_model_workspace(self) -> None:
        self._resume_section = "model"
        self.navigation.set_current_section("model")
        self.navigation.show()
        self.header.set_welcome_mode(False)
        self.workspace_stack.setCurrentWidget(self.workspace)
        self.model_sidebar.show()
        self.analysis_sidebar.show()
        self.analysis_settings.hide()
        self.model_inspector.show()
        self.viewport.set_code_panel_visible(False)

    def _resume_workspace(self) -> None:
        if not self._has_active_workspace:
            return
        self.navigation.show()
        self.header.set_welcome_mode(False)
        self.navigation.set_current_section(self._resume_section)
        self._change_workspace_section(self._resume_section)

    def _open_results_workspace(self) -> None:
        self.analysis_progress.hide()
        self.navigation.show()
        self.header.set_welcome_mode(False)
        self.navigation.set_current_section("results", emit=True)

    def _choose_model_file(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "OpenSeesPy 코드 열기",
            "",
            "Python 파일 (*.py);;모든 파일 (*.*)",
        )
        if source:
            self.model_sidebar.set_source_file(source)
            self._start_model_load(Path(source))

    def _start_model_load(self, source: Path) -> None:
        if self._open_model_service is None:
            QMessageBox.critical(self, "모델 가져오기", "모델 가져오기 서비스가 없습니다.")
            return
        if self._model_load_thread and self._model_load_thread.isRunning():
            return
        if self._analysis_run_thread and self._analysis_run_thread.isRunning():
            return

        # Invalidate every result associated with the model currently on screen as
        # soon as a different source starts loading. A queued completion signal from
        # an older run must never attach itself to the incoming model.
        self._model_generation += 1
        self.analysis_progress.reset()
        self.results_workspace.clear_result()
        self.header.set_busy(True)
        self.statusBar().showMessage(f"Reading model · {source.name}")
        thread = ModelLoadThread(self._open_model_service, source)
        thread.loaded.connect(self._model_loaded)
        thread.failed.connect(self._model_load_failed)
        thread.finished.connect(self._model_load_finished)
        self._model_load_thread = thread
        thread.start()

    def _model_loaded(self, model: object, source: str) -> None:
        self._has_active_workspace = True
        source_path = Path(source).resolve()
        self._current_model_source = source_path
        self.model_sidebar.set_source_file(source)
        self.model_sidebar.set_model(model)
        self.viewport.set_model(model)
        self.model_inspector.set_model(model)
        self.results_workspace.set_model(model)
        self.results_workspace.clear_result()
        self.header.set_project_title(source_path.stem)
        self.modeling_workflow.set_current_step("geometry")
        self.status_model.setText("● 모델 유효")
        self.status_model.setObjectName("statusModelReady")
        self.status_model.style().unpolish(self.status_model)
        self.status_model.style().polish(self.status_model)
        self.status_counts.setText(f"절점 {len(model.nodes)}  |  요소 {len(model.elements)}")
        self.status_units.setText(f"{model.ndm}D · NDF {model.ndf}  |  {self.viewport.unit_system.label}")
        key = str(source_path)
        self._remember_session(
            _WorkspaceSession(
                key=key,
                title=source_path.name,
                source_path=source_path,
                model=model,
            )
        )
        self._current_session_key = key
        self._refresh_start_sessions()
        self._show_model_workspace()
        self.statusBar().showMessage(
            f"Model loaded · Nodes {len(model.nodes)} · Elements {len(model.elements)}"
        )

    def _model_load_failed(self, message: str) -> None:
        self.statusBar().showMessage("Model import failed")
        QMessageBox.critical(self, "모델을 불러올 수 없습니다", message)

    def _model_load_finished(self) -> None:
        self.header.set_busy(False)
        thread = self._model_load_thread
        self._model_load_thread = None
        if thread is not None:
            thread.deleteLater()

    def _change_workspace_section(self, section: str) -> None:
        self._store_current_session_section(section)
        labels = {
            "model": "Model workspace",
            "loads": "Load assignment workspace",
            "analysis": "Analysis configuration",
            "results": "Analysis results",
            "code": "OpenSeesPy code workspace",
            "viewport": "Viewport focus",
        }
        if section == "results":
            self.workspace_stack.setCurrentWidget(self.results_workspace)
            self.statusBar().showMessage("Results workspace | Ready")
            return

        self.workspace_stack.setCurrentWidget(self.workspace)
        focus_viewport = section == "viewport"
        self.model_sidebar.setVisible(section in {"model", "loads"})
        self.analysis_sidebar.setVisible(not focus_viewport)
        self.analysis_settings.setVisible(section == "analysis")
        self.model_inspector.setVisible(section != "analysis")
        self.viewport.set_code_panel_visible(section == "code")
        self.statusBar().showMessage(f"{labels[section]} · Ready")

    def _set_analysis_kind(self, kind: AnalysisKind) -> None:
        names = {
            AnalysisKind.LINEAR_STATIC: "Linear Static",
            AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
            AnalysisKind.TIME_HISTORY: "Time History",
        }
        self.results_workspace.set_analysis_kind(kind)
        self.statusBar().showMessage(f"Analysis type · {names[kind]}")

    def _run_analysis(self) -> None:
        kind = self.analysis_settings.selected_analysis_kind()
        self._set_analysis_kind(kind)

        if self._run_analysis_service is None:
            QMessageBox.critical(self, "해석 실행", "해석 실행 서비스가 없습니다.")
            return
        if self._current_model_source is None:
            QMessageBox.warning(self, "해석 실행", "먼저 모델 파일을 불러오세요.")
            return
        if self._analysis_run_thread and self._analysis_run_thread.isRunning():
            return

        request = AnalysisRequest(source_path=self._current_model_source, kind=kind)
        run_generation = self._model_generation
        run_session_key = self._current_session_key

        # The previous run's numbers must not linger next to a fresh one.
        self.results_workspace.clear_result()
        analysis_name = {
            AnalysisKind.LINEAR_STATIC: "Linear Static",
            AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
            AnalysisKind.TIME_HISTORY: "Time History",
        }[kind]
        self.analysis_progress.show_running(analysis_name)
        self.header.set_busy(True, None)
        self.statusBar().showMessage(f"Running analysis · {kind.value}")
        thread = AnalysisRunThread(self._run_analysis_service, request)
        thread.completed.connect(
            lambda result: self._analysis_completed(
                result,
                run_generation=run_generation,
                run_session_key=run_session_key,
            )
        )
        thread.finished.connect(self._analysis_run_finished)
        self._analysis_run_thread = thread
        thread.start()

    def _analysis_completed(
        self,
        result: AnalysisResult,
        *,
        run_generation: int,
        run_session_key: str | None,
    ) -> None:
        if (
            run_generation != self._model_generation
            or run_session_key is None
            or run_session_key != self._current_session_key
        ):
            self.analysis_progress.hide()
            self.statusBar().showMessage(
                "Discarded an analysis result from a previously opened model"
            )
            return

        self.results_workspace.show_result(result)
        if run_session_key in self._workspace_sessions:
            self._workspace_sessions[run_session_key].result = result
            self._refresh_start_sessions()
        if result.status == AnalysisStatus.COMPLETED:
            self.analysis_progress.show_completed(
                f"Results are ready for {len(result.node_results)} nodes and "
                f"{len(result.element_results)} elements."
            )
            self.statusBar().showMessage(
                f"Analysis completed · Nodes {len(result.node_results)}"
                f" · Elements {len(result.element_results)}"
            )
            QMessageBox.information(
                self,
                "해석 완료",
                "해석이 완료되었습니다.\n\n"
                f"절점 결과: {len(result.node_results)}개\n"
                f"부재 결과: {len(result.element_results)}개\n\n"
                "RESULTS 탭에서 결과를 확인할 수 있습니다.",
            )
        else:
            self.analysis_progress.show_failed(
                " ".join(result.messages) or "The solver returned an unknown error."
            )
            self.statusBar().showMessage("Analysis failed")
            QMessageBox.critical(
                self, "해석 실행 실패", "\n".join(result.messages) or "알 수 없는 해석 오류"
            )

    def _entity_selected_from_viewport(self, kind: str, tag: int) -> None:
        self.model_sidebar.select_entity(kind, tag)
        self.model_inspector.select_entity(kind, tag)

    def _entity_selected_from_tree(self, kind: str, tag: int) -> None:
        self.viewport.select_entity(kind, tag)
        self.model_inspector.select_entity(kind, tag)

    def _analysis_run_finished(self) -> None:
        self.header.set_busy(False)
        thread = self._analysis_run_thread
        self._analysis_run_thread = None
        if thread is not None:
            thread.deleteLater()

    def _remember_session(self, session: _WorkspaceSession) -> None:
        self._workspace_sessions.pop(session.key, None)
        self._workspace_sessions[session.key] = session
        while len(self._workspace_sessions) > 4:
            oldest_key = next(iter(self._workspace_sessions))
            del self._workspace_sessions[oldest_key]

    def _store_current_session_section(self, section: str) -> None:
        if self._current_session_key in self._workspace_sessions:
            self._workspace_sessions[self._current_session_key].section = section

    def _refresh_start_sessions(self) -> None:
        sessions = [
            (
                session.key,
                session.title,
                f"{session.title} · OpenSeesPy · {session.source_path.parent}",
            )
            for session in reversed(self._workspace_sessions.values())
        ]
        if sessions:
            self.start_workspace.set_sessions(sessions, self._current_session_key)

    def _activate_workspace_session(self, key: str) -> None:
        session = self._workspace_sessions.get(key)
        if session is None:
            return

        self._store_current_session_section(self.navigation.current_section())
        self._workspace_sessions.pop(key)
        self._workspace_sessions[key] = session
        self._current_session_key = key
        self._current_model_source = session.source_path
        self._has_active_workspace = True

        self.model_sidebar.set_source_file(str(session.source_path))
        self.model_sidebar.set_model(session.model)
        self.viewport.set_model(session.model)
        self.model_inspector.set_model(session.model)
        self.results_workspace.set_model(session.model)
        self.results_workspace.clear_result()
        if session.result is not None:
            self.results_workspace.show_result(session.result)

        self.analysis_progress.reset()
        self._resume_section = session.section
        self.navigation.show()
        self.header.set_welcome_mode(False)
        self.navigation.set_current_section(session.section)
        self._change_workspace_section(session.section)
        self._refresh_start_sessions()
        self.statusBar().showMessage(f"Workspace restored | {session.title}")
