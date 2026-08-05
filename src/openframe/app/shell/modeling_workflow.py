"""Visible authoring sequence for a complete structural model."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QToolButton, QWidget


class ModelingWorkflowBar(QFrame):
    """Keeps prerequisites visible without turning them into modal wizard pages."""

    step_selected = Signal(str)

    STEPS = (
        ("setup", "기본 설정", "차원, 자유도, 단위와 기본 해석 조건"),
        ("materials", "재료", "재료 모델과 물성"),
        ("sections", "단면", "단면 형상과 강성"),
        ("geometry", "구조 모델", "절점과 구조 요소"),
        ("supports", "지점", "경계조건과 구속"),
        ("loads", "하중", "하중 케이스와 하중 배치"),
        ("analysis", "해석", "모델 검증과 해석 실행"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelingWorkflow")
        self._buttons: dict[str, QToolButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(0)
        title = QLabel("모델 작성 흐름")
        title.setObjectName("workflowTitle")
        layout.addWidget(title)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (key, label, tooltip) in enumerate(self.STEPS, start=1):
            if index > 1:
                connector = QLabel("›")
                connector.setObjectName("workflowConnector")
                layout.addWidget(connector)
            button = QToolButton()
            button.setObjectName("workflowStep")
            button.setText(f"{index}  {label}")
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, step=key: self._select(step))
            group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self.set_current_step("setup")

    def current_step(self) -> str:
        return next(
            (key for key, button in self._buttons.items() if button.isChecked()),
            "setup",
        )

    def set_current_step(self, key: str) -> None:
        if key not in self._buttons:
            raise ValueError(f"Unknown modeling workflow step: {key}")
        self._buttons[key].setChecked(True)

    def _select(self, key: str) -> None:
        self.set_current_step(key)
        self.step_selected.emit(key)
