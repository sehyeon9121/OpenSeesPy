"""Free-form authoring surface for 2D structural-mechanics models.

The layout keeps the canvas dominant: a narrow tool rail on the left (only
선택/그리기 — the two modes a click on the canvas can mean), a coordinate
entry strip under the canvas, and a 우측 워크트리 panel on the right. A
single-row category bar above the canvas (``_build_category_bar`` — 노드
추가/이동·복사·배열/노드 분할/지점/노드 유형/부재/하중) picks which
category's settings the 워크트리 panel shows; nothing is pinned there any
more, so the panel is empty until a category is picked and shows exactly
one at a time (``_build_property_panel``). Only selecting and drawing are
tools; everything else — supports, hinges, loads — is a property page one
click away, so adding a new kind of object never adds another mode to
learn, just another category button.
"""

import json
import math
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openframe.app.shell.analysis_progress_banner import AnalysisProgressBanner
from openframe.core.domain import DEFAULT_UNIT_SYSTEM, FORCE_UNITS, LENGTH_UNITS, UnitSystem
from openframe.features.analysis.statics import (
    MaterialFreeSolveThread,
    MaterialFreeStaticsSolver,
    ModalSolveThread,
    ModalStaticsSolver,
    check_determinacy,
)
from openframe.features.model.drawing import PlaneKind
from openframe.features.model.drawing.coordinates import direction_degrees
from openframe.features.model.presentation.canvas_glyphs import (
    _LOAD_TARGET_OPTIONS,
    _SUPPORT_OPTIONS,
    _paint_load_glyph,
    _paint_node_kind_glyph,
    _paint_support_glyph,
    _render_glyph_icon,
)
from openframe.features.model.presentation.rectangle_section_preview import (
    _RectangleSectionPreview,
)
from openframe.features.model.presentation.safe_spinbox import SafeDoubleSpinBox, SafeSpinBox
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
from openframe.features.results.presentation.results_workspace import ResultsWorkspace
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport


