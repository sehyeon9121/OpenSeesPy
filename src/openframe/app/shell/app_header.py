"""Compact application header matching the analysis workspace design."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget


class AppHeader(QFrame):
    upload_requested = Signal()
    run_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(10)
        mark = QLabel("OF")
        mark.setObjectName("brandMark")
        brand = QLabel("OpenFrame Studio")
        brand.setObjectName("brandName")
        self.status_label = QLabel("●  READY")
        self.status_label.setObjectName("readyBadge")
        self.upload_button = QPushButton("UPLOAD .PY")
        self.upload_button.setObjectName("uploadButton")
        self.upload_button.clicked.connect(self.upload_requested)
        self.run_button = QPushButton("▶  RUN ANALYSIS")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run_requested)
        layout.addWidget(mark)
        layout.addWidget(brand)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        layout.addWidget(self.upload_button)
        layout.addWidget(self.run_button)

    def set_busy(self, busy: bool) -> None:
        self.status_label.setText("●  READING MODEL" if busy else "●  READY")
        self.upload_button.setDisabled(busy)
        self.run_button.setDisabled(busy)
