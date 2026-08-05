"""Modal analysis progress feedback shared by every workspace."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class AnalysisProgressBanner(QDialog):
    """Keep the workspace covered while an analysis runs, then close automatically.

    The historical class name is retained so callers outside the shell do not need
    to change, although the widget is now a centered modal dialog rather than a
    banner embedded above the workspace.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisProgressDialog")
        self.setWindowTitle("Calculating results")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setFixedSize(560, 190)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        self.title = QLabel("Calculating results")
        self.title.setObjectName("analysisProgressTitle")
        layout.addWidget(self.title)

        self.progress = QProgressBar()
        self.progress.setObjectName("analysisProgressBar")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.detail = QLabel("In progress...")
        self.detail.setObjectName("analysisProgressDetail")
        self.detail.setMinimumHeight(48)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.detail)

    def reset(self) -> None:
        self.hide()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.detail.setText("In progress...")

    def show_running(self, analysis_name: str) -> None:
        self.title.setText("Calculating results")
        self.detail.setText(f"{analysis_name} analysis in progress...")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.show()
        self.raise_()
        self.activateWindow()

    def set_progress(self, value: int | None, stage: str) -> None:
        """Connection point for a future runner that reports real progress."""
        self.detail.setText(stage)
        if value is None:
            self.progress.setRange(0, 0)
            self.progress.setTextVisible(False)
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(value, 100)))
        self.progress.setTextVisible(True)

    def show_completed(self, detail: str) -> None:
        """Close immediately; completed results remain available in RESULTS."""
        self.detail.setText(detail)
        self.accept()

    def show_failed(self, detail: str) -> None:
        """Close before the caller opens the dedicated error message box."""
        self.detail.setText(detail)
        super().reject()

    def reject(self) -> None:
        """Ignore user/window-manager dismissal while the solver is still active."""
        if self.parent() is not None:
            thread = getattr(self.parent(), "_analysis_run_thread", None)
            if thread is not None and thread.isRunning():
                return
        super().reject()
