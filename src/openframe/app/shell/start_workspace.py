"""First-run project entry screen for OpenFrame Studio."""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class StartWorkspace(QFrame):
    """Presentation-only entry points for the future project workflows."""

    new_model_requested = Signal()
    template_requested = Signal()
    import_opensees_requested = Signal()
    open_project_requested = Signal()
    resume_workspace_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startWorkspace")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 28)
        outer.setSpacing(0)
        outer.addStretch(1)

        content = QFrame()
        content.setObjectName("startContent")
        content.setMaximumWidth(1080)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        layout.addWidget(self._build_hero())

        section_header = QHBoxLayout()
        section_title = QLabel("START A PROJECT")
        section_title.setObjectName("startSectionTitle")
        section_hint = QLabel("Choose how you want to begin")
        section_hint.setObjectName("startSectionHint")
        section_header.addWidget(section_title)
        section_header.addSpacing(8)
        section_header.addWidget(section_hint)
        section_header.addStretch(1)
        layout.addLayout(section_header)

        choices = QGridLayout()
        choices.setContentsMargins(0, 0, 0, 0)
        choices.setHorizontalSpacing(14)
        choices.setVerticalSpacing(14)
        self.new_model_button = self._add_choice_card(
            choices,
            row=0,
            column=0,
            icon="+",
            eyebrow="RECOMMENDED",
            title="New Model",
            description="Create an editable 2D structural project from a blank canvas.",
            action_text="START NEW MODEL",
            primary=True,
            callback=self.new_model_requested.emit,
            action_id="action_new_model",
        )
        self.template_button = self._add_choice_card(
            choices,
            row=0,
            column=1,
            icon="T",
            eyebrow="QUICK START",
            title="From Template",
            description="Begin with a beam, frame, truss or arch and customize it.",
            action_text="BROWSE TEMPLATES",
            primary=False,
            callback=self.template_requested.emit,
            action_id="action_browse_templates",
        )
        self.import_button = self._add_choice_card(
            choices,
            row=1,
            column=0,
            icon="PY",
            eyebrow="EXISTING WORKFLOW",
            title="Import OpenSeesPy",
            description="Open the MODEL workspace, then choose an OpenSeesPy source file.",
            action_text="START",
            primary=False,
            callback=self.import_opensees_requested.emit,
            action_id="action_import_openseespy",
        )
        self.open_project_button = self._add_choice_card(
            choices,
            row=1,
            column=1,
            icon="O",
            eyebrow="CONTINUE WORK",
            title="Open Project",
            description="Continue a saved OpenFrame project and its model settings.",
            action_text="OPEN PROJECT",
            primary=False,
            callback=self.open_project_requested.emit,
            action_id="action_open_project",
        )
        choices.setColumnStretch(0, 1)
        choices.setColumnStretch(1, 1)
        layout.addLayout(choices)

        layout.addWidget(self._build_footer_panel())

        outer.addWidget(content, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def _build_hero(self) -> QWidget:
        hero = QFrame()
        hero.setObjectName("startHero")
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(6)

        eyebrow = QLabel("OPENFRAME STUDIO  /  2D STRUCTURAL WORKSPACE")
        eyebrow.setObjectName("startHeroEyebrow")
        title = QLabel("Start with the structure, not the software")
        title.setObjectName("startHeroTitle")
        description = QLabel(
            "Build a new structural model with a visual workflow, or bring in an "
            "OpenSeesPy model you already trust."
        )
        description.setObjectName("startHeroDescription")
        description.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(description)
        return hero

    def _add_choice_card(
        self,
        grid: QGridLayout,
        *,
        row: int,
        column: int,
        icon: str,
        eyebrow: str,
        title: str,
        description: str,
        action_text: str,
        primary: bool,
        callback: Callable[[], None],
        action_id: str,
    ) -> QPushButton:
        card = QFrame()
        card.setObjectName("startPrimaryCard" if primary else "startOptionCard")
        card.setMinimumHeight(142)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(5)

        top = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setObjectName("startPrimaryIcon" if primary else "startOptionIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge = QLabel(eyebrow)
        badge.setObjectName("startPrimaryBadge" if primary else "startOptionBadge")
        top.addWidget(icon_label)
        top.addSpacing(7)
        top.addWidget(badge)
        top.addStretch(1)
        layout.addLayout(top)

        heading = QLabel(title)
        heading.setObjectName("startCardTitle")
        body = QLabel(description)
        body.setObjectName("startCardDescription")
        body.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addStretch(1)

        button = QPushButton(action_text)
        button.setObjectName("startPrimaryButton" if primary else "startSecondaryButton")
        button.setProperty("actionId", action_id)
        button.clicked.connect(callback)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(card, row, column)
        return button

    def _build_footer_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("startFooterPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 13, 18, 13)
        layout.setSpacing(16)

        recent = QVBoxLayout()
        self.session_title = QLabel("RECENT PROJECTS")
        self.session_title.setObjectName("startFooterTitle")
        self.session_detail = QLabel("Saved OpenFrame projects will appear here.")
        self.session_detail.setObjectName("startFooterText")
        recent.addWidget(self.session_title)
        session_row = QHBoxLayout()
        session_row.addWidget(self.session_detail, 1)
        self.resume_button = QPushButton("RETURN TO MODEL")
        self.resume_button.setObjectName("startInlineButton")
        self.resume_button.setProperty("actionId", "action_resume_workspace")
        self.resume_button.clicked.connect(self.resume_workspace_requested)
        self.resume_button.hide()
        session_row.addWidget(self.resume_button)
        recent.addLayout(session_row)
        layout.addLayout(recent, 1)

        divider = QFrame()
        divider.setObjectName("startFooterDivider")
        divider.setFrameShape(QFrame.Shape.VLine)
        layout.addWidget(divider)

        workflow = QVBoxLayout()
        workflow_title = QLabel("WORKFLOW")
        workflow_title.setObjectName("startFooterTitle")
        workflow_steps = QLabel("01  MODEL     02  ANALYSIS     03  RESULTS")
        workflow_steps.setObjectName("startWorkflowSteps")
        workflow.addWidget(workflow_title)
        workflow.addWidget(workflow_steps)
        layout.addLayout(workflow, 1)
        return panel

    def set_current_session(self, name: str | None, source: str = "") -> None:
        """Show a preserved workspace that can be resumed from Home."""
        if not name:
            self.session_title.setText("RECENT PROJECTS")
            self.session_detail.setText("Saved OpenFrame projects will appear here.")
            self.resume_button.hide()
            return

        self.session_title.setText("CURRENT SESSION")
        detail = f"{name}  ·  {source}" if source else name
        self.session_detail.setText(detail)
        self.resume_button.show()
