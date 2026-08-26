"""Stitch-inspired structural analysis application shell."""

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openframe import __version__ as _APP_VERSION

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
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
from openframe.app.shell.app_header import APP_ICON_PATH, AppHeader
from openframe.app.shell.direct_model_workspace import DirectModelWorkspace
from openframe.app.shell.imported_model_units import (
    ImportedModelUnitDialog,
    ImportedModelUnitStore,
    unit_system_from_metadata,
)
from openframe.app.shell.page_header import PageHeader
from openframe.app.shell.setup_workspace import SetupWorkspace
from openframe.app.shell.start_workspace import StartWorkspace
from openframe.app.shell.workspace_navigation import WorkspaceNavigation
from openframe.core.domain import (
    AnalysisKind,
    AnalysisResult,
    AnalysisStatus,
    StructuralModel,
    UnitSystem,
)
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.presentation.analysis_config_store import (
    AnalysisConfigStore,
)
from openframe.features.analysis.presentation.analysis_run_thread import AnalysisRunThread
from openframe.features.analysis.statics import export_opensees_script
from openframe.features.model.application.open_model import OpenModelService
from openframe.features.model.presentation.model_load_thread import ModelLoadThread
from openframe.features.model.presentation.model_sidebar import ModelSidebar
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
from openframe.features.results.presentation.results_workspace import ResultsWorkspace
from openframe.features.templates.catalog import TemplateEntry
from openframe.features.templates.presentation.template_gallery_page import TemplateGalleryPage
from openframe.features.viewport.presentation.model_viewport import ModelViewport


@dataclass(slots=True)
class _WorkspaceSession:
    key: str
    title: str
    source_path: Path
    model: StructuralModel
    unit_system: UnitSystem
    result: AnalysisResult | None = None
    section: str = "model"


@dataclass(slots=True)
class _DirectWorkspaceSession:
    key: str
    title: str
    ndm: int
    project_data: dict[str, object]
    step: str = "geometry"
    source_path: Path | None = None


