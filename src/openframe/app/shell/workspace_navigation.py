"""Compact vertical navigation for the engineering workflow."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QToolButton, QVBoxLayout, QWidget


class WorkspaceNavigation(QFrame):
    current_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceNavigation")
        self._buttons: dict[str, QToolButton] = {}
        self.setFixedWidth(72)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 10, 7, 10)
        layout.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, text, tooltip in (
            ("model", "M\n모델", "절점, 부재, 재료와 경계조건"),
            ("loads", "L\n하중", "하중 케이스와 하중 배치"),
            ("analysis", "A\n해석", "해석 방법과 실행 설정"),
            ("results", "R\n결과", "변위, 반력과 부재력 결과"),
            ("code", "C\n코드", "생성되는 OpenSeesPy 코드"),
        ):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, name=key: self._select(name))
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        focus = QToolButton()
        focus.setText("F\n집중")
        focus.setToolTip("좌우 패널을 숨기고 뷰포트에 집중")
        focus.setCheckable(True)
        focus.clicked.connect(lambda checked=False: self._select("viewport"))
        self._group.addButton(focus)
        self._buttons["viewport"] = focus
        layout.addWidget(focus)
        self._buttons["model"].setChecked(True)

    def current_section(self) -> str:
        return next(
            (key for key, button in self._buttons.items() if button.isChecked()),
            "model",
        )

    def set_current_section(self, key: str, *, emit: bool = False) -> None:
        if key not in self._buttons:
            raise ValueError(f"Unknown workspace section: {key}")
        self._buttons[key].setChecked(True)
        if emit:
            self.current_changed.emit(key)

    def _select(self, key: str) -> None:
        self.set_current_section(key, emit=True)
