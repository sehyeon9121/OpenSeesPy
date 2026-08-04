"""Visible analysis lifecycle feedback shared by every workspace."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AnalysisProgressBanner(QFrame):
    """Show honest running, completed and failed states without fake percentages."""

    view_results_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analysisProgressRunning")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        self.state_badge = QLabel("RUNNING")
        self.state_badge.setObjectName("analysisProgressBadge")
        layout.addWidget(self.state_badge)

        copy = QVBoxLayout()
        copy.setSpacing(1)
        self.title = QLabel("Analysis is running")
        self.title.setObjectName("analysisProgressTitle")
        self.detail = QLabel("Preparing the structural model and solver.")
        self.detail.setObjectName("analysisProgressDetail")
        copy.addWidget(self.title)
        copy.addWidget(self.detail)
        layout.addLayout(copy, 1)

        self.progress = QProgressBar()
        self.progress.setObjectName("analysisProgressBar")
        self.progress.setMinimumWidth(260)
        self.progress.setMaximumWidth(430)
        layout.addWidget(self.progress)

        self.view_results_button = QPushButton("VIEW RESULTS")
        self.view_results_button.setObjectName("analysisProgressAction")
        self.view_results_button.clicked.connect(self.view_results_requested)
        layout.addWidget(self.view_results_button)

        self.dismiss_button = QPushButton("CLOSE")
        self.dismiss_button.setObjectName("analysisProgressDismiss")
        self.dismiss_button.clicked.connect(self.hide)
        layout.addWidget(self.dismiss_button)

        self.reset()

    def reset(self) -> None:
        self.hide()
        self.view_results_button.hide()
        self.dismiss_button.hide()

    def show_running(self, analysis_name: str) -> None:
        self._set_state("analysisProgressRunning")
        self.state_badge.setText("RUNNING")
        self.title.setText(f"{analysis_name} analysis in progress")
        self.detail.setText("Building the model and solving. Please wait for completion.")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.view_results_button.hide()
        self.dismiss_button.hide()
        self.show()

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
        self._set_state("analysisProgressComplete")
        self.state_badge.setText("COMPLETED")
        self.title.setText("Analysis completed successfully")
        self.detail.setText(detail)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("100%  COMPLETE")
        self.progress.setTextVisible(True)
        self.view_results_button.show()
        self.dismiss_button.show()
        self.show()

    def show_failed(self, detail: str) -> None:
        self._set_state("analysisProgressFailed")
        self.state_badge.setText("FAILED")
        self.title.setText("Analysis could not be completed")
        self.detail.setText(detail)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("FAILED")
        self.progress.setTextVisible(True)
        self.view_results_button.hide()
        self.dismiss_button.show()
        self.show()

    def _set_state(self, object_name: str) -> None:
        self.setObjectName(object_name)
        self.style().unpolish(self)
        self.style().polish(self)
        self.progress.style().unpolish(self.progress)
        self.progress.style().polish(self.progress)