class MainWindow(QMainWindow):
    def __init__(
        self,
        open_model_service: OpenModelService | None = None,
        run_analysis_service: RunAnalysisService | None = None,
        imported_unit_resolver: Callable[[Path], UnitSystem | None] | None = None,
    ) -> None:
        super().__init__()
        self._open_model_service = open_model_service
        self._run_analysis_service = run_analysis_service
        self._imported_unit_store = ImportedModelUnitStore()
        self._imported_unit_resolver = (
            imported_unit_resolver or self._resolve_undeclared_imported_units
        )
        self._model_load_thread: ModelLoadThread | None = None
        self._analysis_run_thread: AnalysisRunThread | None = None
        #: Set right before a precision-analysis template's generated script
        #: starts loading (see _open_precision_template); consumed exactly
        #: once, in _model_loaded, once the model has actually reached
        #: setup_workspace/analysis_settings and their model-dependent
        #: widgets are populated.
        self._pending_analysis_preset: tuple[AnalysisKind, dict, str] | None = None
        self._current_model_source: Path | None = None
        self._model_generation = 0
        self._resume_section = "model"
        self._has_active_workspace = False
        self._workspace_sessions: dict[str, _WorkspaceSession] = {}
        self._direct_workspace_sessions: dict[str, _DirectWorkspaceSession] = {}
        self._recent_session_keys: list[str] = []
        self._current_session_key: str | None = None
        self._current_direct_session_key: str | None = None
        self._direct_session_sequence = 0
        self.setWindowTitle("OpenFrame Studio")
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
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
        self.template_gallery_page = TemplateGalleryPage()
        self.direct_model_workspace = DirectModelWorkspace()
        self.model_sidebar = ModelSidebar()
        self.viewport = ModelViewport()
        # The single source of truth for the selected analysis kind and its options -
        # MODEL's type selector, SETUP's settings panel and the Nonlinear Settings
        # dialog all read and write through this one instance.
        self.config_store = AnalysisConfigStore()
        self.analysis_sidebar = AnalysisResultsSidebar(self.config_store)
        self.analysis_type_selector = self.analysis_sidebar.type_selector
        self.model_inspector = self.analysis_sidebar.inspector
        self.setup_workspace = SetupWorkspace(self.config_store, run_analysis_service)
        self.analysis_settings = self.setup_workspace.settings_panel
        self.results_workspace = ResultsWorkspace()
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

        self.model_page_header = PageHeader(
            title="MODEL WORKSPACE",
            subtitle="Import, inspect, and prepare the structural model before analysis.",
            action_text="Proceed to Setup  →",
        )
        # Keep MODEL's context header compact so the structural viewport and
        # side panels receive the recovered vertical workspace. SETUP retains
        # the roomier shared PageHeader spacing.
        self.model_page_header.layout().setContentsMargins(24, 7, 24, 7)
        self.model_page_header.action_requested.connect(self._open_setup_workspace)
        self.model_page_header.set_status("Model Status:  ● READY", "ready")
        self.model_workspace_page = QFrame()
        self.model_workspace_page.setObjectName("modelWorkspacePage")
        model_page_layout = QVBoxLayout(self.model_workspace_page)
        model_page_layout.setContentsMargins(0, 0, 0, 0)
        model_page_layout.setSpacing(0)
        model_page_layout.addWidget(self.model_page_header)
        model_page_layout.addWidget(self.workspace, 1)

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.setObjectName("workspaceStack")
        self.workspace_stack.addWidget(self.start_workspace)
        self.workspace_stack.addWidget(self.template_gallery_page)
        self.workspace_stack.addWidget(self.direct_model_workspace)
        self.workspace_stack.addWidget(self.model_workspace_page)
        self.workspace_stack.addWidget(self.setup_workspace)
        self.workspace_stack.addWidget(self.results_workspace)
        self.workspace_stack.setCurrentWidget(self.start_workspace)

        self._build_menu_bar()
        # AppHeader (brand/status/upload/run) rides the native menu bar's own row
        # as a corner widget instead of stacking as its own separate row below it -
        # File/Edit/View/Window/Help and the brand/actions cluster end up on one
        # physical row, the same way the Stitch mockup packs them, without
        # changing anything about AppHeader itself (same widgets, same attribute
        # names every existing test already reaches through window.header.*).
        self.menuBar().setCornerWidget(self.header.brand_panel, Qt.Corner.TopLeftCorner)
        self.menuBar().setCornerWidget(self.header, Qt.Corner.TopRightCorner)
        self.navigation.append_trailing_widget(self.header.upload_button)
        root_layout.addWidget(self.navigation)
        root_layout.addWidget(self.workspace_stack, 1)
        self.setCentralWidget(root)

        self._build_status_bar()
        self._connect_actions()
        self._show_start_workspace()

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        status.setObjectName("applicationStatusBar")
        status.setProperty("mode", "home")
        status.showMessage(f"OpenFrame Studio v{_APP_VERSION}  |  Ready  |  No project loaded")
        self.setStatusBar(status)

    def _set_status_mode(self, mode: str) -> None:
        status = self.statusBar()
        status.setProperty("mode", mode)
        status.style().unpolish(status)
        status.style().polish(status)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        upload_action = QAction("Upload .py…", self)
        upload_action.triggered.connect(self._choose_model_file)
        file_menu.addAction(upload_action)
        save_action = QAction("Save Project", self)
        save_action.triggered.connect(lambda: self._show_pending_workflow("Save Project"))
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = menu_bar.addMenu("Edit")
        edit_menu.addAction(self._pending_action("Undo", "Undo"))
        edit_menu.addAction(self._pending_action("Redo", "Redo"))

        view_menu = menu_bar.addMenu("View")
        for key, text in (
            ("model", "MODEL"),
            ("setup", "SETUP"),
            ("results", "RESULTS"),
            ("viewport", "VIEWPORT"),
        ):
            action = QAction(text.title(), self)
            action.triggered.connect(
                lambda checked=False, section=key: self.navigation.set_current_section(
                    section, emit=True
                )
            )
            view_menu.addAction(action)

        window_menu = menu_bar.addMenu("Window")
        window_menu.addAction(self._pending_action("Reset Layout", "Reset Layout"))

        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About OpenFrame Studio", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _pending_action(self, text: str, workflow: str) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(lambda: self._show_pending_workflow(workflow))
        return action

    def _show_about_dialog(self) -> None:
        QMessageBox.information(
            self,
            "About OpenFrame Studio",
            "OpenFrame Studio\nOpenSeesPy 2D/3D structural model visualization and analysis.",
        )

    def _connect_actions(self) -> None:
        self.header.upload_requested.connect(self._choose_model_file)
        self.header.direct_open_requested.connect(self.direct_model_workspace._open_project)
        self.header.run_requested.connect(self._run_analysis)
        self.header.home_requested.connect(self._show_start_workspace)
        self.header.save_requested.connect(self._save_project_from_header)
        self.header.settings_requested.connect(lambda: self._show_pending_workflow("Settings"))
        self.header.help_requested.connect(self._show_about_dialog)
        self.header.profile_requested.connect(lambda: self._show_pending_workflow("Account"))
        self.setup_workspace.back_to_model_requested.connect(self._show_model_workspace)
        self.start_workspace.import_opensees_requested.connect(self._start_import_workspace)
        self.start_workspace.new_model_requested.connect(self._start_new_model_workspace)
        self.start_workspace.new_3d_model_requested.connect(self._start_new_3d_model_workspace)
        self.direct_model_workspace.back_requested.connect(self._show_start_workspace)
        self.direct_model_workspace.analysis_script_exported.connect(
            self._open_exported_analysis_script
        )
        self.direct_model_workspace.project_opening.connect(
            self._snapshot_current_direct_session
        )
        self.direct_model_workspace.project_opened.connect(
            self._direct_project_opened
        )
        self.direct_model_workspace.project_saved.connect(
            self._direct_project_saved
        )
        self.start_workspace.template_requested.connect(self._show_template_gallery)
        self.template_gallery_page.back_requested.connect(self._show_start_workspace)
        self.template_gallery_page.template_opened.connect(self._open_template)
        self.start_workspace.open_project_requested.connect(self._open_project_from_start)
        self.start_workspace.resume_workspace_requested.connect(self._resume_workspace)
        self.start_workspace.session_requested.connect(self._activate_workspace_session)
        self.navigation.current_changed.connect(self._change_workspace_section)
        self.config_store.kind_changed.connect(self._set_analysis_kind)
        self.analysis_type_selector.open_setup_requested.connect(self._open_setup_workspace)
        self.setup_workspace.run_requested.connect(self._run_analysis)
        self.viewport.unit_system_changed.connect(self._set_unit_system)
        self.viewport.entity_selected.connect(self._entity_selected_from_viewport)
        self.model_sidebar.entity_selected.connect(self._entity_selected_from_tree)
        self.analysis_progress.cancel_requested.connect(self._cancel_analysis)

    def _set_unit_system(self, unit_system: UnitSystem) -> None:
        self._apply_unit_system(unit_system)
        if self._current_session_key in self._workspace_sessions:
            session = self._workspace_sessions[self._current_session_key]
            session.unit_system = unit_system
            session.model.metadata.update(
                {
                    "unit_force": unit_system.force,
                    "unit_length": unit_system.length,
                    "unit_time": unit_system.time,
                }
            )
            self._imported_unit_store.save(session.source_path, unit_system)
        self.statusBar().showMessage(f"Model units changed | {unit_system.label}")

    def _apply_unit_system(self, unit_system: UnitSystem) -> None:
        self.viewport.set_unit_system(unit_system, emit=False)
        self.model_inspector.set_unit_system(unit_system)
        self.analysis_settings.set_unit_system(unit_system)
        self.results_workspace.set_unit_system(unit_system)

    def _resolve_undeclared_imported_units(self, source: Path) -> UnitSystem | None:
        saved = self._imported_unit_store.load(source)
        if saved is not None:
            return saved
        selected = ImportedModelUnitDialog.choose(source, self)
        if selected is not None:
            self._imported_unit_store.save(source, selected)
        return selected

    def _show_start_workspace(self) -> None:
        if self.workspace_stack.currentWidget() is self.direct_model_workspace:
            self._snapshot_current_direct_session()
        if self.workspace_stack.currentWidget() is not self.start_workspace:
            self._resume_section = self.navigation.current_section()
            self._store_current_session_section(self._resume_section)
        self._refresh_start_sessions()
        self.workspace_stack.setCurrentWidget(self.start_workspace)
        self.header.show()
        self.navigation.set_home_mode(True)
        self.navigation.hide()
        self.header.set_welcome_mode(True)
        self._set_status_mode("home")
        self.statusBar().showMessage(f"OpenFrame Studio v{_APP_VERSION}  |  Ready  |  No project loaded")

    def _show_template_gallery(self) -> None:
        """"Templates" on the home screen - a full-page gallery, not a modal,
        so a card's live preview/description/tags have real room instead of
        being squeezed into a popup. Reuses home's own chrome mode (header
        shown, nav hidden) since this is still part of the "start a project"
        flow, just one page deeper than the hub itself."""
        self.workspace_stack.setCurrentWidget(self.template_gallery_page)
        self.header.show()
        self.navigation.set_home_mode(True)
        self.navigation.hide()
        self.header.set_welcome_mode(True)
        self._set_status_mode("home")
        self.statusBar().showMessage("Templates | 완성된 예제 모델을 골라 바로 시작하세요")

    def _open_template(self, data: dict, entry: TemplateEntry) -> None:
        """A plain template is nothing but a bundled ``.ofsm`` project -
        opening one lands on ``direct_model_workspace`` exactly the way
        opening a user's own saved project does (``open_project_dict`` is
        the same core ``open_project_file`` uses), it just skips the file
        dialog and starts a fresh (unsaved) session instead of one tied to a
        path the user never chose. A template whose manifest names an
        ``analysis_kind`` needs a solver the canvas itself cannot run (e.g.
        Elastic Buckling) and takes a different path entirely - see
        ``_open_precision_template``."""
        if entry.analysis_kind:
            self._open_precision_template(data, entry)
            return
        self._snapshot_current_direct_session()
        self.direct_model_workspace.open_project_dict(data)
        self._begin_direct_session(int(data.get("ndm", 2)))
        self.navigation.hide()
        self.header.show()
        self.header.set_welcome_mode(False)
        self.header.set_direct_model_mode(True)
        self.workspace_stack.setCurrentWidget(self.direct_model_workspace)
        self._refresh_start_sessions()
        self.statusBar().showMessage(
            f"템플릿 · {entry.title}" + (f"  |  {entry.hint}" if entry.hint else "")
        )

    def _open_precision_template(self, data: dict, entry: TemplateEntry) -> None:
        """Exports the template's canvas geometry to an OpenSeesPy script
        exactly like the canvas's own "정밀해석으로 내보내기" button would,
        then opens it through the normal OpenSeesPy import pipeline
        (``_open_exported_analysis_script``) so SETUP's model-dependent
        widgets (load pattern lists, etc.) populate for real instead of
        being guessed at. ``_pending_analysis_preset`` carries the
        template's analysis kind/options across the load thread's async
        completion - see ``_model_loaded``, the only place it is consumed."""
        canvas = StaticsDrawingCanvas()
        canvas.load_dict(data)
        model = canvas.build_model()
        unit_length = str(data.get("unit_length", "m"))
        unit_force = str(data.get("unit_force", "kN"))
        kind = AnalysisKind(entry.analysis_kind)
        # Buckling only needs stiffness (mass would be dead weight to the
        # eigenvalue solve); Time History needs real nodal mass (from each
        # element's own density*A) or run_time_history_analysis rejects the
        # model outright with "절점 질량이 정의되어 있지 않습니다" - see
        # time_history_solver.py's own total_mass check.
        include_mass = kind == AnalysisKind.TIME_HISTORY
        script = export_opensees_script(model, include_mass=include_mass, length_unit=unit_length)
        # export_opensees_script (shared with the canvas's own "정밀해석으로
        # 내보내기" button) never embeds OPENFRAME_UNITS - a hand-drawn
        # model's own length_unit isn't necessarily trustworthy enough to
        # skip that confirmation, so the importer falls back to an
        # interactive "pick your units" dialog. A template already carries
        # real, author-verified units in its own .ofsm (unit_force/
        # unit_length above), so prepending the declaration here lets this
        # one path skip that dialog - exactly the point of a "settings
        # already applied" template for a first-time user; the shared
        # export function itself is left untouched.
        script = (
            f'OPENFRAME_UNITS = {{"force": {unit_force!r}, "length": {unit_length!r}, '
            f'"time": "s"}}\n' + script
        )
        scratch_dir = Path(tempfile.gettempdir()) / "openframe_studio_templates"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        script_path = scratch_dir / f"{entry.id}.py"
        script_path.write_text(script, encoding="utf-8")
        self._pending_analysis_preset = (kind, dict(entry.analysis_options), entry.hint)
        self._open_exported_analysis_script(script_path)

    def _show_pending_workflow(self, workflow: str) -> None:
        self.statusBar().showMessage(f"{workflow} interface is ready for feature connection")

    def _start_import_workspace(self) -> None:
        self._has_active_workspace = True
        self._current_direct_session_key = None
        if self._workspace_sessions:
            self._refresh_start_sessions()
        else:
            self.start_workspace.set_current_session(
                "OpenSeesPy Import", "Waiting for a .py source file"
            )
        self._show_model_workspace()
        self.statusBar().showMessage(
            "OpenSeesPy import workspace | Select UPLOAD .PY to choose a model"
        )

    def _start_new_model_workspace(self) -> None:
        """2D structural-mechanics problems are usually determinate textbook
        statics that need no material or section input — jump straight to
        the 2D canvas instead of the setup wizard."""
        self._current_model_source = None
        self.navigation.hide()
        self.header.show()
        self.header.set_direct_model_mode(True)
        self.direct_model_workspace.start_2d_model()
        self._begin_direct_session(2)
        self.workspace_stack.setCurrentWidget(self.direct_model_workspace)
        self.statusBar().showMessage("New 2D Model · 2D 캔버스에서 바로 시작합니다")

    def _start_new_3d_model_workspace(self) -> None:
        """Open a new model directly in its dedicated 3D authoring canvas."""
        self._current_model_source = None
        self.navigation.hide()
        self.header.show()
        self.header.set_direct_model_mode(True)
        self.direct_model_workspace.start_3d_model()
        self._begin_direct_session(3)
        self.workspace_stack.setCurrentWidget(self.direct_model_workspace)
        self.statusBar().showMessage(
            "New 3D Model · 3D 캔버스에서 바로 시작합니다"
        )

    def _open_project_from_start(self) -> None:
        """"Open Project" on the home screen — the only "이전 작업 불러오기"
        entry point used to be the OpenSeesPy import history list, which only
        ever remembers a .py source path, so a hand-drawn 2D/3D project saved
        via the canvas's own 저장 button had nowhere to be reopened from on
        this screen. This card already existed for exactly this (its own
        description always said "Continue a saved OpenFrame project") but was
        left connected to a placeholder message until now.
        """
        path_str, _ = QFileDialog.getOpenFileName(
            self, "프로젝트 열기", "", "OpenFrame 프로젝트 (*.ofsm);;모든 파일 (*.*)"
        )
        if not path_str:
            return
        try:
            self._snapshot_current_direct_session()
            self.direct_model_workspace.open_project_file(Path(path_str))
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.critical(self, "프로젝트 열기", f"프로젝트를 열지 못했습니다: {error}")
            return
        self.statusBar().showMessage(f"프로젝트 열기 · {Path(path_str).name}")

    def _save_project_from_header(self) -> None:
        if self.workspace_stack.currentWidget() is self.direct_model_workspace:
            self.direct_model_workspace._save_project()
            return
        self._show_pending_workflow("Save Project")

    def _show_model_workspace(self) -> None:
        self._resume_section = "model"
        self.navigation.set_home_mode(False)
        self.navigation.set_current_section("model")
        self.navigation.show()
        self.header.show()
        self.header.set_welcome_mode(False)
        self.workspace_stack.setCurrentWidget(self.model_workspace_page)
        self._set_status_mode("model")

    def _resume_workspace(self) -> None:
        if not self._has_active_workspace:
            return
        self.navigation.show()
        self.header.show()
        self.header.set_welcome_mode(False)
        self.navigation.set_current_section(self._resume_section)
        self._change_workspace_section(self._resume_section)

    def _open_results_workspace(self) -> None:
        self.analysis_progress.hide()
        self.navigation.set_home_mode(False)
        self.navigation.show()
        self.header.show()
        self.header.set_welcome_mode(False)
        self.navigation.set_current_section("results", emit=True)

    def _open_setup_workspace(self) -> None:
        self.navigation.set_home_mode(False)
        self.navigation.show()
        self.header.show()
        self.header.set_welcome_mode(False)
        self.navigation.set_current_section("setup", emit=True)
        self._set_status_mode("setup")

    def _open_exported_analysis_script(self, path: Path) -> None:
        """A canvas model just exported itself as an OpenSeesPy script - open it
        exactly like a hand-picked file would be, through the same "OpenSeesPy
        파일 불러오기" pipeline the canvas's own solvers cannot reach (nonlinear
        static, time history). This is the only place the two otherwise-
        independent authoring paths (canvas vs. file import) ever meet."""
        self._has_active_workspace = True
        self._show_model_workspace()
        self.model_sidebar.set_source_file(str(path))
        self._start_model_load(path)

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
        source_path = Path(source).resolve()
        if not isinstance(model, StructuralModel):
            self._model_load_failed("불러온 모델 형식이 StructuralModel이 아닙니다.")
            return
        unit_system = unit_system_from_metadata(model.metadata)
        if unit_system is None:
            unit_system = self._imported_unit_resolver(source_path)
            if unit_system is None:
                self.statusBar().showMessage(
                    "Model import cancelled · Native units are required"
                )
                return
            model.metadata["unit_source"] = "user-selection"
        model.metadata.update(
            {
                "unit_force": unit_system.force,
                "unit_length": unit_system.length,
                "unit_time": unit_system.time,
            }
        )
        self._has_active_workspace = True
        self._current_model_source = source_path
        self._apply_unit_system(unit_system)
        self.model_sidebar.set_source_file(source)
        self.model_sidebar.set_model(model)
        self.viewport.set_model(model)
        self.model_inspector.set_model(model)
        self.setup_workspace.set_model(model)
        self.setup_workspace.set_source_path(source_path)
        self.results_workspace.set_model(model)
        self.results_workspace.clear_result()
        self.navigation.set_breadcrumb(source_path.stem)
        self.navigation.set_breadcrumb_status("READY")
        key = str(source_path)
        self._remember_session(
            _WorkspaceSession(
                key=key,
                title=source_path.name,
                source_path=source_path,
                model=model,
                unit_system=unit_system,
            )
        )
        self._current_session_key = key
        self._current_direct_session_key = None
        self._refresh_start_sessions()

        pending_preset = self._pending_analysis_preset
        self._pending_analysis_preset = None
        if pending_preset is not None:
            kind, options, hint = pending_preset
            if kind == AnalysisKind.BUCKLING:
                self.analysis_settings.apply_buckling_preset(options)
            elif kind == AnalysisKind.TIME_HISTORY:
                self.analysis_settings.apply_time_history_preset(options)
            self._open_setup_workspace()
            self.statusBar().showMessage(
                f"템플릿 · {kind.value} 설정이 이미 적용되었습니다"
                + (f"  |  {hint}" if hint else "")
            )
            return

        self._show_model_workspace()
        self.statusBar().showMessage(
            f"Model loaded · Nodes {len(model.nodes)} · Elements {len(model.elements)} · "
            f"Units {unit_system.label}"
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
        self.navigation.set_home_mode(False)
        if section != "results":
            # Leaving RESULTS entirely must stop the Time History animation
            # timer too, not just switching between result types inside it.
            self.results_workspace.time_history_results_panel.animation_panel.pause_animation()
        labels = {
            "model": "Model workspace",
            "setup": "Analysis setup",
            "results": "Analysis results",
            "viewport": "Viewport focus",
        }
        if section == "results":
            self.workspace_stack.setCurrentWidget(self.results_workspace)
            self._set_status_mode("setup")
            self.statusBar().showMessage("Results workspace | Ready")
            return
        if section == "setup":
            self.workspace_stack.setCurrentWidget(self.setup_workspace)
            self._set_status_mode("setup")
            self.statusBar().showMessage("Analysis setup | Ready")
            return

        self.workspace_stack.setCurrentWidget(self.model_workspace_page)
        focus_viewport = section == "viewport"
        self.model_sidebar.setVisible(not focus_viewport)
        self.analysis_sidebar.setVisible(not focus_viewport)
        self.model_page_header.setVisible(not focus_viewport)
        self._set_status_mode("model")
        self.statusBar().showMessage(f"{labels[section]} · Ready")

    def _set_analysis_kind(self, kind: AnalysisKind) -> None:
        names = {
            AnalysisKind.LINEAR_STATIC: "Linear Static",
            AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
            AnalysisKind.MODAL: "Modal (Eigenvalue)",
            AnalysisKind.TIME_HISTORY: "Time History",
            AnalysisKind.BUCKLING: "Elastic Buckling",
            AnalysisKind.RESPONSE_SPECTRUM: "Response Spectrum",
        }
        self.results_workspace.set_analysis_kind(kind)
        self.statusBar().showMessage(f"Analysis type · {names[kind]}")

    def _run_analysis(self) -> None:
        kind = self.config_store.kind
        self._set_analysis_kind(kind)

        if self._run_analysis_service is None:
            QMessageBox.critical(self, "해석 실행", "해석 실행 서비스가 없습니다.")
            return
        if self._current_model_source is None:
            QMessageBox.warning(self, "해석 실행", "먼저 모델 파일을 불러오세요.")
            return
        if self._analysis_run_thread and self._analysis_run_thread.isRunning():
            return

        request = self.config_store.to_request(self._current_model_source)
        run_generation = self._model_generation
        run_session_key = self._current_session_key

        # The previous run's numbers must not linger next to a fresh one.
        self.results_workspace.clear_result()
        analysis_name = {
            AnalysisKind.LINEAR_STATIC: "Linear Static",
            AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
            AnalysisKind.MODAL: "Modal (Eigenvalue)",
            AnalysisKind.TIME_HISTORY: "Time History",
            AnalysisKind.BUCKLING: "Elastic Buckling",
            AnalysisKind.RESPONSE_SPECTRUM: "Response Spectrum",
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
        thread.progress_changed.connect(self.analysis_progress.set_progress)
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
            if result.mode_shapes:
                summary_line = f"Results are ready for {len(result.mode_shapes)} modes."
                detail_line = f"모드 결과: {len(result.mode_shapes)}개\n\n"
            elif result.buckling_modes:
                summary_line = f"Results are ready for {len(result.buckling_modes)} buckling modes."
                detail_line = f"좌굴모드 결과: {len(result.buckling_modes)}개\n\n"
            elif result.time_history:
                summary_line = f"Results are ready for {len(result.time_history)} time steps."
                detail_line = f"시간이력 스텝 결과: {len(result.time_history)}개\n\n"
            else:
                summary_line = (
                    f"Results are ready for {len(result.node_results)} nodes and "
                    f"{len(result.element_results)} elements."
                )
                detail_line = (
                    f"절점 결과: {len(result.node_results)}개\n"
                    f"부재 결과: {len(result.element_results)}개\n\n"
                )
            self.analysis_progress.show_completed(summary_line)
            self.statusBar().showMessage(f"Analysis completed · {summary_line}")
            QMessageBox.information(
                self,
                "해석 완료",
                "해석이 완료되었습니다.\n\n" + detail_line + "RESULTS 탭에서 결과를 확인할 수 있습니다.",
            )
        elif result.status == AnalysisStatus.PARTIAL and result.buckling_modes:
            # Buckling's own PARTIAL meaning ("fewer valid modes than requested",
            # see buckling_solver.py) - distinct from the nonlinear pushover
            # convergence.completed_steps/requested_steps wording below, which
            # would be misleading here since buckling has no NonlinearConvergence.
            detail = "\n".join(result.messages) or "요청한 모드 수보다 적은 유효 모드를 찾았습니다."
            summary = f"{len(result.buckling_modes)} valid buckling mode(s) found"
            self.analysis_progress.show_failed(f"Partial result: {summary}")
            self.statusBar().showMessage(f"Analysis partially completed | {summary}")
            QMessageBox.warning(
                self,
                "좌굴해석 부분 결과",
                f"요청한 모드 수보다 적은 유효 모드를 찾았습니다.\n\n{detail}\n\n"
                "찾은 모드까지의 결과는 RESULTS 탭에서 확인할 수 있습니다.",
            )
        elif result.status == AnalysisStatus.PARTIAL:
            convergence = result.convergence
            progress = (
                f"{convergence.completed_steps}/{convergence.requested_steps} steps converged"
                if convergence is not None
                else "The nonlinear curve is truncated at the last converged step"
            )
            detail = "\n".join(result.messages) or progress
            self.analysis_progress.show_failed(f"Partial convergence: {progress}")
            self.statusBar().showMessage(f"Analysis partially converged | {progress}")
            QMessageBox.warning(
                self,
                "비선형해석 부분 수렴",
                f"해석이 마지막 목표 스텝까지 수렴하지 않았습니다.\n\n{progress}\n\n{detail}\n\n"
                "마지막 수렴 스텝까지의 결과는 RESULTS 탭에서 확인할 수 있습니다.",
            )
        elif result.status == AnalysisStatus.CANCELLED:
            self.analysis_progress.show_failed("Analysis cancelled")
            self.statusBar().showMessage("Analysis cancelled")
            QMessageBox.warning(
                self,
                "해석 취소",
                "사용자 요청으로 해석을 취소했습니다.",
            )
        else:
            self.analysis_progress.show_failed(
                " ".join(result.messages) or "The solver returned an unknown error."
            )
            self.statusBar().showMessage("Analysis failed")
            QMessageBox.critical(
                self, "해석 실행 실패", "\n".join(result.messages) or "알 수 없는 해석 오류"
            )

    def _cancel_analysis(self) -> None:
        thread = self._analysis_run_thread
        if thread is None or not thread.isRunning():
            return
        self.analysis_progress.show_cancelling()
        thread.request_cancel()

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
        self._touch_recent_session(session.key)

    def _touch_recent_session(self, key: str) -> None:
        if key in self._recent_session_keys:
            self._recent_session_keys.remove(key)
        self._recent_session_keys.append(key)
        while len(self._recent_session_keys) > 4:
            oldest_key = self._recent_session_keys.pop(0)
            self._workspace_sessions.pop(oldest_key, None)
            self._direct_workspace_sessions.pop(oldest_key, None)

    def _begin_direct_session(self, ndm: int) -> None:
        """Register a blank hand-drawn model as a resumable recent project."""
        self._direct_session_sequence += 1
        key = f"direct:{self._direct_session_sequence}"
        session = _DirectWorkspaceSession(
            key=key,
            title=f"Untitled {ndm}D Model",
            ndm=ndm,
            project_data=self.direct_model_workspace.snapshot_project(),
            step=self.direct_model_workspace.current_session_step(),
        )
        self._direct_workspace_sessions[key] = session
        self._touch_recent_session(key)
        self._current_direct_session_key = key
        self._current_session_key = None
        self._current_model_source = None
        self._has_active_workspace = True

    def _snapshot_current_direct_session(self) -> None:
        key = self._current_direct_session_key
        session = self._direct_workspace_sessions.get(key or "")
        if session is None:
            return
        session.project_data = self.direct_model_workspace.snapshot_project()
        session.ndm = int(session.project_data.get("ndm", session.ndm))
        session.step = self.direct_model_workspace.current_session_step()
        self._touch_recent_session(session.key)

    def _direct_project_opened(self, path: Path) -> None:
        """Create/update a recent entry after an .ofsm project is opened."""
        resolved = path.resolve()
        key = f"direct-file:{resolved}"
        session = _DirectWorkspaceSession(
            key=key,
            title=resolved.name,
            ndm=int(self.direct_model_workspace.snapshot_project().get("ndm", 2)),
            project_data=self.direct_model_workspace.snapshot_project(),
            step=self.direct_model_workspace.current_session_step(),
            source_path=resolved,
        )
        self._direct_workspace_sessions[key] = session
        self._touch_recent_session(key)
        self._current_direct_session_key = key
        self._current_session_key = None
        self._current_model_source = None
        self._has_active_workspace = True
        self.navigation.hide()
        self.header.show()
        self.header.set_welcome_mode(False)
        self.header.set_direct_model_mode(True)
        self.workspace_stack.setCurrentWidget(self.direct_model_workspace)
        self._refresh_start_sessions()

    def _direct_project_saved(self, path: Path) -> None:
        resolved = path.resolve()
        key = self._current_direct_session_key
        session = self._direct_workspace_sessions.get(key or "")
        if session is None:
            self._direct_project_opened(resolved)
            return
        old_key = session.key
        new_key = f"direct-file:{resolved}"
        session.key = new_key
        session.title = resolved.name
        session.source_path = resolved
        session.project_data = self.direct_model_workspace.snapshot_project()
        session.step = self.direct_model_workspace.current_session_step()
        if old_key != new_key:
            self._direct_workspace_sessions.pop(old_key, None)
            if old_key in self._recent_session_keys:
                self._recent_session_keys.remove(old_key)
        self._direct_workspace_sessions[new_key] = session
        self._current_direct_session_key = new_key
        self._touch_recent_session(new_key)
        self._refresh_start_sessions()

    def _store_current_session_section(self, section: str) -> None:
        if self._current_session_key in self._workspace_sessions:
            self._workspace_sessions[self._current_session_key].section = section

    def _refresh_start_sessions(self) -> None:
        sessions: list[tuple[str, str, str]] = []
        for key in reversed(self._recent_session_keys):
            imported = self._workspace_sessions.get(key)
            if imported is not None:
                sessions.append(
                    (
                        imported.key,
                        imported.title,
                        f"{imported.title} · OpenSeesPy · {imported.source_path.parent}",
                    )
                )
                continue
            direct = self._direct_workspace_sessions.get(key)
            if direct is not None:
                nodes = len(direct.project_data.get("nodes", []))
                elements = len(direct.project_data.get("elements", []))
                source = str(direct.source_path.parent) if direct.source_path else "Unsaved project"
                sessions.append(
                    (
                        direct.key,
                        direct.title,
                        f"{direct.ndm}D Model · Nodes {nodes} · Members {elements} · {source}",
                    )
                )
        if sessions:
            active_key = self._current_direct_session_key or self._current_session_key
            self.start_workspace.set_sessions(sessions, active_key)

    def _activate_workspace_session(self, key: str) -> None:
        direct = self._direct_workspace_sessions.get(key)
        if direct is not None:
            self._activate_direct_workspace_session(direct)
            return
        session = self._workspace_sessions.get(key)
        if session is None:
            return

        self._store_current_session_section(self.navigation.current_section())
        self._workspace_sessions.pop(key)
        self._workspace_sessions[key] = session
        self._current_session_key = key
        self._current_direct_session_key = None
        self._current_model_source = session.source_path
        self._has_active_workspace = True

        self._apply_unit_system(session.unit_system)
        self.model_sidebar.set_source_file(str(session.source_path))
        self.model_sidebar.set_model(session.model)
        self.viewport.set_model(session.model)
        self.model_inspector.set_model(session.model)
        self.setup_workspace.set_model(session.model)
        self.setup_workspace.set_source_path(session.source_path)
        self.results_workspace.set_model(session.model)
        self.results_workspace.clear_result()
        self.navigation.set_breadcrumb(session.source_path.stem)
        self.navigation.set_breadcrumb_status("READY")
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

    def _activate_direct_workspace_session(self, session: _DirectWorkspaceSession) -> None:
        self._direct_workspace_sessions.pop(session.key, None)
        self._direct_workspace_sessions[session.key] = session
        self._touch_recent_session(session.key)
        self._current_direct_session_key = session.key
        self._current_session_key = None
        self._current_model_source = None
        self._has_active_workspace = True
        self.direct_model_workspace.restore_project(
            session.project_data, step=session.step
        )
        self.navigation.hide()
        self.header.show()
        self.header.set_welcome_mode(False)
        self.header.set_direct_model_mode(True)
        self.workspace_stack.setCurrentWidget(self.direct_model_workspace)
        self._refresh_start_sessions()
        self.statusBar().showMessage(f"Workspace restored | {session.title}")
