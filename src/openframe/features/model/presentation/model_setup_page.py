"""Purpose-built first step for configuring a new structural model."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ModelSetupPage(QFrame):
    """Collects the small set of decisions required before authoring entities."""

    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelSetupPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        eyebrow = QLabel("새 구조 모델 · 1단계")
        eyebrow.setObjectName("setupEyebrow")
        title = QLabel("기본 모델 설정")
        title.setObjectName("setupTitle")
        description = QLabel(
            "모델 공간과 단위계를 먼저 정의합니다. 이 설정은 절점 자유도와 생성되는 "
            "OpenSeesPy 모델 명령의 기준이 됩니다."
        )
        description.setObjectName("setupDescription")
        description.setWordWrap(True)
        root.addWidget(eyebrow)
        root.addWidget(title)
        root.addWidget(description)

        content = QHBoxLayout()
        content.setSpacing(18)
        content.addWidget(self._build_form(), 3)
        content.addWidget(self._build_summary(), 2)
        root.addLayout(content, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.continue_button = QPushButton("재료 설정으로 계속  →")
        self.continue_button.setObjectName("setupContinueButton")
        self.continue_button.clicked.connect(self.continue_requested)
        footer.addWidget(self.continue_button)
        root.addLayout(footer)

        self.dimension.currentIndexChanged.connect(self._dimension_changed)
        for selector in (
            self.model_family,
            self.ndf,
            self.force_unit,
            self.length_unit,
            self.analysis_kind,
        ):
            selector.currentIndexChanged.connect(self._refresh_summary)
        self._refresh_summary()

    def _build_form(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("setupFormPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 17, 18, 17)
        layout.setSpacing(16)

        layout.addWidget(self._section_title("모델 공간", "구조물의 차원과 기본 자유도"))
        space_form = QFormLayout()
        space_form.setHorizontalSpacing(18)
        space_form.setVerticalSpacing(11)
        self.dimension = self._selector(("2D 평면 모델", "3D 공간 모델"))
        self.model_family = self._selector(("프레임 구조", "트러스 구조", "일반 구조"))
        self.ndf = self._selector(("3 · UX, UY, RZ", "2 · UX, UY"))
        space_form.addRow("모델 차원", self.dimension)
        space_form.addRow("구조 형식", self.model_family)
        space_form.addRow("절점 자유도", self.ndf)
        layout.addLayout(space_form)

        divider = QFrame()
        divider.setObjectName("setupDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        layout.addWidget(self._section_title("단위계", "입력과 화면 표시에 사용할 기본 단위"))
        unit_form = QFormLayout()
        unit_form.setHorizontalSpacing(18)
        unit_form.setVerticalSpacing(11)
        self.force_unit = self._selector(("kN", "N", "tf"))
        self.length_unit = self._selector(("m", "mm", "cm"))
        unit_form.addRow("힘", self.force_unit)
        unit_form.addRow("길이", self.length_unit)
        layout.addLayout(unit_form)

        divider = QFrame()
        divider.setObjectName("setupDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        layout.addWidget(self._section_title("기본 해석 조건", "초기 모델 검증에 사용할 기준"))
        analysis_form = QFormLayout()
        analysis_form.setHorizontalSpacing(18)
        analysis_form.setVerticalSpacing(11)
        self.analysis_kind = self._selector(
            ("선형 정적해석", "비선형 정적해석", "시간이력해석")
        )
        self.gravity_direction = self._selector(("-Y", "-Z", "+Y", "+Z"))
        analysis_form.addRow("해석 유형", self.analysis_kind)
        analysis_form.addRow("중력 방향", self.gravity_direction)
        layout.addLayout(analysis_form)
        layout.addStretch(1)
        return panel

    def _build_summary(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("setupSummaryPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 17, 18, 17)
        layout.setSpacing(12)

        heading = QLabel("생성될 모델 기준")
        heading.setObjectName("setupSectionTitle")
        layout.addWidget(heading)
        hint = QLabel("이 값은 이후 단계의 입력 형식과 검증 규칙에 적용됩니다.")
        hint.setObjectName("setupSummaryHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.summary_dimension = self._summary_row(layout, "모델 공간")
        self.summary_dof = self._summary_row(layout, "절점 자유도")
        self.summary_units = self._summary_row(layout, "기본 단위")
        self.summary_analysis = self._summary_row(layout, "초기 해석")

        code_label = QLabel("OpenSeesPy 모델 명령")
        code_label.setObjectName("setupCodeLabel")
        layout.addWidget(code_label)
        self.command_preview = QLabel()
        self.command_preview.setObjectName("setupCommandPreview")
        self.command_preview.setWordWrap(True)
        layout.addWidget(self.command_preview)

        note = QLabel(
            "다음 단계에서 재료와 단면을 정의한 뒤 구조 요소를 작성하게 됩니다."
        )
        note.setObjectName("setupNextHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    def _dimension_changed(self) -> None:
        is_3d = self.dimension.currentIndex() == 1
        self.ndf.blockSignals(True)
        self.ndf.clear()
        self.ndf.addItems(
            ("6 · UX, UY, UZ, RX, RY, RZ", "3 · UX, UY, UZ")
            if is_3d
            else ("3 · UX, UY, RZ", "2 · UX, UY")
        )
        self.ndf.blockSignals(False)
        self.gravity_direction.setCurrentText("-Z" if is_3d else "-Y")
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        ndm = 3 if self.dimension.currentIndex() == 1 else 2
        ndf = 6 if self.ndf.currentIndex() == 0 and ndm == 3 else 3
        if self.ndf.currentIndex() == 1:
            ndf = 3 if ndm == 3 else 2
        self.summary_dimension.setText(f"{ndm}D · {self.model_family.currentText()}")
        self.summary_dof.setText(self.ndf.currentText())
        self.summary_units.setText(f"{self.force_unit.currentText()}, {self.length_unit.currentText()}")
        self.summary_analysis.setText(self.analysis_kind.currentText())
        self.command_preview.setText(f"ops.model('basic', '-ndm', {ndm}, '-ndf', {ndf})")

    @staticmethod
    def _selector(items: tuple[str, ...]) -> QComboBox:
        selector = QComboBox()
        selector.addItems(items)
        return selector

    @staticmethod
    def _section_title(title: str, hint: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("setupSectionTitle")
        hint_label = QLabel(hint)
        hint_label.setObjectName("setupSectionHint")
        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        return container

    @staticmethod
    def _summary_row(layout: QVBoxLayout, name: str) -> QLabel:
        row = QFrame()
        row.setObjectName("setupSummaryRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 8, 10, 8)
        label = QLabel(name)
        label.setObjectName("setupSummaryName")
        value = QLabel()
        value.setObjectName("setupSummaryValue")
        row_layout.addWidget(label)
        row_layout.addStretch(1)
        row_layout.addWidget(value)
        layout.addWidget(row)
        return value


class WorkflowPlaceholderPage(QFrame):
    """A truthful empty state for workflow editors that are not connected yet."""

    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowPlaceholderPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 32)
        eyebrow = QLabel("모델 작성 단계")
        eyebrow.setObjectName("setupEyebrow")
        heading = QLabel(title)
        heading.setObjectName("setupTitle")
        detail = QLabel(description)
        detail.setObjectName("setupDescription")
        detail.setWordWrap(True)
        state = QLabel("편집 인터페이스 연결 예정")
        state.setObjectName("workflowPlaceholderState")
        layout.addWidget(eyebrow)
        layout.addWidget(heading)
        layout.addWidget(detail)
        layout.addSpacing(8)
        layout.addWidget(state)
        layout.addStretch(1)
