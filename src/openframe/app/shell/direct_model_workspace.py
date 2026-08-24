"""Independent workspace for models authored inside OpenFrame."""

import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from openframe.app.shell.modeling_workflow import ModelingWorkflowBar
from openframe.features.model.presentation.material_settings_page import MaterialSettingsPage
from openframe.features.model.presentation.model_setup_page import (
    ModelSetupPage,
    WorkflowPlaceholderPage,
)
from openframe.features.model.presentation.modeling_interface_page import ModelingInterfacePage


class DirectModelWorkspace(QFrame):
    """Owns the new-model workflow without sharing the OpenSeesPy import UI."""

    back_requested = Signal()
    #: Forwarded from whichever geometry page exported one - this workspace has
    #: no access to the "OpenSeesPy 파일 불러오기" pipeline itself (a different,
    #: sibling top-level workspace owns that), so the actual open happens
    #: further up, in MainWindow.
    analysis_script_exported = Signal(Path)
    project_opening = Signal()
    project_opened = Signal(Path)
    project_saved = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("directModelWorkspace")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.command_bar = QFrame()
        self.command_bar.setObjectName("directModelCommandBar")
        command_layout = QHBoxLayout(self.command_bar)
        command_layout.setContentsMargins(12, 4, 12, 4)
        command_layout.addStretch(1)
        self.workflow = ModelingWorkflowBar()
        command_layout.addWidget(self.workflow)
        command_layout.addStretch(1)
        root.addWidget(self.command_bar)

        self.setup_page = ModelSetupPage()
        self.materials_page = MaterialSettingsPage()
        self.sections_page = WorkflowPlaceholderPage(
            "단면 라이브러리",
            "단면 형상과 재료를 조합하고 구조 요소에 사용할 단면을 관리하는 영역입니다.",
        )
        self.geometry_page = ModelingInterfacePage(start_in_3d=False)
        # 2D and 3D are separate work areas with their own canvas — a 3D
        # session must never see geometry drawn in a 2D session (or vice
        # versa), so this is its own page/canvas instance, not a mode toggle
        # on the 2D one.
        self.geometry_page_3d = ModelingInterfacePage(start_in_3d=True)
        self.supports_page = WorkflowPlaceholderPage(
            "지점 및 구속조건",
            "작성한 구조 모델에 지점과 자유도 구속을 배치하는 영역입니다.",
        )
        self.stage_stack = QStackedWidget()
        self.stage_stack.setObjectName("directModelStageStack")
        for page in (
            self.setup_page,
            self.materials_page,
            self.sections_page,
            self.geometry_page,
            self.geometry_page_3d,
            self.supports_page,
        ):
            self.stage_stack.addWidget(page)
        root.addWidget(self.stage_stack, 1)

        self._pages = {
            "setup": self.setup_page,
            "materials": self.materials_page,
            "sections": self.sections_page,
            "geometry": self.geometry_page,
            "geometry_3d": self.geometry_page_3d,
            "supports": self.supports_page,
        }
        # Which page "geometry" actually means right now: the 2D canvas by
        # default, or the 3D canvas for the duration of a 3D wizard session
        # (see start_3d_model). The step bar only ever asks for "geometry" —
        # it has no separate 3D button — so this is where that gets resolved.
        self._wizard_geometry_target = "geometry"

        self.workflow.step_selected.connect(self.set_current_step)
        self.setup_page.continue_requested.connect(self._continue_from_setup)
        self.setup_page.unit_system_changed.connect(self.materials_page.set_unit_system)
        self.setup_page.unit_system_changed.connect(self.geometry_page.set_unit_system)
        self.materials_page.continue_requested.connect(lambda: self.set_current_step("sections"))
        self.materials_page.set_unit_system(self.setup_page.unit_system())
        self.geometry_page.set_unit_system(self.setup_page.unit_system())
        self.geometry_page_3d.set_unit_system(self.setup_page.unit_system())
        self.geometry_page.analysis_script_exported.connect(self.analysis_script_exported)
        self.geometry_page_3d.analysis_script_exported.connect(self.analysis_script_exported)
        self.set_current_step("geometry")

    def start_2d_model(self) -> None:
        """2D structural-mechanics problems (this app's primary 2D use case)
        are usually determinate textbook statics that need no material or
        section input at all — jump straight to the 2D canvas, skip the
        wizard entirely."""
        self.geometry_page.load_project_dict({"ndm": 2})
        self._wizard_geometry_target = "geometry"
        self.set_current_step("geometry")

    def start_3d_model(self) -> None:
        """Open the dedicated 3D canvas immediately with safe defaults.

        Global settings remain available from the canvas's Model tab, while
        materials, sections and loads are authored in its left task panel.
        This keeps new-model setup editable without making it a gate in front
        of the viewport.
        """
        self.geometry_page_3d.load_project_dict({"ndm": 3})
        self._wizard_geometry_target = "geometry_3d"
        self.setup_page.dimension.setCurrentIndex(1)
        self.set_current_step("geometry")

    def set_current_step(self, step: str) -> None:
        if step == "geometry":
            step = self._wizard_geometry_target
        # "geometry_3d" has no button of its own in the step bar — the bar's
        # single "구조 모델" tab always means "geometry", resolved above.
        if step != "geometry_3d":
            self.workflow.set_current_step(step)
        # Neither material-free 2D nor 3D authoring needs the setup/materials/
        # sections/supports steps once you're actually on the canvas - 2D's
        # material-free path already skips straight past materials/sections
        # (see _continue_from_setup), and the "supports" step has always been
        # an unimplemented placeholder (real support/load controls live in the
        # canvas page itself). Hiding the step bar here, instead of removing
        # steps that other flows may still reach, gives the canvas the full
        # window width without touching how those other steps are entered.
        show_workflow = step not in ("geometry", "geometry_3d")
        self.workflow.setVisible(show_workflow)
        self.command_bar.setVisible(show_workflow)
        self.stage_stack.setCurrentWidget(self._pages[step])

    def _continue_from_setup(self) -> None:
        """Skip stiffness inputs for determinate textbook statics problems."""
        next_step = "geometry" if self.setup_page.is_material_free_statics() else "materials"
        self.set_current_step(next_step)

    def _current_geometry_page(self) -> ModelingInterfacePage | None:
        current = self.stage_stack.currentWidget()
        return current if current in (self.geometry_page, self.geometry_page_3d) else None

    def current_session_step(self) -> str:
        """Return the resumable authoring step without exposing widget objects."""
        current = self.stage_stack.currentWidget()
        for step, page in self._pages.items():
            if page is current:
                return "geometry" if step == "geometry_3d" else step
        return "geometry"

    def snapshot_project(self) -> dict[str, object]:
        """Serialize the active 2D/3D authoring canvas for a recent session."""
        page = (
            self.geometry_page_3d
            if self._wizard_geometry_target == "geometry_3d"
            else self.geometry_page
        )
        return page.to_project_dict()

    def restore_project(self, data: dict[str, object], *, step: str = "geometry") -> None:
        """Restore an in-memory recent session and return to its last step."""
        is_3d = int(data.get("ndm", 2)) == 3
        target = self.geometry_page_3d if is_3d else self.geometry_page
        target.load_project_dict(data)
        self._wizard_geometry_target = "geometry_3d" if is_3d else "geometry"
        self.setup_page.dimension.setCurrentIndex(1 if is_3d else 0)
        self.set_current_step(step)

    def _save_project(self) -> None:
        page = self._current_geometry_page()
        if page is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "프로젝트 저장", "", "OpenFrame 프로젝트 (*.ofsm)"
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix != ".ofsm":
            path = path.with_suffix(".ofsm")
        try:
            page.save_to_file(path)
        except OSError as error:
            QMessageBox.critical(self, "프로젝트 저장", f"저장하지 못했습니다: {error}")
            return
        self.project_saved.emit(path.resolve())

    def open_project_dict(self, data: dict[str, object]) -> None:
        """Load an already-parsed project dict and land on its own (2D or
        3D) canvas — the shared core both ``open_project_file`` (a user's
        saved ``.ofsm``) and the Templates gallery (a bundled ``.ofsm`` read
        straight from package resources, no user file dialog involved) go
        through, so there is exactly one place that decides which canvas a
        project's own ``ndm`` routes to.

        A project's own ``ndm`` decides which of the two separate canvas
        instances receives it — never the one currently on screen — since a
        2D project must never end up mixed into a 3D session's geometry (or
        vice versa), the same separation ``start_2d_model``/``start_3d_model``
        already enforce.
        """
        is_3d = int(data.get("ndm", 2)) == 3
        target = self.geometry_page_3d if is_3d else self.geometry_page
        target.load_project_dict(data)
        self._wizard_geometry_target = "geometry_3d" if is_3d else "geometry"
        self.set_current_step("geometry")

    def open_project_file(self, path: Path) -> None:
        """Load a saved project and land on its own (2D or 3D) canvas."""
        data = json.loads(path.read_text(encoding="utf-8"))
        self.open_project_dict(data)
        self.project_opened.emit(path.resolve())

    def _open_project(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "프로젝트 열기", "", "OpenFrame 프로젝트 (*.ofsm);;모든 파일 (*.*)"
        )
        if not path_str:
            return
        self.project_opening.emit()
        try:
            self.open_project_file(Path(path_str))
        except (OSError, ValueError, KeyError, TypeError) as error:
            QMessageBox.critical(self, "프로젝트 열기", f"프로젝트를 열지 못했습니다: {error}")