class _CurrentPageOnlyStack(QStackedWidget):
    """A ``QStackedWidget`` whose size hint comes only from the page actually
    showing, not the widest of all seven — the plain version reports
    ``max(sizeHint() for every page)`` even though six of them are hidden,
    so the 300px-wide 우측 워크트리 scroll area (``_build_property_panel``)
    had to make room for whichever category page happened to be widest
    (부재's 단면 미리보기 + form, in practice) no matter which one was
    actually open, forcing a horizontal scrollbar even on the narrow 노드
    분할 page. Switching pages needs an explicit ``updateGeometry()`` since
    Qt does not know a widget's size hint changed on its own.
    """

    def sizeHint(self):  # noqa: N802 - Qt override
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class ModelingInterfacePage(QFrame):
    """One-screen workflow: draw, inspect, assign conditions, and review results."""

    def __init__(self, parent: QWidget | None = None, *, start_in_3d: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("modelingInterfacePage")
        self._start_in_3d = start_in_3d
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._solver = MaterialFreeStaticsSolver()
        self._solve_thread: MaterialFreeSolveThread | None = None
        self._modal_solver = ModalStaticsSolver()
        self._modal_solve_thread: ModalSolveThread | None = None
        self.analysis_progress = AnalysisProgressBanner(self)
        self.canvas = StaticsDrawingCanvas()
        # Default 집중하중 input mode - plain Fx/Fy, same as every other axis
        # field in this app; "부재 수직" (magnitude+auto-angle, see
        # ``_build_perpendicular_load_fields``) is an opt-in toggle for when
        # the load is naturally given relative to a sloped member instead.
        self.load_input_mode = "component"

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
        self.draw_space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self.canvas)
        self.draw_space_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.draw_space_shortcut.activated.connect(self._activate_draw_tool)
        self.fit_shortcut = QShortcut(QKeySequence("F"), self.canvas)
        self.fit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.fit_shortcut.activated.connect(self.canvas.fit_model)

        if self._start_in_3d:
            self._enable_3d_mode()
        self._activate_select_tool()
        self._refresh_status()

    # --- layout ------------------------------------------------------------

    def _build_header(self) -> QFrame:
        header = QFrame()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel("3D 구조 모델 작성" if self._start_in_3d else "2D 구조 모델 작성")
        title.setObjectName("setupTitle")
        hint = QLabel("노드, 부재, 지점과 하중을 캔버스에 직접 작성하세요.")
        hint.setObjectName("setupDescription")
        text.addWidget(title)
        text.addWidget(hint)
        layout.addLayout(text)
        layout.addStretch(1)
        self.truss_mode_toggle = QPushButton("트러스 모드")
        self.truss_mode_toggle.setObjectName("modelingToggleButton")
        self.truss_mode_toggle.setCheckable(True)
        self.truss_mode_toggle.setToolTip(
            "켜면 이제부터 그리는 부재가 양단 힌지로 연결된 트러스 부재(축력만 전달)로 "
            "그려집니다. 해석 후에는 부재마다 축력 값이 하나씩 표시됩니다."
        )
        self.truss_mode_toggle.toggled.connect(self._toggle_truss_mode)
        layout.addWidget(self.truss_mode_toggle)
        self.self_weight_toggle = QCheckBox("자중 포함")
        self.self_weight_toggle.setToolTip(
            "켜면 해석 시 부재 단위중량(부재 창의 \"단위중량 ρ\")과 단면적으로 계산한 "
            "자중을 등분포하중처럼 더합니다. 단위중량을 입력하지 않은 부재는 빠집니다."
        )
        self.self_weight_toggle.toggled.connect(self._toggle_self_weight)
        layout.addWidget(self.self_weight_toggle)
        self.pdelta_toggle = QCheckBox("P-Delta 포함")
        self.pdelta_toggle.setToolTip(
            "켜면 2차효과(P-Delta, 기하비선형)를 포함해 해석합니다. 정정성과 무관하게 "
            "모든 부재에 실제 재료·단면(E/A/I)이 필요합니다. 부재 하나로 그려진 기둥의 "
            "축하중이 좌굴하중에 가까울수록(대략 30% 초과) 오차가 커질 수 있습니다."
        )
        layout.addWidget(self.pdelta_toggle)
        self.solve_button = QPushButton("정정성 검사 및 해석")
        self.solve_button.setObjectName("setupContinueButton")
        self.solve_button.clicked.connect(self.solve)
        layout.addWidget(self.solve_button)
        self.modal_num_modes = QSpinBox()
        self.modal_num_modes.setRange(1, 50)
        self.modal_num_modes.setValue(3)
        self.modal_num_modes.setToolTip("계산할 모드 수")
        self.modal_num_modes.setMaximumWidth(56)
        layout.addWidget(self.modal_num_modes)
        self.modal_solve_button = QPushButton("모드해석 실행")
        self.modal_solve_button.setToolTip(
            "고유치(모드) 해석 - 2D 프레임 모델만 지원하며, 모든 부재에 실제 "
            "재료·단면(E/A/I)과 단위중량(밀도)이 입력되어 있어야 합니다. 질량은 "
            "부재 자중(단위중량 x 단면적)에서 절점으로 환산해 계산됩니다."
        )
        self.modal_solve_button.clicked.connect(self.solve_modal)
        layout.addWidget(self.modal_solve_button)
        # Re-running solve() re-checks determinacy against whatever the canvas
        # holds *right now* — if the user only wants to look at the results
        # they already computed, that must not require a fresh solve (which
        # would surface a spurious "불안정" if the canvas moved on at all,
        # e.g. a selection-driven property apply after coming back to edit).
        self.view_results_button = QPushButton("결과 보기")
        self.view_results_button.setObjectName("directModelOpenButton")
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
        self.draw_tool = self._rail_tool("그리기", "L / Space", self._activate_draw_tool)
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
        layout.addWidget(self._build_category_bar())
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
        self.grid_snap_toggle = QCheckBox("격자 스냅")
        self.grid_snap_toggle.setChecked(True)
        self.grid_snap_toggle.setToolTip(
            "켜면 격자가 겹치는 모든 점이 이미 노드가 있는 것처럼 클릭·드로잉이 "
            "자동으로 달라붙습니다. 끄면 커서가 가리키는 위치에 그대로 찍힙니다."
        )
        self.grid_snap_toggle.toggled.connect(
            lambda checked: setattr(self.canvas, "grid_snap_enabled", bool(checked))
        )
        layout.addWidget(self.grid_snap_toggle)
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

    #: (category key, button label) for the single-row category bar above the
    #: canvas — order here is both the button order and the 우측 워크트리
    #: page order. Nothing is pinned any more: every one of these, including
    #: 노드 추가/이동·복사·배열 (previously always-on in the right panel), is
    #: now an equal category that opens on click. The previous design's
    #: problem was exactly this asymmetry - 부재 노드 삽입·등분할 sat at the
    #: bottom of an always-visible stack, invisible below the fold unless you
    #: already knew to scroll for it; a first-time user had no way to
    #: discover it. It got its own category briefly, then folded into 노드
    #: 추가 (``_build_add_category``) since both are "make a new node" in the
    #: same breath - a single always-visible row of buttons has no fold to
    #: hide behind either way.
    _CATEGORY_OPTIONS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("add", "노드 추가"),
        ("move", "이동 · 복사 · 배열"),
        ("arch", "아치"),
        ("support", "지점"),
        ("kind", "노드 유형"),
        ("member", "부재"),
        ("load", "하중"),
    )

    def _build_category_bar(self) -> QFrame:
        """The single-row bar above the canvas that picks what the 우측
        워크트리 panel shows — see ``_CATEGORY_OPTIONS``. An exclusive
        ``QButtonGroup`` already gives exactly the interaction wanted: click
        a category to show it, click a different one to switch, and
        clicking the already-active one is a no-op (Qt never lets an
        exclusive group end up with nothing checked once something has been
        checked) — so the panel stays open on whatever was last picked
        instead of needing an explicit close button.
        """
        bar = QFrame()
        bar.setObjectName("directModelCommandBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(True)
        self.category_buttons: dict[str, QToolButton] = {}
        for index, (key, label) in enumerate(self._CATEGORY_OPTIONS):
            button = QToolButton()
            button.setObjectName("slideOutToggle")
            button.setCheckable(True)
            button.setText(label)
            self.category_group.addButton(button, index)
            self.category_buttons[key] = button
            layout.addWidget(button)
        self.category_group.idClicked.connect(self._show_category_by_index)
        layout.addStretch(1)
        return bar

    def _show_category_by_index(self, index: int) -> None:
        self._show_category(self._CATEGORY_OPTIONS[index][0])

    def _show_category(self, key: str) -> None:
        button = self.category_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        self.category_stack.setCurrentIndex(self.category_pages[key])

    def _build_property_panel(self) -> QScrollArea:
        """우측 워크트리: 아무 카테고리도 고르지 않았으면 비어 있고, 상단
        카테고리 바(``_build_category_bar``)에서 하나를 고르면 그 내용만
        여기 나타난다 — 예전엔 노드 추가·이동복사배열만 항상 떠 있고
        나머지(지점/노드유형/부재/하중)는 캔버스 위 아코디언에 있었는데,
        그 비대칭 자체가 발견성 문제였다(부재 노드 삽입은 스크롤해야 보이는
        마지막 섹션이라 처음 쓰는 사람은 있는지도 몰랐다). 지금은 카테고리
        전부 같은 자격으로, 클릭하기 전엔 아무것도 차지하지 않고
        클릭하면 그 하나만 이 폭(300px) 안에서 세로로 펼쳐진다 — 가로 폭
        한계 때문에 글자가 잘리던 문제도 이걸로 같이 해결된다.
        """
        panel = QFrame()
        panel.setObjectName("modelingPropertyPanel")
        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        self.selection_summary = QLabel()
        self.selection_summary.setObjectName("setupSectionTitle")
        self.selection_summary.setWordWrap(True)
        root.addWidget(self.selection_summary)

        self.category_stack = _CurrentPageOnlyStack()
        self.category_stack.currentChanged.connect(lambda _index: self.category_stack.updateGeometry())
        self.category_pages: dict[str, int] = {}
        empty = QLabel("위에서 카테고리를 고르면\n여기에 설정이 표시됩니다.")
        empty.setObjectName("setupSectionHint")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.category_pages["empty"] = self.category_stack.addWidget(empty)
        builders = {
            "add": self._build_add_category,
            "move": self._build_transform_section,
            "arch": self._build_arch_category,
            "support": self._build_support_category,
            "kind": self._build_node_kind_category,
            "member": self._build_member_category,
            "load": self._build_load_category,
        }
        for key, _label in self._CATEGORY_OPTIONS:
            self.category_pages[key] = self.category_stack.addWidget(builders[key]())
        self.category_stack.setCurrentIndex(self.category_pages["empty"])
        root.addWidget(self.category_stack)
        root.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("modelingInspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(300)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _build_support_category(self) -> QWidget:
        section, root = self._section("지점", show_title=False)
        root.addWidget(self._build_support_icon_row())
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("경사각(°)"))
        self.support_angle = self._number(0.0)
        self.support_angle.setRange(-360.0, 360.0)
        self.support_angle.setToolTip(
            "지지면이 수평에서 반시계 방향으로 기울어진 각도. 0이면 보통의 수평·수직 지점입니다."
        )
        self.support_angle.editingFinished.connect(self._apply_support)
        angle_row.addWidget(self.support_angle, 1)
        root.addLayout(angle_row)
        rotate_row = QHBoxLayout()
        cw_button = QPushButton("↻ 시계 30°")
        cw_button.setToolTip("경사각을 시계 방향으로 30°씩 돌리고 바로 적용합니다.")
        cw_button.clicked.connect(lambda: self._rotate_support_angle(-30.0))
        rotate_row.addWidget(cw_button)
        ccw_button = QPushButton("↺ 반시계 30°")
        ccw_button.setToolTip("경사각을 반시계 방향으로 30°씩 돌리고 바로 적용합니다.")
        ccw_button.clicked.connect(lambda: self._rotate_support_angle(30.0))
        rotate_row.addWidget(ccw_button)
        root.addLayout(rotate_row)
        self.support_custom_row = QWidget()
        custom_layout = QGridLayout(self.support_custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(6)
        self.support_dof_checks: dict[str, QCheckBox] = {}
        for i, dof in enumerate(("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")):
            box = QCheckBox(dof)
            box.toggled.connect(self._apply_support)
            self.support_dof_checks[dof] = box
            custom_layout.addWidget(box, i // 3, i % 3)
        self.support_custom_row.setVisible(False)
        root.addWidget(self.support_custom_row)
        return section

    def _build_node_kind_category(self) -> QWidget:
        section, root = self._section("노드 유형", show_title=False)
        root.addWidget(self._build_node_kind_icon_row())
        return section

    def _build_member_category(self) -> QWidget:
        section, root = self._section("부재", show_title=False)
        root.addWidget(self._build_member_bar_content())
        return section

    def _build_load_category(self) -> QWidget:
        section, root = self._section("하중", show_title=False)
        root.addWidget(self._build_load_bar_content())
        return section

    def _build_add_category(self) -> QWidget:
        """좌표로 노드 추가 + 부재 노드 삽입·등분할, 한 카테고리 페이지에 같이.

        둘 다 "새 노드를 만든다"는 점에서 한 갈래이고, 부재 등분할처럼
        모델링 초반에 격자보·트러스 패널을 준비할 때 좌표 입력과 번갈아
        쓰는 경우가 많아 카테고리를 오가게 두는 것보다 한 페이지에 있는
        편이 낫다.
        """
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self._build_create_section())
        root.addWidget(self._build_member_edit_section())
        return page

    def _build_arch_category(self) -> QWidget:
        """A circular arch generated from just its span (start point + L)
        and rise — most textbook arch problems keep the same rise/shape and
        only vary the span, so the four numbers below plus 아치 생성 is the
        whole job; nobody has to work out a radius by hand.

        The result (``StaticsDrawingCanvas.add_arch``) is nothing but
        ordinary straight 노드/부재 stepping along the arc, so every other
        category — 지점, 노드 유형, 부재, 하중, and 노드 추가's 부재 노드
        삽입·등분할 for splitting one of the straight facets further — already
        works on it with no special case at all.
        """
        section, root = self._section("아치", show_title=False)
        form = QFormLayout()
        self.arch_start_x = self._number(0.0)
        self.arch_start_y = self._number(0.0)
        self.arch_span = self._number(8.0)
        self.arch_span.setRange(0.01, 1_000_000.0)
        self.arch_rise = self._number(1.6)
        self.arch_rise.setRange(0.0, 1_000_000.0)
        self.arch_rise.setToolTip(
            "시작점 높이(시작 Y) 기준으로 스팬 중앙이 올라간 높이 — 곡률(라이즈/"
            "스팬 비)은 대부분의 문제에서 일정하고 스팬만 바뀌므로, 기본값을 "
            "그대로 두고 스팬만 바꿔도 됩니다."
        )
        self.arch_segments = SafeSpinBox()
        self.arch_segments.setRange(2, 200)
        self.arch_segments.setValue(12)
        self.arch_segments.setToolTip(
            "아치를 몇 개의 직선 부재로 근사할지 — 많을수록 곡선에 가까워집니다."
        )
        form.addRow("시작 X", self.arch_start_x)
        form.addRow("시작 Y", self.arch_start_y)
        form.addRow("스팬 L", self.arch_span)
        form.addRow("라이즈 h", self.arch_rise)
        form.addRow("분할 개수", self.arch_segments)
        root.addLayout(form)
        generate = QPushButton("아치 생성")
        generate.clicked.connect(self._generate_arch)
        root.addWidget(generate)
        hint = QLabel(
            "생성된 절점·부재는 다른 카테고리(지점/노드 유형/부재/하중)에서 그대로 "
            "다룰 수 있습니다 — 아치도 결국 직선 부재들의 모임입니다."
        )
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)
        return section

    def _generate_arch(self) -> None:
        self.canvas.add_arch(
            self.arch_start_x.value(),
            self.arch_start_y.value(),
            self.arch_span.value(),
            self.arch_rise.value(),
            self.arch_segments.value(),
        )

    def _build_create_section(self) -> QWidget:
        section, root = self._section("좌표로 노드 추가", show_title=False)
        self.node_relative = QCheckBox("상대좌표 (선택한 노드 기준)")
        self.node_relative.toggled.connect(self._refresh_create_section_hint)
        root.addWidget(self.node_relative)
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
        self.create_section_hint = QLabel()
        self.create_section_hint.setWordWrap(True)
        self.create_section_hint.setObjectName("setupSectionHint")
        root.addWidget(self.create_section_hint)
        self._refresh_create_section_hint()
        return section

    def _refresh_create_section_hint(self) -> None:
        if not self.node_relative.isChecked():
            self.create_section_hint.setText(
                "연속으로 그리려면 왼쪽 레일의 그리기 도구를 쓰세요."
            )
            return
        selected = len(self.canvas.selected_nodes)
        if selected == 1:
            self.create_section_hint.setText("선택한 노드를 기준으로 오프셋을 추가합니다.")
        elif selected == 0:
            self.create_section_hint.setText(
                "원점(0, 0) 기준으로 추가합니다. 노드를 하나 선택하면 그 노드가 기준점이 됩니다."
            )
        else:
            self.create_section_hint.setText(
                f"노드 {selected}개가 선택돼 기준점이 모호합니다 — 지금은 원점(0, 0) 기준으로 "
                "추가됩니다. 노드를 하나만 선택하면 그 노드가 기준점이 됩니다."
            )

    def _build_support_icon_row(self) -> QWidget:
        """Icon buttons for 지점 조건, one per ``_SUPPORT_OPTIONS`` entry, applied
        the moment you click one — no separate 적용 button, matching the instant-
        apply feel of the 부재 단부 핀 해제 checkboxes below. Each icon mirrors the
        symbol ``SupportItem`` draws on the canvas so the button you clicked and the
        glyph that appears on the model read as the same shape.

        A 3-column grid, not one long row - six icons abreast never fit the
        우측 패널's fixed 300px width, and this is exactly the kind of "more
        icons added over time, no more horizontal room" clipping the
        category bar itself used to hit. A grid just adds another row
        instead of squeezing.
        """
        row = QWidget()
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.support_group = QButtonGroup(self)
        self.support_group.setExclusive(True)
        self.support_buttons: dict[int, QToolButton] = {}
        columns = 3
        for index, (label, tooltip, glyph_key, _restraints) in enumerate(_SUPPORT_OPTIONS):
            button = QToolButton()
            button.setObjectName("supportKindButton")
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIcon(_render_glyph_icon(lambda p, c, k=glyph_key: _paint_support_glyph(p, k, c)))
            button.setIconSize(QSize(22, 22))
            button.setText(label)
            button.setToolTip(tooltip)
            self.support_group.addButton(button, index)
            self.support_buttons[index] = button
            layout.addWidget(button, index // columns, index % columns)
        self.support_buttons[1].setChecked(True)  # default: 핀 지점, matches the old combo's index
        self.support_group.idClicked.connect(self._on_support_button_clicked)
        return row

    def _build_node_kind_icon_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.node_kind_group = QButtonGroup(self)
        self.node_kind_group.setExclusive(True)

        self.node_kind_rigid_button = QToolButton()
        self.node_kind_rigid_button.setObjectName("supportKindButton")
        self.node_kind_rigid_button.setCheckable(True)
        self.node_kind_rigid_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.node_kind_rigid_button.setIcon(
            _render_glyph_icon(lambda p, c: _paint_node_kind_glyph(p, False, c))
        )
        self.node_kind_rigid_button.setIconSize(QSize(22, 22))
        self.node_kind_rigid_button.setText("강결")
        self.node_kind_rigid_button.setToolTip("일반 노드 (강결) — 만나는 부재끼리 모멘트를 전달합니다.")
        self.node_kind_rigid_button.setChecked(True)
        self.node_kind_group.addButton(self.node_kind_rigid_button, 0)
        layout.addWidget(self.node_kind_rigid_button)

        self.node_kind_hinge_button = QToolButton()
        self.node_kind_hinge_button.setObjectName("supportKindButton")
        self.node_kind_hinge_button.setCheckable(True)
        self.node_kind_hinge_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.node_kind_hinge_button.setIcon(
            _render_glyph_icon(lambda p, c: _paint_node_kind_glyph(p, True, c))
        )
        self.node_kind_hinge_button.setIconSize(QSize(22, 22))
        self.node_kind_hinge_button.setText("활절점")
        self.node_kind_hinge_button.setToolTip("절점 (활절점 · 내부 힌지) — 모멘트를 전달하지 않습니다.")
        self.node_kind_group.addButton(self.node_kind_hinge_button, 1)
        layout.addWidget(self.node_kind_hinge_button)
        layout.addStretch(1)

        self.node_kind_group.idClicked.connect(
            lambda index: self.canvas.set_selected_node_kind(bool(index))
        )
        return row

    def _on_support_button_clicked(self, _index: int) -> None:
        self._refresh_support_custom_row()
        self._apply_support()

    def _refresh_support_custom_row(self) -> None:
        checked = self.support_group.checkedButton()
        is_custom = checked is not None and _SUPPORT_OPTIONS[self.support_group.id(checked)][3] is None
        self.support_custom_row.setVisible(is_custom)
        three_d = self.canvas.ndm == 3
        for dof, box in self.support_dof_checks.items():
            box.setVisible(three_d or dof in {"Ux", "Uy", "Rz"})

    def _refresh_node_type_controls(self) -> None:
        """Make the 노드 유형 / 지점 조건 버튼들이 reflect the *new* selection's
        actual state, instead of whatever was last left checked.

        Neither control used to reset on selection change. Mark one node as a
        절점 (힌지), then select a different node, and 노드 유형 was still sitting
        on 절점 — an absent-minded extra click (easy while working through a
        frame's joints one by one) would hinge a node nobody meant to touch. A
        node clicked to build a member or place a nodal load must stay a plain
        rigid node unless the control genuinely reflects — and the user
        deliberately changes — a hinge state for *that* node. ``setChecked()``
        never fires ``idClicked``, so refreshing here cannot loop back into
        applying anything.
        """
        selected = self.canvas.selected_nodes
        if not selected:
            return
        all_hinge = selected <= self.canvas.hinge_nodes
        (self.node_kind_hinge_button if all_hinge else self.node_kind_rigid_button).setChecked(True)

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
                for index, (_, _, _, template) in enumerate(_SUPPORT_OPTIONS)
                if template is not None and len(template) == dof and tuple(template) == restraints
            ),
            None,
        )
        if preset_index is not None:
            self.support_buttons[preset_index].setChecked(True)
        else:
            self.support_buttons[len(_SUPPORT_OPTIONS) - 1].setChecked(True)  # 커스텀
            order = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")[:dof]
            for dof_name, value in zip(order, restraints, strict=True):
                self.support_dof_checks[dof_name].setChecked(value)
        self._refresh_support_custom_row()

    def _rotate_support_angle(self, delta: float) -> None:
        """Nudge 경사각 by ``delta`` degrees (wrapping into [0, 360)) and apply
        immediately - unlike typing into the field, a button click never
        fires ``editingFinished`` on its own, so this calls ``_apply_support``
        itself rather than relying on that signal."""
        self.support_angle.setValue((self.support_angle.value() + delta) % 360.0)
        self._apply_support()

    def _apply_support(self) -> None:
        checked = self.support_group.checkedButton()
        if checked is None:
            return
        template = _SUPPORT_OPTIONS[self.support_group.id(checked)][3]
        if template is None:
            order = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz") if self.canvas.ndm == 3 else ("Ux", "Uy", "Rz")
            restraints = tuple(self.support_dof_checks[dof].isChecked() for dof in order)
        else:
            restraints = template
        self.canvas.apply_support_to_selection(restraints, self.support_angle.value())

    def _build_transform_section(self) -> QWidget:
        """Move, copy, array-copy and mirror — every operation that turns a hand-
        drawn fragment into a repeated or symmetric shape without redrawing it.
        Its own 이동·복사·배열 category page in the 우측 워크트리 panel.
        """
        section, root = self._section("노드 이동 · 복사 · 배열", show_title=False)
        self.node_transform_operation = QComboBox()
        self.node_transform_operation.addItem("이동", "move")
        self.node_transform_operation.addItem("복사", "copy")
        self.node_transform_operation.addItem("배열 복사 (부재 포함)", "array")
        self.node_transform_operation.addItem("회전 복사 (부재 포함)", "rotate")
        self.node_transform_operation.currentIndexChanged.connect(self._sync_transform_form)
        root.addWidget(self.node_transform_operation)
        self.node_transform_form = QFormLayout()
        form = self.node_transform_form
        self.node_transform_dx = self._number(1.0)
        self.node_transform_dy = self._number(0.0)
        self.node_transform_dx_label = QLabel("dX")
        self.node_transform_dy_label = QLabel("dY")
        form.addRow(self.node_transform_dx_label, self.node_transform_dx)
        form.addRow(self.node_transform_dy_label, self.node_transform_dy)
        self.node_transform_angle = self._number(90.0)
        self.node_transform_angle.setToolTip(
            "복사할 때마다 누적되는 회전각 — 예: 3개·30°면 원본 기준 30°/60°/90° 위치에 복사됩니다."
        )
        form.addRow("회전각(°)", self.node_transform_angle)
        self.node_transform_repeat = SafeSpinBox()
        self.node_transform_repeat.setRange(1, 1000)
        self.node_transform_repeat.setEnabled(False)
        form.addRow("반복/배열 개수", self.node_transform_repeat)
        root.addLayout(form)
        self._sync_transform_form()
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

    def _build_member_edit_section(self) -> QWidget:
        """Add a node mid-span on a member, or subdivide it into equal
        segments — geometry operations on a selected member, grouped with
        좌표로 노드 추가 on the 노드 추가 category page (``_build_add_category``)
        rather than with the 부재 category's section/material fields, since
        these add nodes instead of setting a property on the member that
        already exists.
        """
        section, root = self._section("부재 노드 삽입 · 등분할", show_title=False)
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
        hint = QLabel("지점을 임의 위치에 두려면 여기서 노드를 삽입한 뒤 선택하세요.")
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

    def _build_member_bar_content(self) -> QWidget:
        """Section/material (단면·재료) plus per-end pin release, for one
        selected member — the content shown on the 부재 category page. Mid-
        span node insertion and equal subdivision live on their own 노드 분할
        category page instead (``_build_member_edit_section``) — they add
        nodes/geometry rather than set a property on the member itself.

        A member always has two ends regardless of which node tags they land on, so
        the checkboxes are labelled with the actual node numbers when the selection
        changes rather than fixed "start/end" text.

        Section input is per member (select one, type its own b/h/E), not one
        global value for the whole model — a hand-drawn cantilever, portal
        frame etc. can freely mix member sizes, and this is also what makes a
        width unambiguous: b and h are just two ordinary fields next to a
        member you already picked, not something a canvas drag would need to
        somehow guess a third dimension for.
        """
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addWidget(QLabel("단면 (사각형) · 재료"))
        self.member_section_preview = _RectangleSectionPreview()
        preview_row = QHBoxLayout()
        preview_row.addStretch(1)
        preview_row.addWidget(self.member_section_preview)
        preview_row.addStretch(1)
        root.addLayout(preview_row)
        section_form = QFormLayout()
        self.member_width = self._number(0.3)
        self.member_width.setRange(0.001, 100.0)
        self.member_height = self._number(0.5)
        self.member_height.setRange(0.001, 100.0)
        self.member_elastic = self._number(200_000_000.0)
        self.member_elastic.setRange(0.0, 1.0e12)
        self.member_density = self._number(0.0)
        self.member_density.setRange(0.0, 1.0e6)
        self.member_density.setToolTip(
            "자중(自重) 계산에 쓰이는 단위중량. 0이면 상단 \"자중 포함\" 체크박스를 켜도 "
            "이 부재는 자중 계산에서 빠집니다."
        )
        self.member_width.valueChanged.connect(self._refresh_member_section_preview)
        self.member_height.valueChanged.connect(self._refresh_member_section_preview)
        width_row, self.member_width_unit = self._field_with_unit(self.member_width)
        height_row, self.member_height_unit = self._field_with_unit(self.member_height)
        elastic_row, self.member_elastic_unit = self._field_with_unit(self.member_elastic)
        density_row, self.member_density_unit = self._field_with_unit(self.member_density)
        section_form.addRow("폭 b", width_row)
        section_form.addRow("높이 h", height_row)
        section_form.addRow("탄성계수 E", elastic_row)
        section_form.addRow("단위중량 ρ", density_row)
        self._refresh_member_unit_hint()
        root.addLayout(section_form)
        apply_section = QPushButton("선택 부재에 적용")
        apply_section.clicked.connect(self._apply_member_section)
        root.addWidget(apply_section)
        section_hint = QLabel(
            "정정구조는 없어도 풀리지만, 부정정 구조를 풀거나 실제 처짐 값을 보려면 "
            "선택한 부재마다 입력해야 합니다."
        )
        section_hint.setWordWrap(True)
        section_hint.setObjectName("setupSectionHint")
        root.addWidget(section_hint)

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
        return content

    def _field_with_unit(self, field: QWidget) -> tuple[QWidget, QLabel]:
        """Pair an engineering-value field with a small, live unit label next
        to it — reading "0.3 [m]" beside the field itself is one less lookup
        than a single combined line below several fields at once."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(field, 1)
        unit_label = QLabel()
        unit_label.setObjectName("setupSectionHint")
        layout.addWidget(unit_label)
        return row, unit_label

    def _refresh_member_unit_hint(self) -> None:
        self.member_width_unit.setText(self._unit_system.length)
        self.member_height_unit.setText(self._unit_system.length)
        self.member_elastic_unit.setText(self._unit_system.stress)
        self.member_density_unit.setText(self._unit_system.volumetric_force)

    def _build_load_bar_content(self) -> QWidget:
        """Every applicable load component as its own field, applied together.

        A direction dropdown plus one magnitude field cannot represent Fx and Fy
        at once: applying Fx, then switching the dropdown to Fy and applying
        again, silently discards Fx (each apply replaced the whole load). Showing
        every component side by side and applying them all in one click removes
        the trap instead of asking the user to remember it.

        Laid out as a vertical form (label above/beside its own field, one
        row per component via ``QFormLayout``) now that this lives in the
        우측 워크트리 panel rather than a fixed-height horizontal bar above
        the canvas - a form just grows another row as fields are added
        instead of running out of horizontal room and clipping text.
        """
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(self._build_load_target_icon_row())
        # 기본은 다른 축 입력과 같은 방식인 Fx/Fy 직접 입력입니다. 경사 부재에
        # 수직인 하중(풍하중 등)처럼 각도를 직접 계산하기 번거로운 경우를 위해
        # '부재 수직' 입력(크기 하나 + 자동 각도)으로 전환할 수 있습니다. 노드가
        # 아닌 대상(등분포/사다리꼴 하중)이나 3D에서는 의미가 없어 숨겨집니다.
        self.load_mode_toggle = QPushButton("부재 수직 입력으로")
        self.load_mode_toggle.setObjectName("slideOutToggle")
        self.load_mode_toggle.setCheckable(True)
        self.load_mode_toggle.setToolTip(
            "기본은 Fx/Fy 직접 입력입니다. 이 버튼을 켜면 대신 '부재 수직' 입력으로 "
            "바뀝니다 — 하중을 받을 노드를 선택하면(그 노드에 연결된 부재가 여러 "
            "개면 Ctrl+클릭으로 기준 부재도 함께) 그 부재에 수직인 방향으로 크기 "
            "하나만 넣으면 되고, Fx/Fy는 내부적으로만 계산됩니다."
        )
        self.load_mode_toggle.toggled.connect(self._toggle_load_input_mode)
        root.addWidget(self.load_mode_toggle)
        self.load_form_layout = QFormLayout()
        self.load_form_layout.setSpacing(6)
        self.load_fields: dict[str, QDoubleSpinBox] = {}
        root.addLayout(self.load_form_layout)
        apply_button = QPushButton("적용")
        apply_button.setToolTip("선택 대상에 적용 (전체 성분)")
        apply_button.clicked.connect(self._apply_load)
        root.addWidget(apply_button)
        self._load_target_changed()
        return content

    def _toggle_load_input_mode(self, checked: bool) -> None:
        self.load_input_mode = "perpendicular" if checked else "component"
        self.load_mode_toggle.setText("성분(Fx,Fy) 직접 입력으로" if checked else "부재 수직 입력으로")
        self._load_target_changed()

    def _build_perpendicular_load_fields(self) -> None:
        """The default 집중하중 input: one 크기 (magnitude) field, an 각도
        field that follows the selected node's member automatically (see
        ``_fill_angle_perpendicular_to_selected_member``) but can still be
        typed over by hand, and Mz. Fx/Fy are never shown here — they exist
        only as hidden fields (still ``self.load_fields["fx"/"fy"]``, so
        ``_apply_load``/``_node_load_values``/the preview all keep working
        unchanged) that ``_apply_magnitude_angle_to_fxfy`` keeps in sync
        live. Most nodal loads in practice are "perpendicular to this
        member, magnitude X" (wind on a rafter, a point load at a sloped
        member's end) - asking for Fx/Fy up front made the user compute the
        member's own slope by hand before a load could be typed in at all.
        """
        self.load_magnitude = self._number(0.0)
        self.load_magnitude.setRange(-1_000_000.0, 1_000_000.0)
        self.load_magnitude.setToolTip(
            "부재에 수직인 방향으로 작용하는 힘의 크기 — 부호를 반대로 하면 "
            "반대 방향이 됩니다."
        )
        self.load_angle = self._number(0.0)
        self.load_angle.setRange(-1_000_000.0, 1_000_000.0)
        self.load_angle.setToolTip(
            "전역 +X축에서 반시계 방향으로 잰 각도(°) — 하중을 받을 노드를 선택할 "
            "때마다 그 노드에 연결된 부재를 기준으로 자동 채워집니다. 부재가 "
            "여러 개(방향이 다름)면 Ctrl+클릭으로 기준 부재를 함께 선택하세요. "
            "직접 고쳐 쓸 수도 있습니다."
        )
        self.load_magnitude.valueChanged.connect(self._apply_magnitude_angle_to_fxfy)
        self.load_angle.valueChanged.connect(self._apply_magnitude_angle_to_fxfy)
        self.load_form_layout.addRow("크기", self.load_magnitude)
        self.load_form_layout.addRow("각도(°)", self.load_angle)

        fx_field = self._number(0.0)
        fy_field = self._number(0.0)
        for hidden_field in (fx_field, fy_field):
            hidden_field.setParent(self)
            hidden_field.hide()
            hidden_field.valueChanged.connect(self._update_load_preview)
        self.load_fields["fx"] = fx_field
        self.load_fields["fy"] = fy_field

        mz_field = self._number(0.0)
        mz_field.setRange(-1_000_000.0, 1_000_000.0)
        mz_field.setToolTip(f"{self._COMPONENT_LABELS['mz']} — 시계방향(+) / 반시계방향(-)")
        mz_field.valueChanged.connect(self._update_load_preview)
        self.load_fields["mz"] = mz_field
        self.load_form_layout.addRow("Mz", mz_field)

        recompute_button = QPushButton("각도 재계산")
        recompute_button.setToolTip(
            "각도를 선택된 노드(또는 Ctrl+클릭으로 함께 선택한 기준 부재)의 수직 "
            "방향으로 다시 채웁니다 — 각도를 직접 고친 뒤 자동 계산값으로 되돌리고 "
            "싶을 때 씁니다."
        )
        recompute_button.clicked.connect(lambda _checked=False: self._fill_angle_perpendicular_to_selected_member())
        self.load_form_layout.addRow(recompute_button)

        self._fill_angle_perpendicular_to_selected_member(silent=True)

    def _apply_magnitude_angle_to_fxfy(self) -> None:
        magnitude = self.load_magnitude.value()
        angle = math.radians(self.load_angle.value())
        if "fx" in self.load_fields:
            self.load_fields["fx"].setValue(magnitude * math.cos(angle))
        if "fy" in self.load_fields:
            self.load_fields["fy"].setValue(magnitude * math.sin(angle))

    def _selected_reference_member_tag(self) -> int | None:
        """Whichever single member is selected, regardless of whether a node
        is *also* selected — unlike ``_selected_member_tag`` (which decides
        what the 부재 window shows, and deliberately returns ``None`` the
        moment any node joins the selection), this is for reading a member's
        own geometry as an angle reference while a node stays the actual load
        target, so selecting both at once must not disqualify it.
        """
        elements = self.canvas.selected_elements
        return next(iter(elements)) if len(elements) == 1 else None

    def _member_touching_selected_node(self) -> int | None:
        """The one member touching the single selected (load-target) node,
        used as a fallback reference when no member was explicitly
        Ctrl-selected alongside it — 하중 targets a node, so a load-target
        node with only one member at it (a rafter end, a cantilever tip, a
        truss apex) has an unambiguous "perpendicular to the member" angle
        without making the user hold Ctrl and click the member too.

        A node touching two or more members is only genuinely ambiguous if
        those members point in different directions. 부재 노드 삽입 (splitting
        a drawn member at a point along its span) is a very common way to
        get a second member at a node — both halves sit on the exact same
        line, so "perpendicular to the member" is one unambiguous answer
        regardless of which half is picked. Only a true corner/branch joint
        (members at genuinely different angles) still needs an explicit
        Ctrl-selected member.
        """
        nodes = self.canvas.selected_nodes
        if len(nodes) != 1:
            return None
        (node_tag,) = nodes
        node = self.canvas.nodes[node_tag]
        touching: list[tuple[int, float, float]] = []
        for tag, element in self.canvas.elements.items():
            if element.node_i == node_tag:
                other = self.canvas.nodes[element.node_j]
            elif element.node_j == node_tag:
                other = self.canvas.nodes[element.node_i]
            else:
                continue
            touching.append((tag, other.x - node.x, other.y - node.y))
        if not touching:
            return None
        first_tag, fx, fy = touching[0]
        flen = math.hypot(fx, fy)
        if flen == 0:
            return None
        for _tag, dx, dy in touching[1:]:
            dlen = math.hypot(dx, dy)
            if dlen == 0:
                return None
            # sine of the angle between the two directions, via the
            # normalized 2D cross product - ~0 means the same line.
            if abs((fx * dy - fy * dx) / (flen * dlen)) > 1e-6:
                return None
        return first_tag

    def _fill_angle_perpendicular_to_selected_member(self, *, silent: bool = False) -> None:
        """``silent`` skips the ⚠ warning — used when this runs automatically
        on every selection change (see ``_selection_changed``), where an
        ordinary click that doesn't happen to land on a usable reference
        (nothing selected yet, a node with no member, mid-drawing) is not a
        mistake worth interrupting the user about; the explicit "각도
        재계산" button still surfaces it since there the user asked
        specifically for this to work.
        """
        tag = self._selected_reference_member_tag()
        if tag is None:
            tag = self._member_touching_selected_node()
        if tag is None:
            if silent:
                return
            if len(self.canvas.selected_elements) > 1 or not self.canvas.selected_nodes:
                self.selection_summary.setText(
                    "⚠ 기준 부재를 정할 수 없습니다 — 하중을 받을 노드를 선택하세요 "
                    "(그 노드에 부재가 둘 이상이면 Ctrl+클릭으로 기준 부재도 함께 선택)."
                )
            else:
                self.selection_summary.setText(
                    "⚠ 선택된 노드에 부재가 둘 이상 연결돼 있어 기준 부재를 정할 수 "
                    "없습니다 — 기준으로 삼을 부재를 Ctrl+클릭으로 함께 선택하세요."
                )
            return
        element = self.canvas.elements[tag]
        node_i = self.canvas.nodes[element.node_i]
        node_j = self.canvas.nodes[element.node_j]
        angle = direction_degrees((node_i.x, node_i.y), (node_j.x, node_j.y))
        self.load_angle.setValue(angle + 90.0)

    def _build_load_target_icon_row(self) -> QWidget:
        """집중하중(node)/등분포하중(element)/사다리꼴하중(element_trapezoid) icon
        buttons, mirroring the 지점 조건 row: picking one swaps the field list
        below (still needs a magnitude typed in and 적용 clicked — unlike 지점
        조건 there is no single value to apply instantly here)."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.load_target_group = QButtonGroup(self)
        self.load_target_group.setExclusive(True)
        self.load_target_keys: dict[int, str] = {}
        for index, (label, tooltip, key, glyph_key) in enumerate(_LOAD_TARGET_OPTIONS):
            button = QToolButton()
            button.setObjectName("supportKindButton")
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIcon(_render_glyph_icon(lambda p, c, k=glyph_key: _paint_load_glyph(p, k, c)))
            button.setIconSize(QSize(22, 22))
            button.setText(label)
            button.setToolTip(tooltip)
            self.load_target_group.addButton(button, index)
            self.load_target_keys[index] = key
            layout.addWidget(button)
        self.load_target_group.button(0).setChecked(True)  # default: 집중하중(node)
        self.load_target_group.idClicked.connect(lambda _index: self._load_target_changed())
        layout.addStretch(1)
        return row

    def _build_result_workspace(self) -> QWidget:
        """The full post-processing workspace, not a bare viewport.

        Reactions, nodal displacements and the N/V/M diagrams all need a table beside
        the picture; the reusable workspace already carries one. Its own RESULT
        TYPES sidebar (반력/변형/변위/N/V/M — and more) is the one place that
        picks what's shown; this page used to also draw its own row of the
        same six buttons above it, which meant two different controls did the
        exact same job stacked on top of each other. Only "모델 편집으로
        돌아가기" stays here — nothing inside ResultsWorkspace itself can get
        back to the canvas, since it doesn't know one exists in the shared
        (OpenSeesPy-import) case.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        tools = QHBoxLayout()
        back = QPushButton("모델 편집으로 돌아가기")
        back.clicked.connect(lambda: self.workspace_stack.setCurrentIndex(0))
        tools.addWidget(back)
        tools.addStretch(1)
        layout.addLayout(tools)
        self.results = ResultsWorkspace()
        self.viewport = self.results.viewport
        layout.addWidget(self.results, 1)
        return page

    def _build_status_bar(self) -> QFrame:
        """The unit selector lives here, not just in the setup wizard's first
        step, because the 2D free-modeling path (``start_2d_model``) skips
        that wizard entirely and jumps straight to the canvas — without this,
        a 2D session had no way to ever leave the kN/m default. Picking a
        unit here only changes what label is printed next to a value (E's
        unit hint, load field tooltips, results) — it does not rescale any
        number already typed in, the same way choosing a unit in the wizard
        never rescaled anything either. It is meant to be set once before
        typing values in a particular unit, not swapped mid-model."""
        bar = QFrame()
        bar.setObjectName("directModelCommandBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        self.model_status = QLabel()
        self.determinacy_status = QLabel("정정성: 모델 작성 중")
        layout.addWidget(self.model_status)
        layout.addStretch(1)
        layout.addWidget(self.determinacy_status)
        layout.addSpacing(16)
        layout.addWidget(QLabel("단위:"))
        self.unit_force = QComboBox()
        self.unit_force.addItems(FORCE_UNITS)
        self.unit_force.setCurrentText(self._unit_system.force)
        self.unit_force.setToolTip(
            "힘의 단위. 라벨만 바뀝니다 — 이미 입력한 숫자는 자동 환산되지 않으니, "
            "모델을 새로 그리기 전에 정해두는 것을 권장합니다."
        )
        self.unit_force.currentTextChanged.connect(self._unit_selector_changed)
        layout.addWidget(self.unit_force)
        self.unit_length = QComboBox()
        self.unit_length.addItems(LENGTH_UNITS)
        self.unit_length.setCurrentText(self._unit_system.length)
        self.unit_length.setToolTip(self.unit_force.toolTip())
        self.unit_length.currentTextChanged.connect(self._unit_selector_changed)
        layout.addWidget(self.unit_length)
        return bar

    def _unit_selector_changed(self) -> None:
        self.set_unit_system(UnitSystem(force=self.unit_force.currentText(), length=self.unit_length.currentText()))

    # --- behaviour ---------------------------------------------------------

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        self.results.set_unit_system(unit_system)
        # Keep the status-bar selectors in sync when the unit system is set from
        # outside (e.g. the 3D wizard's own setup step) instead of by the user
        # picking directly from these combo boxes — blocked so setCurrentText
        # doesn't re-fire currentTextChanged and call back into this method.
        for combo, value in ((self.unit_force, unit_system.force), (self.unit_length, unit_system.length)):
            combo.blockSignals(True)
            combo.setCurrentText(value)
            combo.blockSignals(False)
        self._load_target_changed()
        self._refresh_member_unit_hint()

    def to_project_dict(self) -> dict[str, object]:
        """The canvas's own raw state plus the bits of UI chrome that a
        reopened project should also come back with (unit system) — the
        truss-mode and self-weight toggles read straight off the canvas
        instead of duplicating that state here, since the canvas is what
        ``load_project_dict`` restores from and stays the single source of
        truth for both.
        """
        data = self.canvas.to_dict()
        data["unit_force"] = self._unit_system.force
        data["unit_length"] = self._unit_system.length
        return data

    def load_project_dict(self, data: dict[str, object]) -> None:
        self.canvas.load_dict(data)
        self.set_unit_system(
            UnitSystem(
                force=str(data.get("unit_force", self._unit_system.force)),
                length=str(data.get("unit_length", self._unit_system.length)),
            )
        )
        self.truss_mode_toggle.blockSignals(True)
        self.truss_mode_toggle.setChecked(self.canvas.element_family == "truss")
        self.truss_mode_toggle.blockSignals(False)
        self.self_weight_toggle.blockSignals(True)
        self.self_weight_toggle.setChecked(self.canvas.include_self_weight)
        self.self_weight_toggle.blockSignals(False)
        self.view_results_button.setEnabled(False)
        self.workspace_stack.setCurrentIndex(0)
        self._sync_property_panel()
        self._refresh_status()

    def save_to_file(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_project_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def load_from_file(self, path: Path) -> None:
        self.load_project_dict(json.loads(path.read_text(encoding="utf-8")))

    def solve(self) -> None:
        """Always actually calls the solver — the determinacy check below is
        purely informational (shown in the status bar), never a separate gate
        that blocks the attempt. The only thing that can still refuse to
        produce a result is ``MaterialFreeStaticsSolver`` itself, for exactly
        one reason: an indeterminate structure's internal forces genuinely
        depend on member stiffness, so without real (E, A, I) anywhere (per-
        member, in the 부재 속성 window) there is no physically meaningful
        number to compute — not a redundant check to relax, since removing it
        would mean silently reporting a stiffness-independent guess as if it
        were the real answer for a structure whose real answer depends on
        stiffness. That failure (or any other) still only ever reaches the
        status bar here, never a popup — see ``_solve_completed``.
        """
        if self._solve_thread is not None and self._solve_thread.isRunning():
            return
        model = self.canvas.build_model()
        check = check_determinacy(model)
        self.determinacy_status.setText(f"정정성: {check.message}")
        self.solve_button.setEnabled(False)
        self.analysis_progress.show_running("정정성 해석")
        geometric_nonlinearity = "PDelta" if self.pdelta_toggle.isChecked() else "Linear"
        thread = MaterialFreeSolveThread(
            self._solver, model, geometric_nonlinearity=geometric_nonlinearity
        )
        thread.completed.connect(lambda result: self._solve_completed(model, check, result))
        thread.finished.connect(self._solve_thread_finished)
        self._solve_thread = thread
        thread.start()

    def _solve_completed(self, model, check, result) -> None:
        if result.status.value != "completed":
            # Deliberately no QMessageBox here (unlike the OpenSeesPy-import
            # flow's failure path) - an indeterminate structure with no
            # material set is an expected, everyday state while authoring a
            # model, not an error worth interrupting the user over. The
            # status bar already says why.
            self.analysis_progress.show_failed(
                " ".join(result.messages) or "해석에 실패했습니다."
            )
            self.determinacy_status.setText(
                f"정정성: {check.message}  ·  {' '.join(result.messages)}"
            )
            return
        self.analysis_progress.show_completed(
            f"절점 {len(result.node_results)}개, 부재 {len(result.element_results)}개 결과가 준비되었습니다."
        )
        self.results.set_model(model)
        self.results.show_result(result)
        self.results.set_result_type("reaction")
        self.view_results_button.setEnabled(True)
        self.workspace_stack.setCurrentIndex(1)

    def _solve_thread_finished(self) -> None:
        self.solve_button.setEnabled(True)
        thread = self._solve_thread
        self._solve_thread = None
        if thread is not None:
            thread.deleteLater()

    def solve_modal(self) -> None:
        """Same no-popup, status-bar-only failure philosophy as ``solve()`` -
        modal analysis has real, everyday reasons to fail early while a model is
        still being authored (2D only, needs real E/A/I and unit weight
        everywhere), not just genuine errors."""
        if self._modal_solve_thread is not None and self._modal_solve_thread.isRunning():
            return
        model = self.canvas.build_model()
        self.modal_solve_button.setEnabled(False)
        self.analysis_progress.show_running("모드해석")
        thread = ModalSolveThread(
            self._modal_solver,
            model,
            num_modes=self.modal_num_modes.value(),
            length_unit=self._unit_system.length,
        )
        thread.completed.connect(lambda result: self._modal_solve_completed(model, result))
        thread.finished.connect(self._modal_solve_thread_finished)
        self._modal_solve_thread = thread
        thread.start()

    def _modal_solve_completed(self, model, result) -> None:
        if result.status.value != "completed":
            self.analysis_progress.show_failed(
                " ".join(result.messages) or "모드해석에 실패했습니다."
            )
            self.determinacy_status.setText(f"모드해석: {' '.join(result.messages)}")
            return
        self.analysis_progress.show_completed(f"모드 {len(result.mode_shapes)}개가 계산되었습니다.")
        self.results.set_model(model)
        self.results.show_result(result)
        self.results.set_result_type("mode_shapes")
        self.view_results_button.setEnabled(True)
        self.workspace_stack.setCurrentIndex(1)

    def _modal_solve_thread_finished(self) -> None:
        self.modal_solve_button.setEnabled(True)
        thread = self._modal_solve_thread
        self._modal_solve_thread = None
        if thread is not None:
            thread.deleteLater()

    def _toggle_truss_mode(self, checked: bool) -> None:
        """Only affects members drawn from now on — a truss/frame member is a
        drawing-time choice (pinned both ends vs moment-connected), not a
        property that can be flipped retroactively without redrawing it."""
        self.canvas.element_family = "truss" if checked else "frame"

    def _toggle_self_weight(self, checked: bool) -> None:
        """A solve-time decision, unlike truss mode — it only changes what
        build_model() adds on top of whatever loads are already there, so
        toggling it back and forth freely (no redraw needed) is safe."""
        self.canvas.include_self_weight = checked

    def _enable_3d_mode(self) -> None:
        """Switch this page's canvas from a flat 2D sheet to a freely-orbited
        3D view, once, at construction time.

        2D and 3D are separate work areas (separate ``ModelingInterfacePage``
        instances — see ``start_in_3d``), each with its own canvas, so there is
        no live toggle here and no way back to 2D for a page built this way.
        """
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
        self.level_bar.setVisible(True)
        self.canvas_stack.setCurrentWidget(self.preview_3d_panel)
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
        # A load/support/transform flow narrows the selection filter to just
        # nodes or just members while its top-bar slide-out is open, but
        # nothing ever widened it back — so after using, say, the 부재 load
        # target once, every later click on a node was silently ignored with
        # no visible reason why. Returning to the plain select tool (by
        # clicking it, pressing V, or Escape) is the natural point to widen
        # it back to "everything is clickable again".
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("all"))
        self._set_mode(
            "select",
            "선택 · 클릭 또는 드래그로 선택하고 캔버스 위쪽 막대에서 속성을 적용합니다.",
        )
        self._sync_property_panel()

    def _activate_draw_tool(self) -> None:
        self.draw_tool.setChecked(True)
        self._set_mode(
            "draw",
            "그리기 · 연속 클릭으로 노드와 부재를 함께 만듭니다. "
            "아래 입력칸에 길이·각도를 쳐도 됩니다. Esc로 연결을 끊습니다.",
        )
        self.draw_entry.setFocus()
        self._sync_property_panel()
        self._refresh_draw_readout()

    def _activate_node_transform_tool(self) -> None:
        self.select_tool.setChecked(True)
        self._set_mode("select", "이동·복사·배열할 노드를 선택한 뒤 오른쪽 패널에서 적용하세요.")
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("nodes"))
        self._sync_property_panel()
        self._show_category("move")

    def _activate_support_tool(self) -> None:
        self.select_tool.setChecked(True)
        self._set_mode("select", "지점을 적용할 노드를 선택한 뒤 오른쪽 지점 패널에서 적용하세요.")
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("nodes"))
        self._sync_property_panel()
        self._show_category("support")

    def _activate_load_tool(self) -> None:
        self.select_tool.setChecked(True)
        self._set_mode("select", "하중을 적용할 대상을 선택한 뒤 오른쪽 하중 패널에서 적용하세요.")
        self._sync_property_panel()
        self._load_target_changed()
        self._show_category("load")

    def _selection_changed(self) -> None:
        self._sync_property_panel()
        if (
            self.canvas.ndm == 2
            and self._current_load_target() == "node"
            and self.load_input_mode == "perpendicular"
            and hasattr(self, "load_angle")
        ):
            # Follow the selection: whichever node/member is now selected
            # becomes the new perpendicular-angle reference, silently (no ⚠
            # warning noise on an ordinary click - see the ``silent`` docstring).
            self._fill_angle_perpendicular_to_selected_member(silent=True)
        # A pending (not-yet-applied) preview is keyed to whichever node(s)
        # were selected when it was drawn - once the selection moves on, it
        # either needs to jump to the new node(s) (if the field values are
        # still nonzero) or disappear entirely (nothing selected any more),
        # never linger pointing at a node that isn't selected any more.
        self._update_load_preview()

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
        """Refresh whatever depends on the current selection.

        Which category page is showing never changes here — that is only
        ever up to the category bar buttons. What does need refreshing on
        every selection change is the 부재 page's fields (only meaningful
        once exactly one member is selected), the 노드 유형/지점 icons'
        checked state, the create-section hint (its wording depends on how
        many nodes are selected), and the selection-summary text.
        """
        nodes = len(self.canvas.selected_nodes)
        elements = len(self.canvas.selected_elements)
        member_tag = self._selected_member_tag()
        self._refresh_create_section_hint()
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

        width = element.properties.get("width")
        height = element.properties.get("height")
        elastic = element.properties.get("E")
        density = element.properties.get("density")
        if width is not None and height is not None:
            self.member_width.blockSignals(True)
            self.member_width.setValue(float(width))
            self.member_width.blockSignals(False)
            self.member_height.blockSignals(True)
            self.member_height.setValue(float(height))
            self.member_height.blockSignals(False)
        if elastic is not None:
            self.member_elastic.blockSignals(True)
            self.member_elastic.setValue(float(elastic))
            self.member_elastic.blockSignals(False)
        self.member_density.blockSignals(True)
        self.member_density.setValue(float(density) if density is not None else 0.0)
        self.member_density.blockSignals(False)
        self._refresh_member_section_preview()

    def _refresh_member_section_preview(self) -> None:
        self.member_section_preview.set_dimensions(
            self.member_width.value(), self.member_height.value()
        )

    def _apply_member_section(self) -> None:
        self.canvas.apply_section_to_selection(
            self.member_width.value(),
            self.member_height.value(),
            self.member_elastic.value(),
            self.member_density.value(),
        )

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
        "qx_j": "qx (로컬 x, j단)",
        "qy_j": "qy (로컬 y, j단)",
    }

    def _current_load_target(self) -> str:
        checked_id = self.load_target_group.checkedId()
        return self.load_target_keys.get(checked_id, "node")

    def _load_target_changed(self) -> None:
        """Rebuild the load field list for the current target and dimension.

        Every applicable component gets its own field so one "적용" click sets
        the whole load at once — see ``_build_load_bar_content`` for why that
        matters. 등분포하중(element) is the plain uniform load, one qx/qy pair
        applied to the whole span; 사다리꼴하중(element_trapezoid) is its own
        icon (not a checkbox tucked beside 등분포하중) offering qx_j/qy_j for
        the j-end too, so a linearly-varying load — one end zero gives a
        triangular load — can be entered without the common uniform case ever
        carrying dead fields. Fields are grouped by AXIS, not by end: qx next
        to qx_j, then qy next to qy_j, so the two numbers that describe the
        same direction sit side by side instead of split apart by an
        intervening end-i/end-j boundary. Each is its own ``QFormLayout`` row
        (short "qx"/"Fx" label beside its field, full text kept in the
        tooltip) since this now lives in the 우측 워크트리 panel — a form
        just grows taller as fields are added instead of running out of
        horizontal room.

        Deliberately does NOT narrow ``selection_filter`` to match the target
        (nodes-only for 집중하중, elements-only for 등분포/사다리꼴) — that used
        to happen here, back when 하중 was a modal tool you "activated" and
        later left. Now it is a category page with no "leave this tool" step
        to widen the filter back afterward (the widening only ever happened
        in ``_activate_select_tool``, itself only reachable via
        Escape-from-draw or the rail's 선택 button) — so picking
        an element-only load target here would silently make every later
        click on a node do nothing, with no visible reason why, until the
        user stumbled into one of those unrelated reset paths. 적용 already
        no-ops safely against whatever is selected (see ``_apply_load``), so
        there was never a correctness reason to narrow the filter, only a
        now-stale convenience one from the old modal-tool design.
        """
        if not hasattr(self, "load_form_layout"):
            return
        while self.load_form_layout.count():
            item = self.load_form_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.load_fields.clear()
        target = self._current_load_target()
        trapezoid = target == "element_trapezoid"
        is_node = target == "node"
        # "부재 수직" input only makes sense for a node load in 2D - a member
        # has one unambiguous perpendicular direction only within a plane.
        # 등분포/사다리꼴하중 already work in the member's own local axes
        # (qx/qy), so this mode toggle is meaningless for them too.
        show_mode_toggle = is_node and self.canvas.ndm == 2
        if hasattr(self, "load_mode_toggle"):
            self.load_mode_toggle.setVisible(show_mode_toggle)
        if show_mode_toggle and self.load_input_mode == "perpendicular":
            self._build_perpendicular_load_fields()
        else:
            if is_node:
                components = (
                    self._NODE_LOAD_COMPONENTS_3D if self.canvas.ndm == 3 else self._NODE_LOAD_COMPONENTS_2D
                )
            else:
                components = ("qx", "qx_j", "qy", "qy_j") if trapezoid else ("qx", "qy")
            for component in components:
                field = self._number(0.0)
                field.setRange(-1_000_000.0, 1_000_000.0)
                unit = self._unit_system.moment if component[0] == "m" else self._unit_system.force
                if not is_node:
                    unit = f"{self._unit_system.force}/{self._unit_system.length}"
                self.load_fields[component] = field
                full_label = self._COMPONENT_LABELS[component]
                short_label = full_label.split(" ", 1)[0]
                if trapezoid and component in ("qx", "qy"):
                    short_label += "(i)"
                elif component.endswith("_j"):
                    short_label += "(j)"
                tooltip = f"{full_label} ({unit})"
                if component == "mz":
                    # Sign convention here is deliberately the opposite of the
                    # right-hand-rule value OpenSees itself receives (see
                    # _apply_load and _draw_nodal_load) - typed and displayed as
                    # 시계방향(+)/반시계방향(-), flipped at the boundary so the
                    # solver still gets the physically correct signed moment.
                    tooltip += " — 시계방향(+) / 반시계방향(-)"
                field.setToolTip(tooltip)
                if is_node:
                    field.valueChanged.connect(self._update_load_preview)
                self.load_form_layout.addRow(f"{short_label} ({unit})", field)
        if not is_node:
            self.canvas.set_pending_load_preview(None)

    def _node_load_values(self) -> tuple[float, ...]:
        """Fx/Fy/(Fz/Mx/My/)Mz straight from the load bar's fields, in the
        order ``apply_nodal_load_to_selection``/``NodalLoad`` expect.

        Mz is typed in 시계방향(+)/반시계방향(-) - the opposite of the
        right-hand-rule sign OpenSees itself expects for a moment about +Z -
        so it gets negated right here, once, at the only place a user-typed
        value turns into the values a ``NodalLoad`` actually stores. Shared
        by ``_apply_load`` (commits it) and ``_update_load_preview`` (shows
        it before commit) so the live preview can never disagree with what
        적용 would actually save.
        """
        components = (
            self._NODE_LOAD_COMPONENTS_3D if self.canvas.ndm == 3 else self._NODE_LOAD_COMPONENTS_2D
        )
        return tuple(
            (-self.load_fields[component].value() if component == "mz" else self.load_fields[component].value())
            for component in components
        )

    def _update_load_preview(self) -> None:
        """Live dashed preview of the load bar's fields at the selected
        node(s), refreshed on every keystroke/spin — so an inclined load's
        direction can be checked (and corrected) before 적용 is even
        clicked, instead of only finding out it was wrong after committing."""
        if not self.load_fields or self._current_load_target() != "node":
            return
        self.canvas.set_pending_load_preview(self._node_load_values())

    def _apply_load(self) -> None:
        """A plain click on a node or member (without holding Ctrl) clears
        whatever was already selected — see ``_toggle_selection`` — so it is
        easy to end up with the wrong thing (or nothing) selected right
        before pressing 적용, e.g. after clicking a member to fill the
        수직 각도 and forgetting that this silently dropped the node picked
        a moment earlier. ``apply_nodal_load_to_selection``/
        ``apply_uniform_load_to_selection`` used to no-op in that case with
        no feedback at all, which reads as "the button doesn't work" — this
        now says so instead of doing nothing.
        """
        if self._current_load_target() == "node":
            if not self.canvas.selected_nodes:
                self.selection_summary.setText(
                    "⚠ 선택된 노드가 없어 하중을 적용하지 못했습니다 — 하중을 받을 노드를 "
                    "클릭하세요 (부재를 함께 선택하려면 Ctrl+클릭)."
                )
                return
            self.canvas.apply_nodal_load_to_selection(self._node_load_values())
        else:
            if not self.canvas.selected_elements:
                self.selection_summary.setText(
                    "⚠ 선택된 부재가 없어 하중을 적용하지 못했습니다 — 하중을 받을 부재를 클릭하세요."
                )
                return
            values = (self.load_fields["qx"].value(), self.load_fields["qy"].value())
            if "qx_j" in self.load_fields:
                values += (self.load_fields["qx_j"].value(), self.load_fields["qy_j"].value())
            self.canvas.apply_uniform_load_to_selection(values)
        # A load actually landed - replace any stale ⚠ warning (e.g. from an
        # earlier failed attempt on this same selection) with the normal
        # selection summary, so success doesn't still look like an error.
        self._sync_property_panel()

    def _add_nodes_from_coordinates(self) -> None:
        base_x, base_y = 0.0, 0.0
        if self.node_relative.isChecked() and len(self.canvas.selected_nodes) == 1:
            reference = self.canvas.nodes[next(iter(self.canvas.selected_nodes))]
            base_x, base_y = reference.x, reference.y
        x = base_x + self.node_x.value()
        y = base_y + self.node_y.value()
        self.canvas.begin_history_group()
        try:
            for index in range(self.node_repeat.value()):
                self.canvas.add_node(
                    x + self.node_dx.value() * index,
                    y + self.node_dy.value() * index,
                )
        finally:
            self.canvas.end_history_group()

    def _sync_transform_form(self) -> None:
        """dX/dY relabel to 중심 X/중심 Y for 회전 복사 — same two fields, since
        a rotation's pivot point plays the same "where do I measure from" role
        an offset's dx/dy does, so this reuses them instead of adding a
        separate pair of fields only one operation would ever use. 회전각 is
        the one genuinely new field, shown only for that operation."""
        operation = self.node_transform_operation.currentData()
        is_rotate = operation == "rotate"
        self.node_transform_dx_label.setText("중심 X" if is_rotate else "dX")
        self.node_transform_dy_label.setText("중심 Y" if is_rotate else "dY")
        self.node_transform_form.setRowVisible(self.node_transform_angle, is_rotate)
        self.node_transform_repeat.setEnabled(operation in {"copy", "array", "rotate"})

    def _apply_node_transform(self) -> None:
        operation = self.node_transform_operation.currentData()
        if operation == "array":
            self.canvas.array_copy_selection(
                self.node_transform_dx.value(),
                self.node_transform_dy.value(),
                self.node_transform_repeat.value(),
            )
            return
        if operation == "rotate":
            self.canvas.rotate_copy_selection(
                self.node_transform_dx.value(),
                self.node_transform_dy.value(),
                self.node_transform_angle.value(),
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
    def _section(title: str, *, show_title: bool = True) -> tuple[QWidget, QVBoxLayout]:
        """A white card on the panel's tinted background (propertySectionCard),
        so several always-on sections stacked together read as distinct blocks
        instead of one long list of bold labels. ``show_title=False`` is for
        ``create``, whose external toggle button already carries the heading —
        repeating it inside the card the button opens would just be noise."""
        section = QFrame()
        section.setObjectName("propertySectionCard")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)
        if show_title:
            label = QLabel(title)
            label.setObjectName("setupSectionTitle")
            layout.addWidget(label)
        return section, layout

    @staticmethod
    def _number(value: float) -> QDoubleSpinBox:
        field = SafeDoubleSpinBox()
        field.setRange(-1_000_000.0, 1_000_000.0)
        # High enough that typing precision is never the limit; SafeDoubleSpinBox's
        # textFromValue trims the trailing zeros this would otherwise show.
        field.setDecimals(10)
        field.setValue(value)
        return field
