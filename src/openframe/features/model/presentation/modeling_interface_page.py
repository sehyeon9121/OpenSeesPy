"""Free-form authoring surface for 2D structural-mechanics models.

The layout keeps the canvas dominant: a narrow tool rail on the left, a coordinate
entry strip under the canvas, and a property panel on the right that follows the
selection.  Only selecting and drawing are tools; everything else — supports,
hinges, loads — is a property of whatever is selected, so adding a new kind of
object never adds another button to learn.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, UnitSystem
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy
from openframe.features.model.drawing import PlaneKind
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
from openframe.features.results.presentation.results_workspace import ResultsWorkspace
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport


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
        self._pinned_section: str | None = None
        self.canvas = StaticsDrawingCanvas()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 10)
        root.setSpacing(8)
        root.addWidget(self._build_header())

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(self._build_modeling_workspace())
        self.workspace_stack.addWidget(self._build_result_workspace())
        root.addWidget(self.workspace_stack, 1)
        root.addWidget(self._build_status_bar())

        self.canvas.model_changed.connect(self._refresh_status)
        self.canvas.draw_state_changed.connect(self._refresh_draw_readout)
        self.canvas.selection_changed.connect(self._selection_changed)
        for standard, slot in (
            (QKeySequence.StandardKey.Delete, self.canvas.delete_selected),
            (QKeySequence.StandardKey.Undo, self.canvas.undo),
            (QKeySequence.StandardKey.Redo, self.canvas.redo),
        ):
            shortcut = QShortcut(standard, self.canvas)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        self.select_shortcut = QShortcut(QKeySequence("V"), self.canvas)
        self.select_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.select_shortcut.activated.connect(self._activate_select_tool)
        self.draw_shortcut = QShortcut(QKeySequence("L"), self.canvas)
        self.draw_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.draw_shortcut.activated.connect(self._activate_draw_tool)

        self._activate_select_tool()
        self._refresh_status()

    # --- layout ------------------------------------------------------------

    def _build_header(self) -> QFrame:
        header = QFrame()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel("2D 구조 모델 작성")
        title.setObjectName("setupTitle")
        hint = QLabel("절점, 부재, 지점과 하중을 캔버스에 직접 작성하세요.")
        hint.setObjectName("setupDescription")
        text.addWidget(title)
        text.addWidget(hint)
        layout.addLayout(text)
        layout.addStretch(1)
        self.mode_3d_toggle = QPushButton("3D 모드")
        self.mode_3d_toggle.setCheckable(True)
        self.mode_3d_toggle.setToolTip(
            "평면(작업평면)을 오가며 여러 층을 그리고, 기둥으로 연결합니다."
        )
        self.mode_3d_toggle.toggled.connect(self._toggle_3d_mode)
        layout.addWidget(self.mode_3d_toggle)
        self.solve_button = QPushButton("정정성 검사 및 해석")
        self.solve_button.setObjectName("setupContinueButton")
        self.solve_button.clicked.connect(self.solve)
        layout.addWidget(self.solve_button)
        return header

    def _build_modeling_workspace(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_tool_rail())
        layout.addWidget(self._build_canvas_panel(), 1)
        layout.addWidget(self._build_property_panel())
        return page

    def _build_tool_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("directModelCommandBar")
        rail.setFixedWidth(76)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.select_tool = self._rail_tool("선택", "V", self._activate_select_tool)
        self.draw_tool = self._rail_tool("그리기", "L", self._activate_draw_tool)
        layout.addWidget(self.select_tool)
        layout.addWidget(self.draw_tool)
        layout.addSpacing(10)
        for text, tooltip, slot in (
            ("실행 취소", "Ctrl+Z", self.canvas.undo),
            ("다시 실행", "Ctrl+Y", self.canvas.redo),
            ("삭제", "Delete", self.canvas.delete_selected),
            ("전체 선택", "선택 필터에 따릅니다", self.canvas.select_all),
            ("전체 보기", "모델 전체가 보이도록 맞춥니다", self.canvas.fit_model),
        ):
            button = QPushButton(text)
            button.setObjectName("railCommandButton")
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            layout.addWidget(button)
        layout.addStretch(1)
        return rail

    def _rail_tool(self, text: str, shortcut: str, slot) -> QPushButton:
        """A tool (select/draw) — visually distinct from the command buttons below
        it, since only these two govern what a click on the canvas does."""
        button = QPushButton(text)
        button.setObjectName("railToolButton")
        button.setCheckable(True)
        button.setToolTip(f"{text} ({shortcut})")
        button.clicked.connect(slot)
        self.tool_group.addButton(button)
        return button

    def _build_canvas_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("setupSummaryPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.mode_label = QLabel()
        self.mode_label.setContentsMargins(10, 6, 10, 6)
        self.mode_label.setObjectName("setupSummaryHint")
        layout.addWidget(self.mode_label)
        layout.addWidget(self._build_level_bar())

        self.canvas_splitter = QSplitter(Qt.Orientation.Vertical)
        self.canvas_splitter.setChildrenCollapsible(False)
        self.canvas_splitter.addWidget(self.canvas)
        self.preview_3d = Quick3DViewport()
        self.preview_3d.setMinimumHeight(160)
        self.preview_3d.setVisible(False)
        self.canvas_splitter.addWidget(self.preview_3d)
        self.canvas_splitter.setStretchFactor(0, 3)
        self.canvas_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.canvas_splitter, 1)

        layout.addWidget(self._build_entry_bar())
        return panel

    def _build_level_bar(self) -> QFrame:
        """Work-plane controls: draw a floor plan, add a level, connect a column.

        Hidden until 3D mode is turned on — a 2D canvas needs none of this, and a
        control the user never asked for is worse than no control at all.
        """
        bar = QFrame()
        bar.setObjectName("directModelCommandBar")
        self.level_bar = bar
        bar.setVisible(False)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        layout.addWidget(QLabel("현재 작업평면"))
        self.plane_selector = QComboBox()
        self.plane_selector.setMinimumWidth(120)
        self.plane_selector.currentIndexChanged.connect(self._change_active_plane)
        layout.addWidget(self.plane_selector)
        layout.addSpacing(10)
        layout.addWidget(QLabel("새 평면"))
        self.new_plane_kind = QComboBox()
        self.new_plane_kind.addItem("평면도 (XY)", PlaneKind.XY)
        self.new_plane_kind.addItem("정면도 (XZ)", PlaneKind.XZ)
        self.new_plane_kind.addItem("측면도 (YZ)", PlaneKind.YZ)
        layout.addWidget(self.new_plane_kind)
        self.new_plane_offset = self._number(3.0)
        self.new_plane_offset.setToolTip("평면도는 Z 높이, 정면도는 Y, 측면도는 X 위치입니다.")
        layout.addWidget(self.new_plane_offset)
        self.new_plane_label = QLineEdit()
        self.new_plane_label.setPlaceholderText("이름 (예: 2F)")
        self.new_plane_label.setMaximumWidth(90)
        layout.addWidget(self.new_plane_label)
        add_plane = QPushButton("평면 추가")
        add_plane.clicked.connect(self._add_plane)
        layout.addWidget(add_plane)
        layout.addStretch(1)
        layout.addWidget(QLabel("선택 절점을"))
        self.column_target = QComboBox()
        self.column_target.setMinimumWidth(120)
        layout.addWidget(self.column_target)
        connect_button = QPushButton("기둥으로 연결")
        connect_button.setToolTip("선택한 절점을 다른 평면의 같은 위치와 부재로 잇습니다.")
        connect_button.clicked.connect(self._extrude_to_target_plane)
        layout.addWidget(connect_button)
        return bar

    def _build_entry_bar(self) -> QFrame:
        """The measurement strip under the canvas: type what you cannot click."""
        bar = QFrame()
        bar.setObjectName("directModelCommandBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        layout.addWidget(QLabel("그리드"))
        self.snap = QComboBox()
        for value in (0.1, 0.25, 0.5, 1.0):
            self.snap.addItem(f"{value:g} m", value)
        self.snap.setCurrentIndex(3)
        self.snap.currentIndexChanged.connect(
            lambda: setattr(self.canvas, "grid", float(self.snap.currentData()))
        )
        layout.addWidget(self.snap)
        layout.addWidget(QLabel("선택 필터"))
        self.selection_filter = QComboBox()
        self.selection_filter.addItem("전체", "all")
        self.selection_filter.addItem("절점만", "nodes")
        self.selection_filter.addItem("부재만", "elements")
        self.selection_filter.currentIndexChanged.connect(
            lambda: setattr(
                self.canvas, "selection_filter", self.selection_filter.currentData()
            )
        )
        layout.addWidget(self.selection_filter)
        self.ortho_lock = QCheckBox("직교 고정")
        self.ortho_lock.setToolTip("Shift를 누르고 있어도 같게 동작합니다.")
        self.ortho_lock.toggled.connect(
            lambda checked: setattr(self.canvas, "ortho", bool(checked))
        )
        layout.addWidget(self.ortho_lock)
        self.ortho_increment = QComboBox()
        for value in (90.0, 45.0, 30.0, 15.0):
            self.ortho_increment.addItem(f"{value:g}°", value)
        self.ortho_increment.setCurrentIndex(1)
        self.ortho_increment.currentIndexChanged.connect(
            lambda: setattr(
                self.canvas, "ortho_increment", float(self.ortho_increment.currentData())
            )
        )
        layout.addWidget(self.ortho_increment)
        layout.addStretch(1)
        self.draw_readout = QLabel()
        self.draw_readout.setObjectName("setupSummaryHint")
        layout.addWidget(self.draw_readout)
        self.draw_entry = QLineEdit()
        self.draw_entry.setPlaceholderText("5<30 · @3,4 · 3,4 · 5")
        self.draw_entry.setToolTip(
            "길이<각도 · @상대좌표 · 절대좌표 · 길이만 입력하면 현재 커서 방향"
        )
        self.draw_entry.setFixedWidth(200)
        self.draw_entry.returnPressed.connect(self._commit_draw_entry)
        layout.addWidget(self.draw_entry)
        end_chain = QPushButton("연결 끊기")
        end_chain.setToolTip("Esc")
        end_chain.clicked.connect(self.canvas.end_chain)
        layout.addWidget(end_chain)
        return bar

    def _build_property_panel(self) -> QScrollArea:
        panel = QFrame()
        panel.setObjectName("setupFormPanel")
        root = QVBoxLayout(panel)
        root.setContentsMargins(14, 13, 14, 13)
        root.setSpacing(10)
        self.selection_summary = QLabel()
        self.selection_summary.setObjectName("setupSectionTitle")
        self.selection_summary.setWordWrap(True)
        root.addWidget(self.selection_summary)
        self._sections: dict[str, QWidget] = {}
        for key, section in (
            ("create", self._build_create_section()),
            ("node", self._build_node_section()),
            ("transform", self._build_transform_section()),
            ("member", self._build_member_section()),
            ("load", self._build_load_section()),
        ):
            self._sections[key] = section
            root.addWidget(section)
        root.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("modelingInspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(300)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _build_create_section(self) -> QWidget:
        section, root = self._section("좌표로 절점 추가")
        form = QFormLayout()
        self.node_x = self._number(0.0)
        self.node_y = self._number(0.0)
        self.node_dx = self._number(1.0)
        self.node_dy = self._number(0.0)
        self.node_repeat = SafeSpinBox()
        self.node_repeat.setRange(1, 1000)
        form.addRow("X", self.node_x)
        form.addRow("Y", self.node_y)
        form.addRow("증분 dX", self.node_dx)
        form.addRow("증분 dY", self.node_dy)
        form.addRow("생성 개수", self.node_repeat)
        root.addLayout(form)
        add = QPushButton("절점 추가")
        add.clicked.connect(self._add_nodes_from_coordinates)
        root.addWidget(add)
        hint = QLabel("연속으로 그리려면 왼쪽 레일의 그리기 도구를 쓰세요.")
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)
        return section

    def _build_node_section(self) -> QWidget:
        section, root = self._section("절점 속성")
        root.addWidget(QLabel("지점 조건"))
        self.support_kind = QComboBox()
        self.support_kind.addItem("자유 (지점 없음)", (False, False, False))
        self.support_kind.addItem("핀 지점", (True, True, False))
        self.support_kind.addItem("수직 롤러", (False, True, False))
        self.support_kind.addItem("수평 롤러", (True, False, False))
        self.support_kind.addItem("고정 지점", (True, True, True))
        self.support_kind.setCurrentIndex(1)
        root.addWidget(self.support_kind)
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("경사각(°)"))
        self.support_angle = self._number(0.0)
        self.support_angle.setRange(-360.0, 360.0)
        self.support_angle.setDecimals(2)
        self.support_angle.setToolTip(
            "지지면이 수평에서 반시계 방향으로 기울어진 각도. 0이면 보통의 수평·수직 지점입니다."
        )
        angle_row.addWidget(self.support_angle, 1)
        root.addLayout(angle_row)
        apply_support = QPushButton("선택 절점에 적용")
        apply_support.clicked.connect(
            lambda: self.canvas.apply_support_to_selection(
                self.support_kind.currentData(), self.support_angle.value()
            )
        )
        root.addWidget(apply_support)
        root.addWidget(QLabel("절점 유형"))
        self.node_kind = QComboBox()
        self.node_kind.addItem("일반 절점 (강결)", False)
        self.node_kind.addItem("활절점 (내부 힌지)", True)
        root.addWidget(self.node_kind)
        apply_kind = QPushButton("선택 절점에 적용")
        apply_kind.clicked.connect(
            lambda: self.canvas.set_selected_node_kind(bool(self.node_kind.currentData()))
        )
        root.addWidget(apply_kind)
        self.transform_toggle = QPushButton("이동 · 복사 · 배열 ▸")
        self.transform_toggle.setObjectName("sectionToggleButton")
        self.transform_toggle.clicked.connect(self._toggle_transform_section)
        root.addWidget(self.transform_toggle)
        return section

    def _toggle_transform_section(self) -> None:
        self._pinned_section = None if self._pinned_section == "transform" else "transform"
        self._sync_property_panel()

    def _build_transform_section(self) -> QWidget:
        """Move, copy, array-copy and mirror — every operation that turns a hand-
        drawn fragment into a repeated or symmetric shape without redrawing it.
        Collapsed by default (see ``_sync_property_panel``); the toggle button in
        the node section above opens it back up.
        """
        section, root = self._section("절점 이동 · 복사 · 배열")
        self.node_transform_operation = QComboBox()
        self.node_transform_operation.addItem("이동", "move")
        self.node_transform_operation.addItem("복사", "copy")
        self.node_transform_operation.addItem("배열 복사 (부재 포함)", "array")
        self.node_transform_operation.currentIndexChanged.connect(
            lambda: self.node_transform_repeat.setEnabled(
                self.node_transform_operation.currentData() in {"copy", "array"}
            )
        )
        root.addWidget(self.node_transform_operation)
        form = QFormLayout()
        self.node_transform_dx = self._number(1.0)
        self.node_transform_dy = self._number(0.0)
        self.node_transform_repeat = SafeSpinBox()
        self.node_transform_repeat.setRange(1, 1000)
        self.node_transform_repeat.setEnabled(False)
        form.addRow("dX", self.node_transform_dx)
        form.addRow("dY", self.node_transform_dy)
        form.addRow("반복/배열 개수", self.node_transform_repeat)
        root.addLayout(form)
        apply_button = QPushButton("선택 절점에 적용")
        apply_button.clicked.connect(self._apply_node_transform)
        root.addWidget(apply_button)

        mirror_hint = QLabel("대칭 복사 — 절반만 그린 뒤 축을 기준으로 나머지를 만듭니다.")
        mirror_hint.setWordWrap(True)
        mirror_hint.setObjectName("setupSectionHint")
        root.addWidget(mirror_hint)
        mirror_row = QHBoxLayout()
        self.mirror_axis = QComboBox()
        self.mirror_axis.addItem("수직선 X =", "x")
        self.mirror_axis.addItem("수평선 Y =", "y")
        mirror_row.addWidget(self.mirror_axis)
        self.mirror_value = self._number(0.0)
        mirror_row.addWidget(self.mirror_value, 1)
        root.addLayout(mirror_row)
        mirror_button = QPushButton("선택 절점 대칭 복사")
        mirror_button.clicked.connect(self._apply_mirror)
        root.addWidget(mirror_button)
        return section

    def _build_member_section(self) -> QWidget:
        """Per-end pin release and mid-span node insertion for one selected member.

        A member always has two ends regardless of which node tags they land on, so
        the checkboxes are labelled with the actual node numbers when the selection
        changes rather than fixed "start/end" text.
        """
        section, root = self._section("부재 속성")
        self.member_end_i = QCheckBox("i단 핀 해제 (모멘트 0)")
        self.member_end_i.toggled.connect(
            lambda checked: self._apply_member_end_release("i", checked)
        )
        root.addWidget(self.member_end_i)
        self.member_end_j = QCheckBox("j단 핀 해제 (모멘트 0)")
        self.member_end_j.toggled.connect(
            lambda checked: self._apply_member_end_release("j", checked)
        )
        root.addWidget(self.member_end_j)
        root.addWidget(QLabel("부재 위 절점 삽입 (x/L)"))
        insert_row = QHBoxLayout()
        self.member_station = self._number(0.5)
        self.member_station.setRange(0.01, 0.99)
        self.member_station.setSingleStep(0.05)
        insert_row.addWidget(self.member_station, 1)
        insert_button = QPushButton("삽입")
        insert_button.clicked.connect(self._insert_member_station_node)
        insert_row.addWidget(insert_button)
        root.addLayout(insert_row)
        hint = QLabel("지점을 임의 위치에 두려면 여기서 절점을 삽입한 뒤 왼쪽에서 선택하세요.")
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)
        root.addWidget(QLabel("부재 등분할"))
        subdivide_row = QHBoxLayout()
        self.member_segments = SafeSpinBox()
        self.member_segments.setRange(2, 20)
        self.member_segments.setValue(2)
        subdivide_row.addWidget(self.member_segments, 1)
        subdivide_button = QPushButton("등분할")
        subdivide_button.setToolTip("트러스 패널이나 격자보처럼 일정 간격 절점이 필요할 때 씁니다.")
        subdivide_button.clicked.connect(self._subdivide_member)
        subdivide_row.addWidget(subdivide_button)
        root.addLayout(subdivide_row)
        return section

    def _build_load_section(self) -> QWidget:
        section, root = self._section("하중")
        self.load_target = QComboBox()
        self.load_target.addItem("절점", "node")
        self.load_target.addItem("부재", "element")
        self.load_target.currentIndexChanged.connect(self._load_target_changed)
        root.addWidget(self.load_target)
        self.load_direction = QComboBox()
        self.load_direction.currentIndexChanged.connect(self._update_load_unit)
        root.addWidget(self.load_direction)
        magnitude = QHBoxLayout()
        self.load_magnitude = self._number(10.0)
        self.load_magnitude.setRange(0.0, 1_000_000.0)
        magnitude.addWidget(self.load_magnitude, 1)
        self.load_unit = QLabel()
        magnitude.addWidget(self.load_unit)
        root.addLayout(magnitude)
        apply_button = QPushButton("선택 대상에 적용")
        apply_button.clicked.connect(self._apply_directional_load)
        root.addWidget(apply_button)
        self._load_target_changed()
        return section

    def _build_result_workspace(self) -> QWidget:
        """The full post-processing workspace, not a bare viewport.

        Reactions, nodal displacements and the N/V/M diagrams all need a table beside
        the picture; the reusable workspace already carries one.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        tools = QHBoxLayout()
        back = QPushButton("모델 편집으로 돌아가기")
        back.clicked.connect(lambda: self.workspace_stack.setCurrentIndex(0))
        tools.addWidget(back)
        for label, kind in (
            ("지점 반력", "reaction"),
            ("변형 형상", "deformation"),
            ("절점 변위", "displacement"),
            ("축력도 N", "axial"),
            ("전단력도 V", "shear"),
            ("모멘트도 M", "moment"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked=False, value=kind: self.results.set_result_type(value)
            )
            tools.addWidget(button)
        tools.addStretch(1)
        layout.addLayout(tools)
        self.results = ResultsWorkspace()
        self.viewport = self.results.viewport
        layout.addWidget(self.results, 1)
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

    # --- behaviour ---------------------------------------------------------

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self.results.set_unit_system(unit_system)
        self.unit_status.setText(f"단위: {unit_system.force}, {unit_system.length}")
        self._update_load_unit()

    def solve(self) -> None:
        model = self.canvas.build_model()
        check = check_determinacy(model)
        self.determinacy_status.setText(f"정정성: {check.message}")
        result = self._solver.solve(model)
        if result.status.value != "completed":
            self.determinacy_status.setText(
                f"정정성: {check.message}  ·  {' '.join(result.messages)}"
            )
            return
        self.results.set_model(model)
        self.results.show_result(result)
        self.results.set_result_type("reaction")
        self.workspace_stack.setCurrentIndex(1)

    def _toggle_3d_mode(self, checked: bool) -> None:
        """Switch between a flat 2D sheet and a stack of work planes.

        Turning 3D on is one-way for the session: the canvas already carries
        model coordinates in three dimensions the moment it is drawn (a 2D canvas
        is just the special case where every z is 0), so nothing is lost by
        entering 3D mode with an empty or already-drawn model — turning it back
        off would only hide, not undo, anything already placed off the ground plane.
        """
        if checked:
            self.canvas.enter_3d_mode()
            self.canvas.model_changed.connect(self._refresh_3d_preview)
            self._refresh_plane_selectors()
            self._refresh_3d_preview()
            self._load_target_changed()
        self.level_bar.setVisible(checked)
        self.preview_3d.setVisible(checked)

    def _refresh_plane_selectors(self) -> None:
        for combo in (self.plane_selector, self.column_target):
            combo.blockSignals(True)
            combo.clear()
            for plane in self.canvas.levels:
                combo.addItem(f"{plane.label} ({plane.kind})", plane)
            combo.blockSignals(False)
        # QComboBox.findData() compares composite Python objects (a WorkPlane, here)
        # by identity under the hood, not by value — a freshly-built-but-equal
        # WorkPlane would silently fail to match. Iterating and comparing with
        # Python's own `==` is the reliable way to do this lookup.
        for index in range(self.plane_selector.count()):
            if self.plane_selector.itemData(index) == self.canvas.work_plane:
                self.plane_selector.setCurrentIndex(index)
                break

    def _change_active_plane(self) -> None:
        plane = self.plane_selector.currentData()
        if plane is not None:
            self.canvas.set_active_plane(plane)
            self._refresh_status()

    def _add_plane(self) -> None:
        label = self.new_plane_label.text().strip() or f"평면 {len(self.canvas.levels) + 1}"
        plane = self.canvas.add_level(
            self.new_plane_offset.value(), label, self.new_plane_kind.currentData()
        )
        self._refresh_plane_selectors()
        self.canvas.set_active_plane(plane)
        self._refresh_plane_selectors()
        self.new_plane_label.clear()

    def _extrude_to_target_plane(self) -> None:
        target = self.column_target.currentData()
        if target is not None:
            self.canvas.extrude_selection_to_plane(target)

    def _refresh_3d_preview(self) -> None:
        if self.mode_3d_toggle.isChecked():
            self.preview_3d.set_model(self.canvas.build_model())

    def _set_mode(self, mode: str, description: str) -> None:
        self.canvas.set_mode(mode)
        self.mode_label.setText(description)

    def _activate_select_tool(self) -> None:
        self.select_tool.setChecked(True)
        self._pinned_section = None
        self._set_mode(
            "select",
            "선택 · 클릭 또는 드래그로 선택하고 오른쪽 패널에서 속성을 적용합니다.",
        )
        self._sync_property_panel()

    def _activate_draw_tool(self) -> None:
        self.draw_tool.setChecked(True)
        self._pinned_section = None
        self._set_mode(
            "draw",
            "그리기 · 연속 클릭으로 절점과 부재를 함께 만듭니다. "
            "아래 입력칸에 길이·각도를 쳐도 됩니다. Esc로 연결을 끊습니다.",
        )
        self.draw_entry.setFocus()
        self._sync_property_panel()
        self._refresh_draw_readout()

    def _activate_node_transform_tool(self) -> None:
        self._pin_section("transform", "nodes")

    def _activate_support_tool(self) -> None:
        self._pin_section("node", "nodes")

    def _activate_load_tool(self) -> None:
        self._load_target_changed()
        self._pin_section("load", None)

    def _pin_section(self, key: str, selection_filter: str | None) -> None:
        """Keep one property section open while the user builds up a selection."""
        self.select_tool.setChecked(True)
        self._set_mode("select", "대상을 선택한 뒤 오른쪽 패널에서 적용하세요.")
        if selection_filter is not None:
            self.selection_filter.setCurrentIndex(
                self.selection_filter.findData(selection_filter)
            )
        self._pinned_section = key
        self._sync_property_panel()

    def _selection_changed(self) -> None:
        self._pinned_section = None
        self._sync_property_panel()

    def _selected_member_tag(self) -> int | None:
        if self.canvas.selected_nodes or len(self.canvas.selected_elements) != 1:
            return None
        return next(iter(self.canvas.selected_elements))

    def _sync_property_panel(self) -> None:
        """Show only the sections that apply to what is selected right now."""
        nodes = len(self.canvas.selected_nodes)
        elements = len(self.canvas.selected_elements)
        member_tag = self._selected_member_tag()
        pinned = self._pinned_section
        visible = {
            "create": not nodes and not elements,
            "node": bool(nodes),
            # Collapsed by default — move/copy/array/mirror is a wide block and most
            # selections only need a support or a load, not a geometry operation.
            # The toggle button inside the node section (or the rail's pin path)
            # opens it back up.
            "transform": False,
            "member": member_tag is not None,
            "load": bool(nodes or elements),
        }
        if pinned is not None:
            visible[pinned] = True
        for key, section in self._sections.items():
            section.setVisible(visible[key])
        self.transform_toggle.setText(
            "이동 · 복사 · 배열 감추기 ▾" if visible["transform"] else "이동 · 복사 · 배열 ▸"
        )
        if member_tag is not None:
            self._refresh_member_section(member_tag)
        if nodes and elements:
            summary = f"절점 {nodes}개 · 부재 {elements}개 선택됨"
        elif nodes:
            summary = f"절점 {nodes}개 선택됨"
        elif elements:
            summary = f"부재 {elements}개 선택됨"
        elif self.canvas.mode == "draw":
            summary = "그리는 중 — 선택하면 속성이 여기에 나타납니다."
        else:
            summary = "선택된 대상이 없습니다."
        self.selection_summary.setText(summary)

    def _refresh_member_section(self, member_tag: int) -> None:
        element = self.canvas.elements[member_tag]
        self.member_end_i.setText(f"N{element.node_i} 쪽 핀 해제 (모멘트 0)")
        self.member_end_j.setText(f"N{element.node_j} 쪽 핀 해제 (모멘트 0)")
        self.member_end_i.blockSignals(True)
        self.member_end_i.setChecked(element.moment_release_i)
        self.member_end_i.blockSignals(False)
        self.member_end_j.blockSignals(True)
        self.member_end_j.setChecked(element.moment_release_j)
        self.member_end_j.blockSignals(False)

    def _apply_member_end_release(self, end: str, released: bool) -> None:
        member_tag = self._selected_member_tag()
        if member_tag is not None:
            self.canvas.set_member_end_release(member_tag, end, released)

    def _insert_member_station_node(self) -> None:
        member_tag = self._selected_member_tag()
        if member_tag is not None:
            self.canvas.add_member_station_node(member_tag, self.member_station.value())

    def _subdivide_member(self) -> None:
        member_tag = self._selected_member_tag()
        if member_tag is not None:
            self.canvas.subdivide_member(member_tag, self.member_segments.value())

    def _commit_draw_entry(self) -> None:
        if self.canvas.commit_entry(self.draw_entry.text()):
            self.draw_entry.clear()
            return
        self.draw_readout.setText("입력 형식을 인식하지 못했습니다.")

    def _refresh_draw_readout(self) -> None:
        measure = self.canvas.pending_length_and_angle()
        parts = []
        if measure is not None:
            parts.append(f"길이 {measure[0]:.4g} m · 각도 {measure[1]:.1f}°")
        if self.canvas.snap_label:
            parts.append(f"스냅 {self.canvas.snap_label}")
        self.draw_readout.setText("   ".join(parts))

    def _load_target_changed(self) -> None:
        """Populate the direction combo with string keys, never composite objects.

        ``QComboBox.findData()`` compares stored Python objects by identity, not
        value, for anything beyond a handful of primitive types it special-cases
        (str, int, float, known enums) — a freshly built tuple that is equal to
        the one stored earlier still fails to match. Keeping each item's data a
        plain string (``"fx+"``, ``"qy-"``) sidesteps that entirely.
        """
        if not hasattr(self, "load_direction"):
            return
        self.load_direction.clear()
        if self.load_target.currentData() == "node":
            directions = [
                ("+X (오른쪽)", "fx+"),
                ("-X (왼쪽)", "fx-"),
                ("+Y (위쪽)", "fy+"),
                ("-Y (아래쪽)", "fy-"),
            ]
            if self.canvas.ndm == 3:
                # A 2D model only ever bends about Z, so Mz alone covers it; a 3D
                # node has three translations and three rotations to load.
                directions += [
                    ("+Z", "fz+"),
                    ("-Z", "fz-"),
                    ("+Mx", "mx+"),
                    ("-Mx", "mx-"),
                    ("+My", "my+"),
                    ("-My", "my-"),
                ]
            directions += [
                ("+Mz (반시계)", "mz+"),
                ("-Mz (시계)", "mz-"),
            ]
            filter_key = "nodes"
        else:
            directions = [
                ("로컬 +x", "qx+"),
                ("로컬 -x", "qx-"),
                ("로컬 +y", "qy+"),
                ("로컬 -y", "qy-"),
            ]
            filter_key = "elements"
        for label, key in directions:
            self.load_direction.addItem(label, key)
        if hasattr(self, "selection_filter"):
            self.selection_filter.setCurrentIndex(self.selection_filter.findData(filter_key))
        self._update_load_unit()

    def _update_load_unit(self) -> None:
        if not hasattr(self, "load_unit"):
            return
        unit = self._unit_system.force
        key = self.load_direction.currentData()
        if self.load_target.currentData() == "element":
            unit = f"{unit}/{self._unit_system.length}"
        elif key and key[:2] in {"mx", "my", "mz"}:
            unit = self._unit_system.moment
        self.load_unit.setText(unit)

    def _apply_directional_load(self) -> None:
        key = self.load_direction.currentData()
        if not key:
            return
        component, sign = key[:2], (1.0 if key[2] == "+" else -1.0)
        value = self.load_magnitude.value() * sign
        if self.load_target.currentData() == "node":
            if self.canvas.ndm == 3:
                index = {"fx": 0, "fy": 1, "fz": 2, "mx": 3, "my": 4, "mz": 5}[component]
                values = tuple(value if i == index else 0.0 for i in range(6))
            else:
                values = {
                    "fx": (value, 0.0, 0.0),
                    "fy": (0.0, value, 0.0),
                    "mz": (0.0, 0.0, value),
                }[component]
            self.canvas.apply_nodal_load_to_selection(values)
        else:
            values = (value, 0.0) if component == "qx" else (0.0, value)
            self.canvas.apply_uniform_load_to_selection(values)

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
        operation = self.node_transform_operation.currentData()
        if operation == "array":
            self.canvas.array_copy_selection(
                self.node_transform_dx.value(),
                self.node_transform_dy.value(),
                self.node_transform_repeat.value(),
            )
            return
        self.canvas.transform_selected_nodes(
            operation,
            self.node_transform_dx.value(),
            self.node_transform_dy.value(),
            self.node_transform_repeat.value(),
        )

    def _apply_mirror(self) -> None:
        self.canvas.mirror_selection(self.mirror_axis.currentData(), self.mirror_value.value())

    def _refresh_status(self) -> None:
        model = self.canvas.build_model()
        load_count = len(model.nodal_loads) + len(model.element_loads)
        self.model_status.setText(
            f"절점 {len(model.nodes)}  |  부재 {len(model.elements)}  |  "
            f"지점 {len(model.boundaries)}  |  하중 {load_count}"
        )
        check = check_determinacy(model)
        self.determinacy_status.setText(f"정정성: {check.message}")

    @staticmethod
    def _section(title: str) -> tuple[QWidget, QVBoxLayout]:
        section = QFrame()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("setupSectionTitle")
        layout.addWidget(label)
        return section, layout

    @staticmethod
    def _number(value: float) -> QDoubleSpinBox:
        field = SafeDoubleSpinBox()
        field.setRange(-1_000_000.0, 1_000_000.0)
        field.setDecimals(4)
        field.setValue(value)
        return field
