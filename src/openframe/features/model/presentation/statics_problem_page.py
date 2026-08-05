"""First usable direct-model page for material-free textbook beam problems."""

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
    UniformElementLoad,
    UnitSystem,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver
from openframe.features.results.presentation.result_viewport import ResultViewport
from openframe.features.results.reactions import support_reactions


class StaticsProblemPage(QFrame):
    """Template authoring and N/V/M result view, independent of material stiffness."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("staticsProblemPage")
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._model: StructuralModel | None = None
        self._result = None
        self._solver = MaterialFreeStaticsSolver()

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        title = QLabel("구조역학 정정구조 계산")
        title.setObjectName("setupTitle")
        description = QLabel(
            "재료와 단면 강성 없이 평형조건으로 반력, 전단력도와 휨모멘트도를 계산합니다. "
            "현재 첫 구현은 단순지지보와 캔틸레버보 문제를 지원합니다."
        )
        description.setObjectName("setupDescription")
        description.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(description)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_inputs())
        body.addWidget(self._build_results(), 1)
        root.addLayout(body, 1)

        self.solve_button.clicked.connect(self.solve)
        self.support_type.currentIndexChanged.connect(self._refresh_load_name)
        self.load_type.currentIndexChanged.connect(self._refresh_load_name)
        self._refresh_load_name()

    def _build_inputs(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("setupFormPanel")
        panel.setFixedWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(12)
        heading = QLabel("문제 조건")
        heading.setObjectName("setupSectionTitle")
        layout.addWidget(heading)

        form = QFormLayout()
        self.support_type = QComboBox()
        self.support_type.addItem("단순지지보", "simple")
        self.support_type.addItem("캔틸레버보", "cantilever")
        self.load_type = QComboBox()
        self.load_type.addItem("집중하중", "point")
        self.load_type.addItem("등분포하중", "uniform")
        self.span = self._number(4.0, 0.01, 100_000.0)
        self.load = self._number(10.0, 0.0, 1_000_000.0)
        self.span_name = QLabel("경간")
        self.load_name = QLabel("하중")
        form.addRow("구조 형식", self.support_type)
        form.addRow("하중 형식", self.load_type)
        form.addRow(self.span_name, self.span)
        form.addRow(self.load_name, self.load)
        layout.addLayout(form)

        self.solve_button = QPushButton("반력 및 다이어그램 계산")
        self.solve_button.setObjectName("setupContinueButton")
        layout.addWidget(self.solve_button)
        self.check_message = QLabel("조건을 입력하고 계산하세요.")
        self.check_message.setWordWrap(True)
        self.check_message.setObjectName("setupSummaryHint")
        layout.addWidget(self.check_message)
        self.reaction_summary = QLabel("반력 결과가 여기에 표시됩니다.")
        self.reaction_summary.setWordWrap(True)
        self.reaction_summary.setObjectName("setupCommandPreview")
        layout.addWidget(self.reaction_summary)
        layout.addStretch(1)
        return panel

    def _build_results(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("setupSummaryPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        for label, result_type in (
            ("반력", "reaction"),
            ("축력도 N", "axial"),
            ("전단력도 V", "shear"),
            ("모멘트도 M", "moment"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked=False, kind=result_type: self.viewport.set_result_type(kind)
            )
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.viewport = ResultViewport()
        self.viewport.set_result_type("reaction")
        layout.addWidget(self.viewport, 1)
        return panel

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self.viewport.set_unit_system(unit_system)
        self._refresh_load_name()

    def solve(self) -> None:
        model = self._build_model()
        result = self._solver.solve(model)
        self._model = model
        self._result = result
        self.viewport.set_model(model)
        if result.status.value == "completed":
            self.viewport.show_result(result)
            self.viewport.set_result_type("reaction")
            self.check_message.setText(result.messages[0])
            rows = []
            for reaction in support_reactions(model, result):
                rows.append(
                    f"R{reaction.node_tag}:  Fx={reaction.fx:.4g}, "
                    f"Fy={reaction.fy:.4g}, Mz={reaction.mz:.4g}"
                )
            self.reaction_summary.setText("\n".join(rows))
        else:
            self.viewport.clear_result()
            self.check_message.setText("\n".join(result.messages))
            self.reaction_summary.setText("계산 결과 없음")

    def _build_model(self) -> StructuralModel:
        length = self.span.value()
        magnitude = self.load.value()
        simple = self.support_type.currentData() == "simple"
        point = self.load_type.currentData() == "point"
        if point and simple:
            nodes = {
                1: Node(1, 0.0, 0.0),
                2: Node(2, length / 2.0, 0.0),
                3: Node(3, length, 0.0),
            }
            elements = {
                1: Element(1, 1, 2, "frame"),
                2: Element(2, 2, 3, "frame"),
            }
            boundaries = [
                BoundaryCondition(1, (True, True, False)),
                BoundaryCondition(3, (False, True, False)),
            ]
            return StructuralModel(
                nodes=nodes,
                elements=elements,
                boundaries=boundaries,
                nodal_loads=[NodalLoad(2, (0.0, -magnitude, 0.0))],
            )

        nodes = {1: Node(1, 0.0, 0.0), 2: Node(2, length, 0.0)}
        elements = {1: Element(1, 1, 2, "frame")}
        boundaries = (
            [
                BoundaryCondition(1, (True, True, False)),
                BoundaryCondition(2, (False, True, False)),
            ]
            if simple
            else [BoundaryCondition(1, (True, True, True))]
        )
        return StructuralModel(
            nodes=nodes,
            elements=elements,
            boundaries=boundaries,
            nodal_loads=[NodalLoad(2, (0.0, -magnitude, 0.0))] if point else [],
            element_loads=[UniformElementLoad(1, wy=-magnitude)] if not point else [],
        )

    def _refresh_load_name(self) -> None:
        self.span_name.setText(f"경간 ({self._unit_system.length})")
        if self.load_type.currentData() == "uniform":
            self.load_name.setText(
                f"등분포하중 ({self._unit_system.force}/{self._unit_system.length})"
            )
        else:
            location = "중앙" if self.support_type.currentData() == "simple" else "자유단"
            self.load_name.setText(f"{location} 집중하중 ({self._unit_system.force})")

    @staticmethod
    def _number(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setRange(minimum, maximum)
        field.setDecimals(4)
        field.setValue(value)
        return field
