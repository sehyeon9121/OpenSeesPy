"""Reusable page-level header: title, subtitle, a status badge and an optional
action link. Shared by MODEL's workspace wrapper and SETUP's page so both read
as one consistent design instead of two hand-rolled headers."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PageHeader(QFrame):
    action_requested = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        action_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(12)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.subtitle_label)
        layout.addLayout(text_column, 1)

        self.action_button = QPushButton(action_text or "")
        self.action_button.setObjectName("pageActionButton")
        self.action_button.setVisible(bool(action_text))
        self.action_button.setFlat(True)
        self.action_button.setCursor(self._pointing_hand_cursor())
        self.action_button.clicked.connect(self.action_requested)
        layout.addWidget(self.action_button)

        self.status_badge = QLabel("")
        self.status_badge.setObjectName("pageStatusBadge")
        self.status_badge.setProperty("state", "ready")
        self.status_badge.setVisible(False)
        layout.addWidget(self.status_badge)

    @staticmethod
    def _pointing_hand_cursor():
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QCursor

        return QCursor(Qt.CursorShape.PointingHandCursor)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)

    def set_action_text(self, text: str | None) -> None:
        self.action_button.setText(text or "")
        self.action_button.setVisible(bool(text))

    def set_status(self, text: str, state: str = "ready") -> None:
        self.status_badge.setText(text)
        self.status_badge.setProperty("state", state)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.status_badge.setVisible(True)
