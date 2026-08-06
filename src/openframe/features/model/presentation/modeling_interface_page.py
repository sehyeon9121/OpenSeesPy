"""Free-form authoring surface for 2D structural-mechanics models.

The layout keeps the canvas dominant: a narrow tool rail on the left, a coordinate
entry strip under the canvas, and a property panel on the right that follows the
selection.  Only selecting and drawing are tools; everything else — supports,
hinges, loads — is a property of whatever is selected, so adding a new kind of
object never adds another button to learn.
"""

from typing import ClassVar

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
        self.canvas.escape_requested.connect(self._activate_select_tool)
        self.preview_3d.plane_point_picked.connect(self._on_3d_plane_picked)
        self.preview_3d.node_picked.connect(self._on_3d_node_picked)
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
        self.fit_shortcut = QShortcut(QKeySequence("F"), self.canvas)
        self.fit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.fit_shortcut.activated.connect(self.canvas.fit_model)

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
        hint = QLabel("노드, 부재, 지점과 하중을 캔버스에 직접 작성하세요.")
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
        # Re-running solve() re-checks determinacy against whatever the canvas
        # holds *right now* — if the user only wants to look at the results
        # they already computed, that must not require a fresh solve (which
        # would surface a spurious "불안정" if the canvas moved on at all,
        # e.g. a selection-driven property apply after coming back to edit).
        self.view_results_button = QPushButton("결과 보기")
        self.view_results_button.setEnabled(False)
        self.view_results_button.clicked.connect(
            lambda: self.workspace_stack.setCurrentIndex(1)
        )
        layout.addWidget(self.view_results_button)
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
            ("전체 보기", "F · 화면 위치를 잃어버렸을 때 모델 전체가 보이도록 맞춥니다", self.canvas.fit_model),
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

        # 3D mode swaps the 2D plan out entirely for the 3D view, rather than
        # splitting the two — a small preview strip beside a dominant 2D canvas
        # is not "freely modelling in 3D", it is modelling in 2D with a picture
        # of the result off to the side. A stack keeps whichever one is active
        # full-size; only the picking mode wiring needs to know which is shown.
        self.canvas_stack = QStackedWidget()
        self.canvas_stack.addWidget(self.canvas)
        self.preview_3d_panel = self._build_3d_preview_panel()
        self.canvas_stack.addWidget(self.preview_3d_panel)
        layout.addWidget(self.canvas_stack, 1)

        layout.addWidget(self._build_entry_bar())
        return panel

    def _build_3d_preview_panel(self) -> QFrame:
        """The 3D view, with the same camera chrome as the imported-model
        viewer (``ModelViewport``) — a view-preset combo, zoom, and a FIT
        button — so 3D mode looks and drives like the window a student would
        already recognise from opening an existing OpenSeesPy model.
        """
        panel = QFrame()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("directModelCommandBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        header_layout.setSpacing(6)
        header_layout.addWidget(QLabel("3D 뷰"))
        hint = QLabel("가운데 버튼 회전 · Shift+가운데 버튼 이동 · 휠 확대")
        hint.setObjectName("setupSectionHint")
        header_layout.addWidget(hint)
        header_layout.addStretch(1)
        self.preview_3d_camera = QComboBox()
        for label, preset in (("ISO", "iso"), ("XY", "xy"), ("XZ", "xz"), ("YZ", "yz")):
            self.preview_3d_camera.addItem(label, preset)
        self.preview_3d_camera.currentIndexChanged.connect(self._apply_3d_camera_preset)
        header_layout.addWidget(self.preview_3d_camera)
        zoom_out = QPushButton("−")
        zoom_out.setObjectName("railCommandButton")
        zoom_out.setFixedWidth(28)
        zoom_out.clicked.connect(lambda: self.preview_3d.zoom(1 / 1.2))
        header_layout.addWidget(zoom_out)
        zoom_in = QPushButton("+")
        zoom_in.setObjectName("railCommandButton")
        zoom_in.setFixedWidth(28)
        zoom_in.clicked.connect(lambda: self.preview_3d.zoom(1.2))
        header_layout.addWidget(zoom_in)
        fit = QPushButton("FIT")
        fit.setObjectName("railCommandButton")
        fit.setToolTip("화면 위치를 잃어버렸을 때 모델 전체가 보이도록 맞춥니다.")
        fit.clicked.connect(self._fit_3d_preview)
        header_layout.addWidget(fit)
        layout.addWidget(header)

        self.preview_3d = Quick3DViewport()
        layout.addWidget(self.preview_3d, 1)
        return panel

    def _apply_3d_camera_preset(self) -> None:
        preset = self.preview_3d_camera.currentData()
        if preset:
            self.preview_3d.set_camera_preset(str(preset))

    def _fit_3d_preview(self) -> None:
        preset = self.preview_3d_camera.currentData() or "iso"
        self.preview_3d.set_camera_preset(str(preset))

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
        layout.addWidget(QLabel("선택 노드를"))
        self.column_target = QComboBox()
        self.column_target.setMinimumWidth(120)
        layout.addWidget(self.column_target)
        connect_button = QPushButton("기둥으로 연결")
        connect_button.setToolTip("선택한 노드를 다른 평면의 같은 위치와 부재로 잇습니다.")
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
        self.selection_filter.addItem("노드만", "nodes")
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
        section, root = self._section("좌표로 노드 추가")
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
        add = QPushButton("노드 추가")
        add.clicked.connect(self._add_nodes_from_coordinates)
        root.addWidget(add)
        hint = QLabel("연속으로 그리려면 왼쪽 레일의 그리기 도구를 쓰세요.")
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)
        return section

    def _build_node_section(self) -> QWidget:
        section, root = self._section("노드 속성")
        root.addWidget(QLabel("지점 조건"))
        self.support_kind = QComboBox()
        self.support_kind.addItem("자유 (지점 없음)", (False, False, False))
        self.support_kind.addItem("핀 지점", (True, True, False))
        self.support_kind.addItem("수직 롤러", (False, True, False))
        self.support_kind.addItem("수평 롤러", (True, False, False))
        self.support_kind.addItem("고정 지점", (True, True, True))
        self.support_kind.addItem("커스텀 (자유도 직접 지정)", None)
        self.support_kind.setCurrentIndex(1)
        self.support_kind.currentIndexChanged.connect(self._refresh_support_custom_row)
        root.addWidget(self.support_kind)

        self.support_custom_row = QWidget()
        custom_layout = QHBoxLayout(self.support_custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)
        self.support_dof_checks: dict[str, QCheckBox] = {}
        for dof in ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz"):
            box = QCheckBox(dof)
            self.support_dof_checks[dof] = box
            custom_layout.addWidget(box)
        self.support_custom_row.setVisible(False)
        root.addWidget(self.support_custom_row)

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
        apply_support = QPushButton("선택 노드에 적용")
        apply_support.clicked.connect(self._apply_support)
        root.addWidget(apply_support)
        root.addWidget(QLabel("노드 유형"))
        self.node_kind = QComboBox()
        self.node_kind.addItem("일반 노드 (강결)", False)
        self.node_kind.addItem("절점 (활절점 · 내부 힌지)", True)
        root.addWidget(self.node_kind)
        apply_kind = QPushButton("선택 노드에 적용")
        apply_kind.clicked.connect(
            lambda: self.canvas.set_selected_node_kind(bool(self.node_kind.currentData()))
        )
        root.addWidget(apply_kind)
        self.transform_toggle = QPushButton("이동 · 복사 · 배열 ▸")
        self.transform_toggle.setObjectName("sectionToggleButton")
        self.transform_toggle.clicked.connect(self._toggle_transform_section)
        root.addWidget(self.transform_toggle)
        return section

    def _refresh_support_custom_row(self) -> None:
        is_custom = self.support_kind.currentData() is None
        self.support_custom_row.setVisible(is_custom)
        three_d = self.canvas.ndm == 3
        for dof, box in self.support_dof_checks.items():
            box.setVisible(three_d or dof in {"Ux", "Uy", "Rz"})

    def _refresh_node_type_controls(self) -> None:
        """Make the 노드 유형 / 지점 조건 combos reflect the *new* selection's
        actual state, instead of whatever was last left in them.

        Neither combo used to reset on selection change. Mark one node as a
        절점 (힌지), then select a different node to set its support, and the
        노드 유형 combo was still sitting on 절점 — an absent-minded second
        click on its 적용 button (easy to do while working through a frame's
        joints one by one) would hinge a node nobody meant to touch. A node
        clicked to build a member or place a nodal load must stay a plain rigid
        node unless the combo genuinely reflects — and the user deliberately
        changes — a hinge state for *that* node.
        """
        selected = self.canvas.selected_nodes
        if not selected:
            return
        all_hinge = selected <= self.canvas.hinge_nodes
        self.node_kind.blockSignals(True)
        self.node_kind.setCurrentIndex(1 if all_hinge else 0)
        self.node_kind.blockSignals(False)

        if len(selected) != 1:
            return
        tag = next(iter(selected))
        boundary = self.canvas.boundaries.get(tag)
        self.support_angle.blockSignals(True)
        self.support_angle.setValue(boundary.angle if boundary else 0.0)
        self.support_angle.blockSignals(False)

        dof = 6 if self.canvas.ndm == 3 else 3
        restraints = tuple(boundary.restraints[:dof]) if boundary else ()
        restraints += (False,) * (dof - len(restraints))
        preset_index = next(
            (
                index
                for index in range(self.support_kind.count())
                if self.support_kind.itemData(index) is not None
                and len(self.support_kind.itemData(index)) == dof
                and tuple(self.support_kind.itemData(index)) == restraints
            ),
            None,
        )
        self.support_kind.blockSignals(True)
        if preset_index is not None:
            self.support_kind.setCurrentIndex(preset_index)
        else:
            self.support_kind.setCurrentIndex(self.support_kind.findData(None))
            order = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")[:dof]
            for dof_name, value in zip(order, restraints, strict=True):
                self.support_dof_checks[dof_name].setChecked(value)
        self.support_kind.blockSignals(False)
        self._refresh_support_custom_row()

    def _apply_support(self) -> None:
        if self.support_kind.currentData() is None:
            order = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz") if self.canvas.ndm == 3 else ("Ux", "Uy", "Rz")
            restraints = tuple(self.support_dof_checks[dof].isChecked() for dof in order)
        else:
            restraints = self.support_kind.currentData()
        self.canvas.apply_support_to_selection(restraints, self.support_angle.value())

    def _toggle_transform_section(self) -> None:
        self._pinned_section = None if self._pinned_section == "transform" else "transform"
        self._sync_property_panel()

    def _build_transform_section(self) -> QWidget:
        """Move, copy, array-copy and mirror — every operation that turns a hand-
        drawn fragment into a repeated or symmetric shape without redrawing it.
        Collapsed by default (see ``_sync_property_panel``); the toggle button in
        the node section above opens it back up.
        """
        section, root = self._section("노드 이동 · 복사 · 배열")
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
        apply_button = QPushButton("선택 노드에 적용")
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
        mirror_button = QPushButton("선택 노드 대칭 복사")
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
        root.addWidget(QLabel("부재 위 노드 삽입 (x/L)"))
        insert_row = QHBoxLayout()
        self.member_station = self._number(0.5)
        self.member_station.setRange(0.01, 0.99)
        self.member_station.setSingleStep(0.05)
        insert_row.addWidget(self.member_station, 1)
        insert_button = QPushButton("삽입")
        insert_button.clicked.connect(self._insert_member_station_node)
        insert_row.addWidget(insert_button)
        root.addLayout(insert_row)
        hint = QLabel("지점을 임의 위치에 두려면 여기서 노드를 삽입한 뒤 왼쪽에서 선택하세요.")
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
        subdivide_button.setToolTip("트러스 패널이나 격자보처럼 일정 간격 노드가 필요할 때 씁니다.")
        subdivide_button.clicked.connect(self._subdivide_member)
        subdivide_row.addWidget(subdivide_button)
        root.addLayout(subdivide_row)
        return section

    def _build_load_section(self) -> QWidget:
        """Every applicable load component as its own field, applied together.

        A direction dropdown plus one magnitude field cannot represent Fx and Fy
        at once: applying Fx, then switching the dropdown to Fy and applying
        again, silently discards Fx (each apply replaced the whole load). Showing
        every component side by side and applying them all in one click removes
        the trap instead of asking the user to remember it.
        """
        section, root = self._section("하중")
        self.load_target = QComboBox()
        self.load_target.addItem("노드", "node")
        self.load_target.addItem("부재", "element")
        self.load_target.currentIndexChanged.connect(self._load_target_changed)
        root.addWidget(self.load_target)
        self.load_form_layout = QFormLayout()
        self.load_fields: dict[str, QDoubleSpinBox] = {}
        root.addLayout(self.load_form_layout)
        apply_button = QPushButton("선택 대상에 적용 (전체 성분)")
        apply_button.clicked.connect(self._apply_load)
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
            ("노드 변위", "displacement"),
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
        self._load_target_changed()

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
        self.view_results_button.setEnabled(True)
        self.workspace_stack.setCurrentIndex(1)

    def _toggle_3d_mode(self, checked: bool) -> None:
        """Switch between a flat 2D sheet and a freely-orbited 3D view.

        Turning 3D on is one-way for the *data*: the canvas already carries
        model coordinates in three dimensions the moment it is drawn (a 2D canvas
        is just the special case where every z is 0), so nothing is lost by
        entering 3D mode with an empty or already-drawn model. The *view* can
        still be switched back to the flat 2D plan by unchecking the toggle —
        useful for typing exact coordinates — without losing any 3D geometry.
        """
        if checked and self.canvas.ndm != 3:
            self.canvas.enter_3d_mode()
            self.canvas.model_changed.connect(self._refresh_3d_preview)
            self._refresh_plane_selectors()
            # Not relied on to happen via the plane-selector's own signal: Qt may
            # auto-select a combo box's first item while population is still
            # signal-blocked, in which case the later setCurrentIndex(0) is a
            # no-op and currentIndexChanged never fires.
            self.preview_3d.set_active_plane(
                str(self.canvas.work_plane.kind), self.canvas.work_plane.offset
            )
            self._refresh_3d_preview()
            self._load_target_changed()
            self._refresh_support_custom_row()
        self.level_bar.setVisible(checked)
        self.canvas_stack.setCurrentWidget(self.preview_3d_panel if checked else self.canvas)
        # Whichever surface is now on screen needs its picking mode to match
        # whatever tool is already active, not just whatever it was left at.
        self._sync_picking_mode()

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
            self.preview_3d.set_active_plane(str(plane.kind), plane.offset)
            self._refresh_status()

    def _add_plane(self) -> None:
        label = self.new_plane_label.text().strip() or f"평면 {len(self.canvas.levels) + 1}"
        plane = self.canvas.add_level(
            self.new_plane_offset.value(), label, self.new_plane_kind.currentData()
        )
        self._refresh_plane_selectors()
        self.canvas.set_active_plane(plane)
        self.preview_3d.set_active_plane(str(plane.kind), plane.offset)
        self._refresh_plane_selectors()
        self.new_plane_label.clear()

    def _extrude_to_target_plane(self) -> None:
        target = self.column_target.currentData()
        if target is not None:
            self.canvas.extrude_selection_to_plane(target)

    def _on_3d_plane_picked(self, x: float, y: float, z: float) -> None:
        """A click on the active plane in the 3D view — the free-form-3D
        counterpart of a 2D canvas click, feeding the very same chain logic."""
        u, v = self.canvas.work_plane.to_2d((x, y, z))
        self.canvas.place_point(u, v)

    def _on_3d_node_picked(self, tag: int, _screen_x: int, _screen_y: int) -> None:
        """A click on an existing node in the 3D view: continue the chain to it
        while drawing, or just select it otherwise — matching what clicking a
        node on the 2D plan does in each of those tools."""
        if self.canvas.mode == "draw":
            self.canvas.continue_chain_to_node(tag)
        else:
            self.canvas.selected_nodes = {tag}
            self.canvas.selected_elements.clear()
            self.canvas.selection_changed.emit()

    def _refresh_3d_preview(self) -> None:
        if self.canvas.ndm == 3:
            self.preview_3d.set_model(self.canvas.build_model(), reset_camera=False)

    def _set_mode(self, mode: str, description: str) -> None:
        self.canvas.set_mode(mode)
        self.mode_label.setText(description)
        self._sync_picking_mode()

    def _sync_picking_mode(self) -> None:
        """Match the 3D view's click behaviour to whatever tool is active.

        Kept as its own step (not inlined into ``_set_mode``) because the 3D
        panel's picking mode also has to be refreshed on its own when the view
        is swapped in by the 3D toggle, without the tool itself changing.
        """
        if self.canvas.ndm != 3:
            return
        drawing = self.canvas.mode == "draw"
        self.preview_3d.set_plane_picking_mode(drawing)
        self.preview_3d.set_picking_mode(not drawing)

    def _activate_select_tool(self) -> None:
        self.select_tool.setChecked(True)
        self._pinned_section = None
        # A load/support/transform flow narrows the selection filter to just
        # nodes or just members while it is pinned open (_pin_section), but
        # nothing ever widened it back — so after using, say, the 부재 load
        # target once, every later click on a node was silently ignored with
        # no visible reason why. Returning to the plain select tool (by
        # clicking it, pressing V, or Escape) is the natural point to widen
        # it back to "everything is clickable again".
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("all"))
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
            "그리기 · 연속 클릭으로 노드와 부재를 함께 만듭니다. "
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

    def _node_selection_summary(self) -> str:
        """Count the selection as 노드 (rigid) versus 절점 (hinge) — MIDAS's split,
        not just a label swap: a 절점 is specifically where rotation is released,
        so a selection of only hinges should read as 절점, not generic 노드."""
        selected = self.canvas.selected_nodes
        hinges = len(selected & self.canvas.hinge_nodes)
        rigid = len(selected) - hinges
        if hinges and rigid:
            return f"노드 {rigid}개 · 절점 {hinges}개"
        if hinges:
            return f"절점 {hinges}개"
        return f"노드 {rigid}개"

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
        if nodes:
            self._refresh_node_type_controls()
        node_summary = self._node_selection_summary()
        if nodes and elements:
            summary = f"{node_summary} · 부재 {elements}개 선택됨"
        elif nodes:
            summary = f"{node_summary} 선택됨"
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

    #: Order the tuple positions apply_nodal_load_to_selection expects.
    _NODE_LOAD_COMPONENTS_2D = ("fx", "fy", "mz")
    _NODE_LOAD_COMPONENTS_3D = ("fx", "fy", "fz", "mx", "my", "mz")
    _COMPONENT_LABELS: ClassVar[dict[str, str]] = {
        "fx": "Fx",
        "fy": "Fy",
        "fz": "Fz",
        "mx": "Mx",
        "my": "My",
        "mz": "Mz",
        "qx": "qx (로컬 x)",
        "qy": "qy (로컬 y)",
    }

    def _load_target_changed(self) -> None:
        """Rebuild the load field list for the current target and dimension.

        Every applicable component gets its own field so one "적용" click sets
        the whole load at once — see ``_build_load_section`` for why that matters.
        """
        if not hasattr(self, "load_form_layout"):
            return
        while self.load_form_layout.rowCount():
            self.load_form_layout.removeRow(0)
        self.load_fields.clear()
        if self.load_target.currentData() == "node":
            components = (
                self._NODE_LOAD_COMPONENTS_3D if self.canvas.ndm == 3 else self._NODE_LOAD_COMPONENTS_2D
            )
            filter_key = "nodes"
        else:
            components = ("qx", "qy")
            filter_key = "elements"
        for component in components:
            field = self._number(0.0)
            field.setRange(-1_000_000.0, 1_000_000.0)
            unit = self._unit_system.moment if component[0] == "m" else self._unit_system.force
            if self.load_target.currentData() == "element":
                unit = f"{self._unit_system.force}/{self._unit_system.length}"
            self.load_fields[component] = field
            self.load_form_layout.addRow(f"{self._COMPONENT_LABELS[component]} ({unit})", field)
        if hasattr(self, "selection_filter"):
            self.selection_filter.setCurrentIndex(self.selection_filter.findData(filter_key))

    def _apply_load(self) -> None:
        if self.load_target.currentData() == "node":
            components = (
                self._NODE_LOAD_COMPONENTS_3D if self.canvas.ndm == 3 else self._NODE_LOAD_COMPONENTS_2D
            )
            values = tuple(self.load_fields[component].value() for component in components)
            self.canvas.apply_nodal_load_to_selection(values)
        else:
            values = (self.load_fields["qx"].value(), self.load_fields["qy"].value())
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
        hinge_count = len(self.canvas.hinge_nodes)
        node_text = (
            f"노드 {len(model.nodes)} (절점 {hinge_count})" if hinge_count else f"노드 {len(model.nodes)}"
        )
        self.model_status.setText(
            f"{node_text}  |  부재 {len(model.elements)}  |  "
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
