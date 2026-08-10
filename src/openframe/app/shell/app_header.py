"""Application command bar shared by modeling, analysis and results."""

from pathlib import Path

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

APP_ICON_PATH = Path(__file__).resolve().parents[2] / "resources" / "icons" / "app_icon.png"


class AppHeader(QFrame):
    home_requested = Signal()
    upload_requested = Signal()
    run_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(10)
        self.brand_button = QPushButton()
        self.brand_button.setObjectName("brandMark")
        if APP_ICON_PATH.exists():
            self.brand_button.setIcon(QIcon(str(APP_ICON_PATH)))
            self.brand_button.setIconSize(QSize(26, 26))
        else:
            self.brand_button.setText("OF")
        self.brand_button.setToolTip("Go to Home")
        self.brand_button.clicked.connect(self.home_requested)
        brand = QLabel("OpenFrame Studio")
        brand.setObjectName("brandName")
        self.home_button = QPushButton("HOME")
        self.home_button.setObjectName("homeButton")
        self.home_button.clicked.connect(self.home_requested)
        self.status_label = QLabel("●  READY")
        self.status_label.setObjectName("readyBadge")
        self.upload_button = QPushButton("UPLOAD .PY")
        self.upload_button.setObjectName("uploadButton")
        self.upload_button.clicked.connect(self.upload_requested)
        self.run_button = QPushButton("▶  RUN ANALYSIS")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run_requested)
        layout.addWidget(self.brand_button)
        layout.addWidget(brand)
        layout.addWidget(self.home_button)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addWidget(self.upload_button)
        layout.addWidget(self.run_button)

    def set_welcome_mode(self, welcome: bool) -> None:
        """Keep the first-run screen focused on project entry choices."""
        self.status_label.setText("2D STRUCTURAL MODELING & ANALYSIS" if welcome else "●  READY")
        self.status_label.setObjectName("welcomeHeaderLabel" if welcome else "readyBadge")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.home_button.setVisible(not welcome)
        self.upload_button.setVisible(not welcome)
        self.run_button.setVisible(not welcome)

    def set_busy(self, busy: bool, label: str | None = "READING MODEL") -> None:
        self.status_label.setText(f"●  {label}" if busy and label else "●  READY")
        self.upload_button.setDisabled(busy)
        self.run_button.setDisabled(busy)
