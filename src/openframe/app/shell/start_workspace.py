"""Compact Stitch-matched project hub for OpenFrame Studio."""

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class StartWorkspace(QFrame):
    """Project entry points and resumable sessions without changing app behavior."""

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
        outer.setContentsMargins(24, 28, 24, 22)
        outer.setSpacing(0)

        content = QFrame()
        content.setObjectName("startContent")
        content.setMaximumWidth(1320)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("startHubHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 16)
        header_layout.setSpacing(3)
        title = QLabel("PROJECTS")
        title.setObjectName("startPageTitle")
        description = QLabel("Start a new structural model or continue your recent work.")
        description.setObjectName("startPageDescription")
        header_layout.addWidget(title)
        header_layout.addWidget(description)
        layout.addWidget(header)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 32, 0, 0)
        columns.setSpacing(28)
        columns.addWidget(self._build_start_panel(), 11)
        columns.addWidget(self._build_continue_panel(), 9)
        layout.addLayout(columns)
        layout.addStretch(1)
        layout.addSpacing(32)
        layout.addWidget(self._build_workflow_panel())

        outer.addWidget(content, 1, Qt.AlignmentFlag.AlignHCenter)

    @staticmethod
    def _section_heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("startSectionHeading")
        return label

    def _build_start_panel(self) -> QWidget:
        column = QFrame()
        column.setObjectName("startColumn")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._section_heading("NEW PROJECT"))

        panel = QFrame()
        panel.setObjectName("startActionPanel")
        actions = QVBoxLayout(panel)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(0)

        self.new_model_button = self._add_action_row(
            actions, "2D", "New 2D Model",
            "Create a 2D structural frame from a blank workspace", "NEW",
            self.new_model_requested.emit, "action_new_model", first=True,
        )
        self.new_3d_model_button = self._add_action_row(
            actions, "3D", "New 3D Model", "Create a 3D structural model", "NEW",
            self.new_3d_model_requested.emit, "action_new_3d_model",
        )
        self.import_button = self._add_action_row(
            actions, "PY", "Import OpenSeesPy",
            "Import an existing .py structural model for analysis", "IMPORT",
            self.import_opensees_requested.emit, "action_import_openseespy",
        )
        self.open_project_button = self._add_action_row(
            actions, "▣", "Open Project", "Browse local files for an existing project", "OPEN",
            self.open_project_requested.emit, "action_open_project",
        )
        self.template_button = self._add_action_row(
            actions, "▦", "Templates", "Start from a beam, frame, truss, arch, or example model",
            "BROWSE", self.template_requested.emit, "action_browse_templates", last=True,
        )
        layout.addWidget(panel)
        layout.addStretch(1)
        return column

    def _add_action_row(
        self,
        parent_layout: QVBoxLayout,
        icon: str,
        title: str,
        description: str,
        action_text: str,
        callback: Callable[[], None],
        action_id: str,
        *,
        first: bool = False,
        last: bool = False,
    ) -> QPushButton:
        row = QFrame()
        row.setObjectName("startActionRow")
        row.setProperty("first", first)
        row.setProperty("last", last)
        row.setMinimumHeight(78)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(18, 14, 18, 14)
        row_layout.setSpacing(16)

        icon_label = QLabel(icon)
        icon_label.setObjectName("startActionIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(icon_label)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("startCardTitle")
        body = QLabel(description)
        body.setObjectName("startCardDescription")
        body.setWordWrap(False)
        copy.addWidget(heading)
        copy.addWidget(body)
        row_layout.addLayout(copy, 1)

        button = QPushButton(action_text)
        button.setObjectName("startActionButton")
        button.setProperty("primary", first)
        button.setProperty("actionId", action_id)
        button.clicked.connect(callback)
        row_layout.addWidget(button)
        parent_layout.addWidget(row)
        return button

    def _build_continue_panel(self) -> QWidget:
        column = QFrame()
        column.setObjectName("startContinueColumn")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._section_heading("RECENT PROJECTS"))

        session = QFrame()
        session.setObjectName("startSessionPanel")
        session_layout = QVBoxLayout(session)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.setSpacing(0)

        self.session_title = QLabel("RECENT PROJECTS")
        self.session_title.setObjectName("startCurrentSessionBadge")
        self.session_title.hide()
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
            session_layout.addWidget(row)

        self.session_name = self._session_names[0]
        self.session_detail = self._session_details[0]
        self.resume_button = self._session_buttons[0]
        self._show_empty_sessions()
        layout.addWidget(session)
        layout.addStretch(1)
        return column

    def _build_session_row(self, index: int) -> tuple[QFrame, QLabel, QLabel, QPushButton]:
        row = QFrame()
        row.setObjectName("startSessionRow")
        row.setProperty("active", index == 0)
        row.setMinimumHeight(72 if index else 94)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(18, 14, 18, 14)
        row_layout.setSpacing(12)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        badge = QLabel("CURRENT SESSION")
        badge.setObjectName("startCurrentSessionBadge")
        badge.setVisible(index == 0)
        name_label = QLabel()
        name_label.setObjectName("startSessionRowName")
        name_label.setWordWrap(False)
        detail_label = QLabel()
        detail_label.setObjectName("startSessionRowDetail")
        detail_label.setWordWrap(False)
        copy.addWidget(badge)
        copy.addWidget(name_label)
        copy.addWidget(detail_label)
        row_layout.addLayout(copy, 1)

        button = QPushButton("RETURN")
        button.setObjectName("startSessionReturnButton")
        button.clicked.connect(lambda checked=False, row_index=index: self._request_session(row_index))
        row_layout.addWidget(button)
        return row, name_label, detail_label, button

    def _build_workflow_panel(self) -> QFrame:
        wrapper = QFrame()
        wrapper.setObjectName("startWorkflowWrapper")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._section_heading("WORKFLOW"))

        panel = QFrame()
        panel.setObjectName("startWorkflowPanel")
        steps = QHBoxLayout(panel)
        steps.setContentsMargins(12, 12, 12, 12)
        steps.setSpacing(8)
        for index, (name, detail) in enumerate((
            ("01 MODEL", "Inspect model"),
            ("02 SETUP", "Configure analysis"),
            ("03 RESULTS", "Review responses"),
        )):
            step = QFrame()
            step.setObjectName("startWorkflowStep")
            step_layout = QVBoxLayout(step)
            step_layout.setContentsMargins(8, 8, 8, 8)
            step_layout.setSpacing(2)
            name_label = QLabel(name)
            name_label.setObjectName("startStepName")
            name_label.setProperty("active", index == 0)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail_label = QLabel(detail)
            detail_label.setObjectName("startStepDetail")
            detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step_layout.addWidget(name_label)
            step_layout.addWidget(detail_label)
            steps.addWidget(step, 1)
            if index < 2:
                arrow = QLabel("→")
                arrow.setObjectName("startWorkflowArrow")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                steps.addWidget(arrow)
        layout.addWidget(panel)
        return wrapper

    def _request_session(self, index: int) -> None:
        key = self._session_keys[index]
        if key:
            self.session_requested.emit(key)
        else:
            self.resume_workspace_requested.emit()

    def _show_empty_sessions(self) -> None:
        self._session_keys = ["", "", "", ""]
        self.session_title.setText("RECENT PROJECTS")
        self.session_title.hide()
        for index, row in enumerate(self._session_rows):
            if index == 0:
                row.setProperty("active", False)
                self._session_names[index].setText("No recent projects.")
                self._session_details[index].setText("Create or import a model to begin.")
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
            row.setProperty("active", index == 0 and key == active_key)
            row.style().unpolish(row)
            row.style().polish(row)
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
        self._session_rows[0].setProperty("active", True)
        self._session_rows[0].style().unpolish(self._session_rows[0])
        self._session_rows[0].style().polish(self._session_rows[0])
        self.session_name.setText(name)
        self.session_detail.setText(f"{name}  ·  {source}" if source else name)
        self.resume_button.show()
        self._session_rows[0].show()
        for row in self._session_rows[1:]:
            row.hide()
