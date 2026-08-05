"""Professional free-form authoring surface for 2D structural-mechanics models."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, UnitSystem
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
from openframe.features.results.presentation.result_viewport import ResultViewport


class SafeDoubleSpinBox(QDoubleSpinBox):
    """Prevent a scrolling gesture from silently changing an engineering value."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class SafeSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


class ModelingInterfacePage(QFrame):
    """One-screen workflow: draw, inspect, assign conditions, and review results."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("modelingInterfacePage")
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._solver = MaterialFreeStaticsSolver()
        self.canvas = StaticsDrawingCanvas()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 10)
        root.setSpacing(8)
        root.addWidget(self._build_header())
        root.addWidget(self._build_tool_bar())
        root.addWidget(self._build_tool_context())

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(self._build_modeling_workspace())
        self.workspace_stack.addWidget(self._build_result_workspace())
        root.addWidget(self.workspace_stack, 1)
        root.addWidget(self._build_status_bar())

        self.canvas.model_changed.connect(self._refresh_status)
        self.delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.canvas)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.delete_shortcut.activated.connect(self.canvas.delete_selected)
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self.canvas)
        self.undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.undo_shortcut.activated.connect(self.canvas.undo)
        self.redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self.canvas)
        self.redo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.redo_shortcut.activated.connect(self.canvas.redo)
        self._activate_select_tool()
        self._refresh_status()

    def _build_header(self) -> QFrame:
        header = QFrame()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel("2D 구조 모델 작성")
        title.setObjectName("setupTitle")
        hint = QLabel("문제의 노드, 부재, 지점과 하중을 캔버스에 직접 작성하세요.")
        hint.setObjectName("setupDescription")
        text.addWidget(title)
        text.addWidget(hint)
        layout.addLayout(text)
        layout.addStretch(1)
        self.solve_button = QPushButton("정정성 검사 및 해석")
        self.solve_button.setObjectName("setupContinueButton")
        self.solve_button.clicked.connect(self.solve)
        layout.addWidget(self.solve_button)
        return header

    def _build_tool_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("directModelCommandBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        select = QPushButton("선택")
        select.clicked.connect(self._activate_select_tool)
        nodes = QPushButton("노드 생성")
        nodes.clicked.connect(self._activate_node_tool)
        move_nodes = QPushButton("노드 이동/복사")
        move_nodes.clicked.connect(self._activate_node_transform_tool)
        members = QPushButton("부재 생성")
        members.clicked.connect(self._activate_member_tool)
        layout.addWidget(select)
        layout.addWidget(nodes)
        layout.addWidget(move_nodes)
        layout.addWidget(members)
        layout.addSpacing(10)
        support = QPushButton("지점")
        support.clicked.connect(self._activate_support_tool)
        load = QPushButton("하중")
        load.clicked.connect(self._activate_load_tool)
        layout.addWidget(support)
        layout.addWidget(load)
        layout.addSpacing(10)
        delete = QPushButton("선택 삭제")
        delete.clicked.connect(self.canvas.delete_selected)
        layout.addWidget(delete)
        undo = QPushButton("실행 취소")
        undo.setToolTip("Ctrl+Z")
        undo.clicked.connect(self.canvas.undo)
        layout.addWidget(undo)
        redo = QPushButton("다시 실행")
        redo.setToolTip("Ctrl+Y")
        redo.clicked.connect(self.canvas.redo)
        layout.addWidget(redo)
        select_all = QPushButton("전체 선택")
        select_all.clicked.connect(self.canvas.select_all)
        layout.addWidget(select_all)
        layout.addStretch(1)
        layout.addWidget(QLabel("선택 필터"))
        self.selection_filter = QComboBox()
        self.selection_filter.addItem("전체", "all")
        self.selection_filter.addItem("노드만", "nodes")
        self.selection_filter.addItem("부재만", "elements")
        self.selection_filter.currentIndexChanged.connect(
            lambda: setattr(self.canvas, "selection_filter", self.selection_filter.currentData())
        )
        layout.addWidget(self.selection_filter)
        layout.addWidget(QLabel("스냅"))
        self.snap = QComboBox()
        for value in (0.1, 0.25, 0.5, 1.0):
            self.snap.addItem(str(value), value)
        self.snap.setCurrentIndex(3)
        self.snap.currentIndexChanged.connect(
            lambda: setattr(self.canvas, "grid", float(self.snap.currentData()))
        )
        layout.addWidget(self.snap)
        fit = QPushButton("전체 보기")
        fit.clicked.connect(self.canvas.fit_model)
        layout.addWidget(fit)
        return bar

    def _build_tool_context(self) -> QStackedWidget:
        self.tool_context = QStackedWidget()
        self.tool_context.setObjectName("setupSummaryPanel")
        self._context_pages: dict[str, QWidget] = {}
        self._add_context("select", self._build_select_context())
        self._add_context("node", self._build_node_context())
        self._add_context("node_transform", self._build_node_transform_context())
        self._add_context("member", self._hint_context("시작 노드 클릭 → 마우스 이동 → 스냅 표시된 끝 노드 클릭"))
        self._add_context("support", self._build_support_context())
        self._add_context("load", self._build_load_context())
        self.tool_context.setFixedHeight(78)
        return self.tool_context

    def _add_context(self, key: str, page: QWidget) -> None:
        self._context_pages[key] = page
        self.tool_context.addWidget(page)

    def _hint_context(self, text: str) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(12, 8, 12, 8)
        label = QLabel(text)
        label.setObjectName("setupSummaryHint")
        layout.addWidget(label)
        layout.addStretch(1)
        return page

    def _build_select_context(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.addWidget(QLabel("드래그 선택 · Ctrl+클릭 추가 · 가운데 버튼 이동 · 휠 확대/축소"))
        layout.addStretch(1)
        layout.addWidget(QLabel("선택 노드 연결조건"))
        self.node_kind = QComboBox()
        self.node_kind.addItem("일반 노드 (강결)", False)
        self.node_kind.addItem("활절점 (회전 해제)", True)
        layout.addWidget(self.node_kind)
        apply_kind = QPushButton("연결조건 적용")
        apply_kind.clicked.connect(
            lambda: self.canvas.set_selected_node_kind(bool(self.node_kind.currentData()))
        )
        layout.addWidget(apply_kind)
        return page

    def _build_node_context(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.addWidget(QLabel("시작 좌표"))
        self.node_x = self._number(0.0)
        self.node_y = self._number(0.0)
        self.node_dx = self._number(1.0)
        self.node_dy = self._number(0.0)
        self.node_repeat = SafeSpinBox()
        self.node_repeat.setRange(1, 1000)
        for label, field in (
            ("X", self.node_x),
            ("Y", self.node_y),
            ("dX", self.node_dx),
            ("dY", self.node_dy),
            ("개수", self.node_repeat),
        ):
            layout.addWidget(QLabel(label))
            field.setMaximumWidth(90)
            layout.addWidget(field)
        add = QPushButton("노드 생성")
        add.setObjectName("setupContinueButton")
        add.clicked.connect(self._add_nodes_from_coordinates)
        layout.addWidget(add)
        midpoint = QPushButton("부재 위 노드 찍기")
        midpoint.clicked.connect(self._activate_midpoint_node_tool)
        layout.addWidget(midpoint)
        layout.addStretch(1)
        return page

    def _build_support_context(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.addWidget(QLabel("1. 노드 선택"))
        layout.addWidget(QLabel("2. 지점 종류"))
        self.support_kind = QComboBox()
        self.support_kind.addItem("핀 (Ux, Uy 구속)", (True, True, False))
        self.support_kind.addItem("Y 구속 롤러 · 수평면", (False, True, False))
        self.support_kind.addItem("X 구속 롤러 · 수직면", (True, False, False))
        self.support_kind.addItem("고정 (Ux, Uy, Rz 구속)", (True, True, True))
        self.support_kind.setMinimumWidth(210)
        layout.addWidget(self.support_kind)
        apply_button = QPushButton("3. 선택 노드에 적용")
        apply_button.setObjectName("setupContinueButton")
        apply_button.clicked.connect(
            lambda: self.canvas.apply_support_to_selection(self.support_kind.currentData())
        )
        layout.addWidget(apply_button)
        layout.addStretch(1)
        return page

    def _build_node_transform_context(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.addWidget(QLabel("1. 노드 선택"))
        layout.addWidget(QLabel("2. 작업"))
        self.node_transform_operation = QComboBox()
        self.node_transform_operation.addItem("이동", "move")
        self.node_transform_operation.addItem("복사", "copy")
        self.node_transform_operation.currentIndexChanged.connect(
            lambda: self.node_transform_repeat.setEnabled(
                self.node_transform_operation.currentData() == "copy"
            )
        )
        layout.addWidget(self.node_transform_operation)
        self.node_transform_dx = self._number(1.0)
        self.node_transform_dy = self._number(0.0)
        self.node_transform_repeat = SafeSpinBox()
        self.node_transform_repeat.setRange(1, 1000)
        self.node_transform_repeat.setEnabled(False)
        for label, field in (
            ("dX", self.node_transform_dx),
            ("dY", self.node_transform_dy),
            ("반복", self.node_transform_repeat),
        ):
            layout.addWidget(QLabel(label))
            field.setMaximumWidth(90)
            layout.addWidget(field)
        apply_button = QPushButton("3. 적용")
        apply_button.setObjectName("setupContinueButton")
        apply_button.clicked.connect(self._apply_node_transform)
        layout.addWidget(apply_button)
        layout.addStretch(1)
        return page

    def _build_load_context(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.addWidget(QLabel("1. 대상"))
        self.load_target = QComboBox()
        self.load_target.addItem("노드", "node")
        self.load_target.addItem("부재", "element")
        self.load_target.currentIndexChanged.connect(self._load_target_changed)
        layout.addWidget(self.load_target)
        layout.addWidget(QLabel("2. 방향"))
        self.load_direction = QComboBox()
        self.load_direction.setMinimumWidth(145)
        self.load_direction.currentIndexChanged.connect(self._update_load_unit)
        layout.addWidget(self.load_direction)
        layout.addWidget(QLabel("3. 크기"))
        self.load_magnitude = self._number(10.0)
        self.load_magnitude.setRange(0.0, 1_000_000.0)
        self.load_magnitude.setMaximumWidth(110)
        layout.addWidget(self.load_magnitude)
        self.load_unit = QLabel()
        layout.addWidget(self.load_unit)
        apply_button = QPushButton("4. 선택 대상에 적용")
        apply_button.setObjectName("setupContinueButton")
        apply_button.clicked.connect(self._apply_directional_load)
        layout.addWidget(apply_button)
        layout.addStretch(1)
        self._load_target_changed()
        return page

    def _build_modeling_workspace(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        canvas_panel = QFrame()
        canvas_panel.setObjectName("setupSummaryPanel")
        canvas_layout = QVBoxLayout(canvas_panel)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.mode_label = QLabel()
        self.mode_label.setContentsMargins(10, 6, 10, 6)
        self.mode_label.setObjectName("setupSummaryHint")
        canvas_layout.addWidget(self.mode_label)
        canvas_layout.addWidget(self.canvas, 1)
        layout.addWidget(canvas_panel, 1)
        return page

    def _build_inspector(self) -> QScrollArea:
        panel = QFrame()
        panel.setObjectName("setupFormPanel")
        root = QVBoxLayout(panel)
        root.setContentsMargins(14, 13, 14, 13)
        root.setSpacing(10)
        title = QLabel("모델 입력 및 속성")
        title.setObjectName("setupSectionTitle")
        root.addWidget(title)

        root.addWidget(self._section("절점 좌표 입력"))
        coordinates = QFormLayout()
        self.node_x = self._number(0.0)
        self.node_y = self._number(0.0)
        self.node_dx = self._number(1.0)
        self.node_dy = self._number(0.0)
        self.node_repeat = QSpinBox()
        self.node_repeat.setRange(1, 1000)
        coordinates.addRow("X", self.node_x)
        coordinates.addRow("Y", self.node_y)
        coordinates.addRow("증분 dX", self.node_dx)
        coordinates.addRow("증분 dY", self.node_dy)
        coordinates.addRow("생성 개수", self.node_repeat)
        root.addLayout(coordinates)
        add_node = QPushButton("좌표로 절점 추가")
        add_node.clicked.connect(self._add_nodes_from_coordinates)
        root.addWidget(add_node)

        root.addWidget(self._section("절점 유형"))
        self.node_kind = QComboBox()
        self.node_kind.addItem("일반 절점", False)
        self.node_kind.addItem("활절점 (내부 힌지)", True)
        root.addWidget(self.node_kind)
        apply_node_kind = QPushButton("선택 절점에 유형 적용")
        apply_node_kind.clicked.connect(
            lambda: self.canvas.set_selected_node_kind(bool(self.node_kind.currentData()))
        )
        root.addWidget(apply_node_kind)

        root.addWidget(self._section("지점 조건"))
        self.support_kind = QComboBox()
        self.support_kind.addItem("핀 지점", (True, True, False))
        self.support_kind.addItem("수직 롤러", (False, True, False))
        self.support_kind.addItem("수평 롤러", (True, False, False))
        self.support_kind.addItem("고정 지점", (True, True, True))
        root.addWidget(self.support_kind)
        apply_support = QPushButton("선택 절점에 지점 적용")
        apply_support.clicked.connect(
            lambda: self.canvas.apply_support_to_selection(self.support_kind.currentData())
        )
        root.addWidget(apply_support)
        support_hint = QLabel("캔버스에서 클릭 또는 드래그로 절점을 선택한 뒤 적용합니다.")
        support_hint.setWordWrap(True)
        support_hint.setObjectName("setupSectionHint")
        root.addWidget(support_hint)

        root.addWidget(self._section("절점하중"))
        nodal_form = QFormLayout()
        self.fx = self._number(0.0)
        self.fy = self._number(-10.0)
        self.mz = self._number(0.0)
        nodal_form.addRow("Fx", self.fx)
        nodal_form.addRow("Fy", self.fy)
        nodal_form.addRow("Mz", self.mz)
        root.addLayout(nodal_form)
        apply_nodal = QPushButton("선택 절점에 하중 적용")
        apply_nodal.clicked.connect(self._apply_nodal_load)
        root.addWidget(apply_nodal)

        root.addWidget(self._section("부재 분포하중 (로컬축)"))
        element_form = QFormLayout()
        self.qx = self._number(0.0)
        self.qy = self._number(-10.0)
        element_form.addRow("qx", self.qx)
        element_form.addRow("qy", self.qy)
        root.addLayout(element_form)
        apply_uniform = QPushButton("선택 부재에 하중 적용")
        apply_uniform.clicked.connect(self._apply_uniform_load)
        root.addWidget(apply_uniform)
        root.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("modelingInspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(320)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _build_result_workspace(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        back = QPushButton("모델 편집으로 돌아가기")
        back.clicked.connect(lambda: self.workspace_stack.setCurrentIndex(0))
        tools.addWidget(back)
        for label, kind in (
            ("반력", "reaction"),
            ("축력도 N", "axial"),
            ("전단력도 V", "shear"),
            ("모멘트도 M", "moment"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked=False, value=kind: self.viewport.set_result_type(value)
            )
            tools.addWidget(button)
        tools.addStretch(1)
        layout.addLayout(tools)
        self.viewport = ResultViewport()
        layout.addWidget(self.viewport, 1)
        return page

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("directModelCommandBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        self.model_status = QLabel()
        self.determinacy_status = QLabel("정정성: 모델 작성 중")
        self.unit_status = QLabel()
        layout.addWidget(self.model_status)
        layout.addStretch(1)
        layout.addWidget(self.determinacy_status)
        layout.addSpacing(16)
        layout.addWidget(self.unit_status)
        return bar

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self.viewport.set_unit_system(unit_system)
        self.unit_status.setText(f"단위: {unit_system.force}, {unit_system.length}")
        self._update_load_unit()

    def solve(self) -> None:
        model = self.canvas.build_model()
        check = check_determinacy(model)
        self.determinacy_status.setText(f"정정성: {check.message}")
        result = self._solver.solve(model)
        if result.status.value != "completed":
            return
        self.viewport.set_model(model)
        self.viewport.show_result(result)
        self.viewport.set_result_type("reaction")
        self.workspace_stack.setCurrentIndex(1)

    def _set_mode(self, mode: str, description: str) -> None:
        self.canvas.set_mode(mode)
        self.mode_label.setText(f"현재 도구: {description}")

    def _show_context(self, key: str) -> None:
        self.tool_context.setCurrentWidget(self._context_pages[key])

    def _activate_select_tool(self) -> None:
        self._show_context("select")
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("all"))
        self._set_mode("select", "대상을 클릭하거나 드래그하여 선택합니다.")

    def _activate_node_tool(self) -> None:
        self._show_context("node")
        self._set_mode("select", "좌표와 증분을 입력한 뒤 노드 생성 버튼을 누릅니다.")

    def _activate_member_tool(self) -> None:
        self._show_context("member")
        self._set_mode("member", "시작 노드에서 끝 노드까지 스냅 연결합니다.")

    def _activate_midpoint_node_tool(self) -> None:
        self._show_context("node")
        self._set_mode(
            "member_midpoint",
            "부재 위 임의 위치를 클릭합니다. 중앙 근처에서는 MID로 자동 스냅됩니다.",
        )

    def _activate_node_transform_tool(self) -> None:
        self._show_context("node_transform")
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("nodes"))
        self._set_mode("select", "이동하거나 복사할 노드를 클릭 또는 드래그 선택합니다.")

    def _activate_support_tool(self) -> None:
        self._show_context("support")
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("nodes"))
        self._set_mode("select", "노드를 선택하고 같은 줄의 지점 적용 버튼을 누릅니다.")

    def _activate_load_tool(self) -> None:
        self._show_context("load")
        self._load_target_changed()
        self._set_mode("select", "대상, 방향과 크기를 정한 뒤 같은 줄에서 적용합니다.")

    def _load_target_changed(self) -> None:
        if not hasattr(self, "load_direction"):
            return
        self.load_direction.clear()
        if self.load_target.currentData() == "node":
            directions = (
                ("+X (오른쪽)", ("fx", 1.0)),
                ("-X (왼쪽)", ("fx", -1.0)),
                ("+Y (위쪽)", ("fy", 1.0)),
                ("-Y (아래쪽)", ("fy", -1.0)),
                ("+Mz (반시계)", ("mz", 1.0)),
                ("-Mz (시계)", ("mz", -1.0)),
            )
            filter_key = "nodes"
        else:
            directions = (
                ("로컬 +x", ("qx", 1.0)),
                ("로컬 -x", ("qx", -1.0)),
                ("로컬 +y", ("qy", 1.0)),
                ("로컬 -y", ("qy", -1.0)),
            )
            filter_key = "elements"
        for label, value in directions:
            self.load_direction.addItem(label, value)
        if hasattr(self, "selection_filter"):
            self.selection_filter.setCurrentIndex(self.selection_filter.findData(filter_key))
        self._update_load_unit()

    def _update_load_unit(self) -> None:
        if not hasattr(self, "load_unit"):
            return
        unit = self._unit_system.force
        if self.load_target.currentData() == "element":
            unit = f"{unit}/{self._unit_system.length}"
        elif self.load_direction.currentData() and self.load_direction.currentData()[0] == "mz":
            unit = self._unit_system.moment
        self.load_unit.setText(unit)

    def _apply_directional_load(self) -> None:
        component, sign = self.load_direction.currentData()
        value = self.load_magnitude.value() * sign
        if self.load_target.currentData() == "node":
            values = {
                "fx": (value, 0.0, 0.0),
                "fy": (0.0, value, 0.0),
                "mz": (0.0, 0.0, value),
            }[component]
            self.canvas.apply_nodal_load_to_selection(values)
        else:
            values = (value, 0.0) if component == "qx" else (0.0, value)
            self.canvas.apply_uniform_load_to_selection(values)

    def _support_mode(self) -> None:
        self._set_mode("select", "지점을 적용할 절점을 클릭하거나 드래그 선택합니다.")

    def _nodal_load_mode(self) -> None:
        self._set_mode("select", "하중을 적용할 절점을 클릭하거나 드래그 선택합니다.")

    def _uniform_load_mode(self) -> None:
        self._set_mode("select", "분포하중을 적용할 부재를 클릭하거나 드래그 선택합니다.")

    def _add_nodes_from_coordinates(self) -> None:
        x = self.node_x.value()
        y = self.node_y.value()
        self.canvas.begin_history_group()
        try:
            for index in range(self.node_repeat.value()):
                self.canvas.add_node(
                    x + self.node_dx.value() * index,
                    y + self.node_dy.value() * index,
                )
        finally:
            self.canvas.end_history_group()

    def _apply_node_transform(self) -> None:
        self.canvas.transform_selected_nodes(
            self.node_transform_operation.currentData(),
            self.node_transform_dx.value(),
            self.node_transform_dy.value(),
            self.node_transform_repeat.value(),
        )

    def _apply_nodal_load(self) -> None:
        self.canvas.apply_nodal_load_to_selection(
            (self.fx.value(), self.fy.value(), self.mz.value())
        )

    def _apply_uniform_load(self) -> None:
        self.canvas.apply_uniform_load_to_selection((self.qx.value(), self.qy.value()))

    def _refresh_status(self) -> None:
        model = self.canvas.build_model()
        load_count = len(model.nodal_loads) + len(model.element_loads)
        self.model_status.setText(
            f"노드 {len(model.nodes)}  |  부재 {len(model.elements)}  |  "
            f"지점 {len(model.boundaries)}  |  하중 {load_count}"
        )
        check = check_determinacy(model)
        self.determinacy_status.setText(f"정정성: {check.message}")

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("setupSectionTitle")
        return label

    @staticmethod
    def _number(value: float) -> QDoubleSpinBox:
        field = SafeDoubleSpinBox()
        field.setRange(-1_000_000.0, 1_000_000.0)
        field.setDecimals(4)
        field.setValue(value)
        return field
