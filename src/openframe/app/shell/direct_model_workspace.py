"""Independent workspace for models authored inside OpenFrame."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from openframe.app.shell.modeling_workflow import ModelingWorkflowBar
from openframe.features.model.presentation.model_setup_page import (
    ModelSetupPage,
    WorkflowPlaceholderPage,
)


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
        self.back_button = QPushButton("←  홈")
        self.back_button.setObjectName("directModelBackButton")
        self.back_button.clicked.connect(self.back_requested)
        command_layout.addWidget(self.back_button)
        command_layout.addStretch(1)
        root.addWidget(command_bar)

        self.workflow = ModelingWorkflowBar()
        root.addWidget(self.workflow)

        self.setup_page = ModelSetupPage()
        self.materials_page = WorkflowPlaceholderPage(
            "재료 라이브러리",
            "OpenSees 재료 모델을 만들고 물성을 관리하는 영역입니다.",
        )
        self.sections_page = WorkflowPlaceholderPage(
            "단면 라이브러리",
            "단면 형상과 재료를 조합하고 구조 요소에 사용할 단면을 관리하는 영역입니다.",
        )
        self.geometry_page = WorkflowPlaceholderPage(
            "직접 모델링 캔버스",
            "절점과 구조 요소를 직접 작성하는 전용 캔버스가 배치될 영역입니다.",
        )
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
        root.addWidget(self.stage_stack, 1)

        self._pages = {
            "setup": self.setup_page,
            "materials": self.materials_page,
            "sections": self.sections_page,
            "geometry": self.geometry_page,
            "supports": self.supports_page,
        }
        self.workflow.step_selected.connect(self.set_current_step)
        self.setup_page.continue_requested.connect(lambda: self.set_current_step("materials"))
        self.set_current_step("setup")

    def set_current_step(self, step: str) -> None:
        self.workflow.set_current_step(step)
        self.stage_stack.setCurrentWidget(self._pages[step])
