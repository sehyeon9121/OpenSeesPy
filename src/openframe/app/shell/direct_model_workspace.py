"""Independent workspace for models authored inside OpenFrame."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
from openframe.features.model.presentation.statics_problem_page import StaticsProblemPage


class DirectModelWorkspace(QFrame):
    """Owns the new-model workflow without sharing the OpenSeesPy import UI."""

    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("directModelWorkspace")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        command_bar = QFrame()
        command_bar.setObjectName("directModelCommandBar")
        command_layout = QHBoxLayout(command_bar)
        command_layout.setContentsMargins(12, 7, 12, 7)
        brand = QLabel("OpenFrame Studio")
        brand.setObjectName("directModelBrand")
        command_layout.addWidget(brand)
        self.back_button = QPushButton("Home")
        self.back_button.setObjectName("directModelBackButton")
        self.back_button.clicked.connect(self.back_requested)
        command_layout.addWidget(self.back_button)
        command_layout.addStretch(1)
        self.save_button = QPushButton("저장")
        self.save_button.setObjectName("directModelSaveButton")
        self.save_button.setToolTip("프로젝트 저장 기능 연결 예정")
        self.save_button.setDisabled(True)
        command_layout.addWidget(self.save_button)
        root.addWidget(command_bar)

        self.workflow = ModelingWorkflowBar()

        self.setup_page = ModelSetupPage()
        self.materials_page = MaterialSettingsPage()
        self.sections_page = WorkflowPlaceholderPage(
            "단면 라이브러리",
            "단면 형상과 재료를 조합하고 구조 요소에 사용할 단면을 관리하는 영역입니다.",
        )
        self.geometry_page = StaticsProblemPage()
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
            self.supports_page,
        ):
            self.stage_stack.addWidget(page)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.workflow)
        body.addWidget(self.stage_stack, 1)
        root.addLayout(body, 1)

        self._pages = {
            "setup": self.setup_page,
            "materials": self.materials_page,
            "sections": self.sections_page,
            "geometry": self.geometry_page,
            "supports": self.supports_page,
        }
        self.workflow.step_selected.connect(self.set_current_step)
        self.setup_page.continue_requested.connect(self._continue_from_setup)
        self.setup_page.unit_system_changed.connect(self.materials_page.set_unit_system)
        self.setup_page.unit_system_changed.connect(self.geometry_page.set_unit_system)
        self.materials_page.continue_requested.connect(lambda: self.set_current_step("sections"))
        self.materials_page.set_unit_system(self.setup_page.unit_system())
        self.geometry_page.set_unit_system(self.setup_page.unit_system())
        self.set_current_step("setup")

    def set_current_step(self, step: str) -> None:
        self.workflow.set_current_step(step)
        self.stage_stack.setCurrentWidget(self._pages[step])

    def _continue_from_setup(self) -> None:
        """Skip stiffness inputs for determinate textbook statics problems."""
        next_step = "geometry" if self.setup_page.is_material_free_statics() else "materials"
        self.set_current_step(next_step)
