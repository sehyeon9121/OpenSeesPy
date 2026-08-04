"""Stitch-inspired structural analysis application shell."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from openframe.app.shell.analysis_results_sidebar import AnalysisResultsSidebar
from openframe.app.shell.app_header import AppHeader
from openframe.app.shell.workspace_navigation import WorkspaceNavigation
from openframe.core.domain import (
    AnalysisKind,
    AnalysisRequest,
    AnalysisResult,
    AnalysisStatus,
    UnitSystem,
)
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.presentation.analysis_run_thread import AnalysisRunThread
from openframe.features.model.application.open_model import OpenModelService
from openframe.features.model.presentation.model_load_thread import ModelLoadThread
from openframe.features.model.presentation.model_sidebar import ModelSidebar
from openframe.features.viewport.presentation.model_viewport import ModelViewport


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
        self.model_sidebar = ModelSidebar()
        self.viewport = ModelViewport()
        self.analysis_sidebar = AnalysisResultsSidebar()
        self.analysis_settings = self.analysis_sidebar.settings
        self.results_panel = self.analysis_sidebar.results
        self.view = self.viewport.view
        self.scene = self.viewport.scene

        self.workspace = QSplitter(Qt.Orientation.Horizontal)
        self.workspace.setObjectName("workspaceSplitter")
        self.workspace.setChildrenCollapsible(False)
        self.workspace.addWidget(self.model_sidebar)
        self.workspace.addWidget(self.viewport)
        self.workspace.addWidget(self.analysis_sidebar)
        self.workspace.setStretchFactor(0, 0)
        self.workspace.setStretchFactor(1, 1)
        self.workspace.setStretchFactor(2, 0)
        self.workspace.setSizes((255, 850, 300))

        root_layout.addWidget(self.header)
        root_layout.addWidget(self.navigation)
        root_layout.addWidget(self.workspace, 1)
        self.setCentralWidget(root)

        self._build_status_bar()
        self._connect_actions()

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        status.showMessage("Ready · Sample preview · Units: kN, m")
        self.setStatusBar(status)

    def _connect_actions(self) -> None:
        self.header.upload_requested.connect(self._choose_model_file)
        self.header.run_requested.connect(self._run_analysis)
        self.navigation.current_changed.connect(self._change_workspace_section)
        self.analysis_settings.analysis_kind_changed.connect(self._set_analysis_kind)
        self.viewport.unit_system_changed.connect(self._set_unit_system)

    def _set_unit_system(self, unit_system: UnitSystem) -> None:
        self.results_panel.set_unit_system(unit_system)
        self.statusBar().showMessage(f"Model units changed | {unit_system.label}")

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

        self.header.set_busy(True)
        self.statusBar().showMessage(f"Reading model · {source.name}")
        thread = ModelLoadThread(self._open_model_service, source)
        thread.loaded.connect(self._model_loaded)
        thread.failed.connect(self._model_load_failed)
        thread.finished.connect(self._model_load_finished)
        self._model_load_thread = thread
        thread.start()

    def _model_loaded(self, model: object, source: str) -> None:
        self._current_model_source = Path(source)
        self.model_sidebar.set_source_file(source)
        self.model_sidebar.set_model(model)
        self.viewport.set_model(model)
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
        labels = {
            "model": "Model workspace",
            "analysis": "Analysis configuration",
            "results": "Analysis results",
            "viewport": "Viewport focus",
        }
        focus_viewport = section == "viewport"
        self.model_sidebar.setVisible(not focus_viewport)
        self.analysis_sidebar.setVisible(not focus_viewport)
        if section == "results":
            self.results_panel.result_tabs.setFocus()
        self.statusBar().showMessage(f"{labels[section]} · Ready")

    def _set_analysis_kind(self, kind: AnalysisKind) -> None:
        names = {
            AnalysisKind.LINEAR_STATIC: "Linear Static",
            AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
            AnalysisKind.TIME_HISTORY: "Time History",
        }
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

        self.header.set_busy(True, "RUNNING ANALYSIS")
        self.statusBar().showMessage(f"Running analysis · {kind.value}")
        thread = AnalysisRunThread(self._run_analysis_service, request)
        thread.completed.connect(self._analysis_completed)
        thread.finished.connect(self._analysis_run_finished)
        self._analysis_run_thread = thread
        thread.start()

    def _analysis_completed(self, result: AnalysisResult) -> None:
        self.results_panel.show_result(result)
        if result.status == AnalysisStatus.COMPLETED:
            self.statusBar().showMessage(
                f"Analysis completed · Nodes {len(result.node_results)}"
                f" · Elements {len(result.element_results)}"
            )
        else:
            self.statusBar().showMessage("Analysis failed")
            QMessageBox.critical(
                self, "해석 실행 실패", "\n".join(result.messages) or "알 수 없는 해석 오류"
            )

    def _analysis_run_finished(self) -> None:
        self.header.set_busy(False)
        thread = self._analysis_run_thread
        self._analysis_run_thread = None
        if thread is not None:
            thread.deleteLater()
