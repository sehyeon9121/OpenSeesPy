"""Application command bar shared by modeling, analysis and results."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget


class AppHeader(QFrame):
    home_requested = Signal()
    upload_requested = Signal()
    run_requested = Signal()
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)
        self.brand_button = QPushButton("OF")
        self.brand_button.setObjectName("brandMark")
        self.brand_button.setToolTip("Go to Home")
        self.brand_button.clicked.connect(self.home_requested)
        brand = QLabel("OpenFrame")
        brand.setObjectName("brandName")
        self.home_button = QPushButton("HOME")
        self.home_button.setObjectName("homeButton")
        self.home_button.clicked.connect(self.home_requested)
        self.project_divider = QLabel("│")
        self.project_divider.setObjectName("headerDivider")
        self.project_label = QLabel("새 구조 모델")
        self.project_label.setObjectName("projectName")
        self.status_label = QLabel("●  준비됨")
        self.status_label.setObjectName("readyBadge")
        self.undo_button = QPushButton("↶")
        self.undo_button.setObjectName("headerToolButton")
        self.undo_button.setToolTip("실행 취소 · 직접 모델링 기능 연결 예정")
        self.undo_button.setDisabled(True)
        self.redo_button = QPushButton("↷")
        self.redo_button.setObjectName("headerToolButton")
        self.redo_button.setToolTip("다시 실행 · 직접 모델링 기능 연결 예정")
        self.redo_button.setDisabled(True)
        self.upload_button = QPushButton("모델 가져오기")
        self.upload_button.setObjectName("uploadButton")
        self.upload_button.clicked.connect(self.upload_requested)
        self.export_button = QPushButton("<>  OpenSeesPy 내보내기")
        self.export_button.setObjectName("exportButton")
        self.export_button.clicked.connect(self.export_requested)
        self.run_button = QPushButton("▶  RUN ANALYSIS")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run_requested)
        layout.addWidget(self.brand_button)
        layout.addWidget(brand)
        layout.addWidget(self.home_button)
        layout.addWidget(self.project_divider)
        layout.addWidget(self.project_label)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        layout.addWidget(self.upload_button)
        layout.addWidget(self.export_button)
        layout.addWidget(self.run_button)

    def set_welcome_mode(self, welcome: bool) -> None:
        """Keep the first-run screen focused on project entry choices."""
        self.status_label.setText("구조 모델링 및 해석" if welcome else "●  준비됨")
        self.status_label.setObjectName("welcomeHeaderLabel" if welcome else "readyBadge")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.home_button.setVisible(not welcome)
        self.project_divider.setVisible(not welcome)
        self.project_label.setVisible(not welcome)
        self.undo_button.setVisible(not welcome)
        self.redo_button.setVisible(not welcome)
        self.upload_button.setVisible(not welcome)
        self.export_button.setVisible(not welcome)
        self.run_button.setVisible(not welcome)

    def set_busy(self, busy: bool, label: str | None = "READING MODEL") -> None:
        self.status_label.setText(f"●  {label}" if busy and label else "●  READY")
        self.upload_button.setDisabled(busy)
        self.export_button.setDisabled(busy)
        self.run_button.setDisabled(busy)

    def set_project_title(self, title: str) -> None:
        self.project_label.setText(title)
        self.project_label.setToolTip(title)
