"""Clear, large-format home screen for OpenFrame Studio."""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class StartWorkspace(QFrame):
    """Project entry points and the current-session summary."""

    new_model_requested = Signal()
    new_3d_model_requested = Signal()
    template_requested = Signal()
    import_opensees_requested = Signal()
    open_project_requested = Signal()
    resume_workspace_requested = Signal()
    session_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startWorkspace")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 26)
        outer.setSpacing(0)

        content = QFrame()
        content.setObjectName("startContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(22)

        title = QLabel("Start or continue a project")
        title.setObjectName("startPageTitle")
        description = QLabel(
            "Create a structural model, import OpenSeesPy, or continue your current work."
        )
        description.setObjectName("startPageDescription")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(22)
        body.addWidget(self._build_start_panel(), 5)
        body.addWidget(self._build_continue_panel(), 6)
        layout.addLayout(body)

        outer.addWidget(content, 1)

    def _build_start_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("startActionPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(11)

        title = QLabel("START NEW")
        title.setObjectName("startColumnTitle")
        hint = QLabel("Choose one way to begin")
        hint.setObjectName("startSectionHint")
        layout.addWidget(title)
        layout.addWidget(hint)

        self.new_model_button = self._add_action_card(
            layout,
            icon="+",
            title="New 2D Model",
            description="Create a structural frame from a blank canvas.",
            action_text="START",
            primary=True,
            callback=self.new_model_requested.emit,
            action_id="action_new_model",
        )
        self.new_3d_model_button = self._add_action_card(
            layout,
            icon="3D",
            title="New 3D Model",
            description="Create a space frame from a blank 3D canvas.",
            action_text="START",
            primary=False,
            callback=self.new_3d_model_requested.emit,
            action_id="action_new_3d_model",
        )
        self.import_button = self._add_action_card(
            layout,
            icon="PY",
            title="Import OpenSeesPy",
            description="Open an existing Python model for analysis.",
            action_text="START",
            primary=False,
            callback=self.import_opensees_requested.emit,
            action_id="action_import_openseespy",
        )
        self.open_project_button = self._add_action_card(
            layout,
            icon="O",
            title="Open Project",
            description="Continue a saved OpenFrame project.",
            action_text="OPEN",
            primary=False,
            callback=self.open_project_requested.emit,
            action_id="action_open_project",
        )
        self.template_button = self._add_action_card(
            layout,
            icon="T",
            title="Use Template",
            description="Start from a beam, frame, truss, or arch.",
            action_text="BROWSE",
            primary=False,
            callback=self.template_requested.emit,
            action_id="action_browse_templates",
        )
        return panel

    def _add_action_card(
        self,
        parent_layout: QVBoxLayout,
        *,
        icon: str,
        title: str,
        description: str,
        action_text: str,
        primary: bool,
        callback: Callable[[], None],
        action_id: str,
    ) -> QPushButton:
        card = QFrame()
        card.setObjectName("startPrimaryCard" if primary else "startOptionCard")
        card.setMinimumHeight(84)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(15, 12, 13, 12)
        layout.setSpacing(12)

        icon_label = QLabel(icon)
        icon_label.setObjectName("startPrimaryIcon" if primary else "startOptionIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        heading = QLabel(title)
        heading.setObjectName("startCardTitle")
        body = QLabel(description)
        body.setObjectName("startCardDescription")
        body.setWordWrap(True)
        copy.addWidget(heading)
        copy.addWidget(body)
        layout.addLayout(copy, 1)

        button = QPushButton(action_text)
        button.setObjectName("startPrimaryButton" if primary else "startSecondaryButton")
        button.setProperty("actionId", action_id)
        button.clicked.connect(callback)
        layout.addWidget(button)
        parent_layout.addWidget(card, 1)
        return button

    def _build_continue_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("startContinueColumn")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        heading = QLabel("CONTINUE WORK")
        heading.setObjectName("startColumnTitle")
        layout.addWidget(heading)

        session = QFrame()
        session.setObjectName("startSessionPanel")
        session_layout = QVBoxLayout(session)
        session_layout.setContentsMargins(18, 16, 18, 18)
        session_layout.setSpacing(9)

        self.session_title = QLabel("RECENT WORKSPACES")
        self.session_title.setObjectName("startFooterTitle")
        session_layout.addWidget(self.session_title)
        self._session_keys = ["", "", "", ""]
        self._session_rows: list[QFrame] = []
        self._session_names: list[QLabel] = []
        self._session_details: list[QLabel] = []
        self._session_buttons: list[QPushButton] = []
        for index in range(4):
            row, name_label, detail_label, button = self._build_session_row(index)
            self._session_rows.append(row)
            self._session_names.append(name_label)
            self._session_details.append(detail_label)
            self._session_buttons.append(button)
            session_layout.addWidget(row, 1)

        self.session_name = self._session_names[0]
        self.session_detail = self._session_details[0]
        self.resume_button = self._session_buttons[0]
        self._show_empty_sessions()
        layout.addWidget(session, 1)

        workflow = QFrame()
        workflow.setObjectName("startWorkflowPanel")
        workflow_layout = QVBoxLayout(workflow)
        workflow_layout.setContentsMargins(22, 18, 22, 20)
        workflow_layout.setSpacing(13)
        workflow_title = QLabel("WORKFLOW")
        workflow_title.setObjectName("startFooterTitle")
        workflow_layout.addWidget(workflow_title)

        steps = QHBoxLayout()
        steps.setSpacing(10)
        for number, name in (("01", "MODEL"), ("02", "ANALYSIS"), ("03", "RESULTS")):
            step = QFrame()
            step.setObjectName("startWorkflowStep")
            step_layout = QVBoxLayout(step)
            step_layout.setContentsMargins(14, 12, 14, 12)
            step_layout.setSpacing(3)
            number_label = QLabel(number)
            number_label.setObjectName("startStepNumber")
            name_label = QLabel(name)
            name_label.setObjectName("startStepName")
            step_layout.addWidget(number_label)
            step_layout.addWidget(name_label)
            steps.addWidget(step, 1)
        workflow_layout.addLayout(steps)
        layout.addWidget(workflow)
        return panel

    def _build_session_row(
        self, index: int
    ) -> tuple[QFrame, QLabel, QLabel, QPushButton]:
        row = QFrame()
        row.setObjectName("startSessionRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 10, 12, 10)
        row_layout.setSpacing(12)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        name_label = QLabel()
        name_label.setObjectName("startSessionRowName")
        name_label.setWordWrap(True)
        detail_label = QLabel()
        detail_label.setObjectName("startSessionRowDetail")
        detail_label.setWordWrap(True)
        copy.addWidget(name_label)
        copy.addWidget(detail_label)
        row_layout.addLayout(copy, 1)

        button = QPushButton("RETURN")
        button.setObjectName("startSessionReturnButton")
        button.clicked.connect(lambda checked=False, row_index=index: self._request_session(row_index))
        row_layout.addWidget(button)
        return row, name_label, detail_label, button

    def _request_session(self, index: int) -> None:
        key = self._session_keys[index]
        if key:
            self.session_requested.emit(key)
        else:
            self.resume_workspace_requested.emit()

    def _show_empty_sessions(self) -> None:
        self._session_keys = ["", "", "", ""]
        for index, row in enumerate(self._session_rows):
            if index == 0:
                self._session_names[index].setText("No active project")
                self._session_details[index].setText(
                    "Import a model or create a project to begin."
                )
                self._session_buttons[index].hide()
                row.show()
            else:
                row.hide()

    def set_sessions(
        self,
        sessions: list[tuple[str, str, str]],
        active_key: str | None = None,
    ) -> None:
        """Show up to four resumable workspaces, with the active one first."""
        ordered = list(sessions[:4])
        if active_key:
            ordered.sort(key=lambda item: item[0] != active_key)
        if not ordered:
            self.session_title.setText("RECENT WORKSPACES")
            self._show_empty_sessions()
            return

        self.session_title.setText("CURRENT SESSION")
        self._session_keys = ["", "", "", ""]
        for index, row in enumerate(self._session_rows):
            if index >= len(ordered):
                row.hide()
                continue
            key, name, detail = ordered[index]
            self._session_keys[index] = key
            self._session_names[index].setText(name)
            self._session_details[index].setText(detail)
            self._session_buttons[index].setText("RETURN" if key != active_key else "RESUME")
            self._session_buttons[index].show()
            row.show()

    def set_current_session(self, name: str | None, source: str = "") -> None:
        """Show a preserved workspace that can be resumed from Home."""
        if not name:
            self._show_empty_sessions()
            return

        self.session_title.setText("CURRENT SESSION")
        self._session_keys = ["", "", "", ""]
        self.session_name.setText(name)
        detail = f"{name}  ·  {source}" if source else name
        self.session_detail.setText(detail)
        self.resume_button.show()
        self._session_rows[0].show()
        for row in self._session_rows[1:]:
            row.hide()
