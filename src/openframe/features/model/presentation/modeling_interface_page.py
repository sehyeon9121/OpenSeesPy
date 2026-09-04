"""Free-form authoring surface for 2D structural-mechanics models.

The layout keeps the canvas dominant: a narrow tool rail on the left (only
선택/그리기 — the two modes a click on the canvas can mean), a coordinate
entry strip under the canvas, a category editor column further left
(``_build_2d_editor_panel``), and a Work Tree/Selection Status inspector on
the right (``_build_selection_panel``). A single-row category bar above
the canvas (``_build_category_bar`` — 노드 추가/이동/노드
분할/지점/노드 유형/부재/하중) picks which category's settings the
editor column shows; nothing is pinned there any more, so it is empty
until a category is picked and shows exactly one at a time. The editor
and Selection Status used to share one vertical splitter on the right,
which read as a single cluttered panel — separating them onto their own
columns mirrors the 3D workbench's tools-left/status-right split. Only
selecting and drawing are tools; everything else — supports, hinges,
loads — is a property page one click away, so adding a new kind of object
never adds another mode to learn, just another category button.
"""

import json
import math
import re
import tempfile
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from openframe.app.shell.analysis_progress_banner import AnalysisProgressBanner
from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    FORCE_UNITS,
    LENGTH_UNITS,
    AnalysisKind,
    AnalysisRequest,
    AnalysisResult,
    AnalysisStatus,
    FloorLoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoadEntry,
    SeismicLoadParameters,
    SelfWeightEntry,
    StoryWeight,
    UnitSystem,
    WindLoadParameters,
    design_spectral_accelerations,
    equivalent_lateral_force,
    lumped_node_weights,
    mpa_to_stress_unit,
    seismic_response_coefficient,
    unit_conversion_factors,
    wind_force_by_story,
)
from openframe.features.analysis.application.run_analysis import RunAnalysisService
from openframe.features.analysis.presentation.analysis_run_thread import AnalysisRunThread
from openframe.features.analysis.presentation.analysis_settings_panel import AnalysisSettingsPanel
from openframe.features.analysis.statics import (
    MaterialFreeSolveThread,
    MaterialFreeStaticsSolver,
    NonlinearStaticSolveThread,
    check_determinacy,
    export_opensees_script,
)
from openframe.features.model.drawing import PlaneKind
from openframe.features.model.drawing.coordinates import direction_degrees
from openframe.features.model.presentation.analysis_case_store import AnalysisCaseStore
from openframe.features.model.presentation.analysis_settings_dialogs import AnalysisSettingsDialog
from openframe.features.model.presentation.analysis_settings_sidebar import AnalysisSettingsSidebar
from openframe.features.model.presentation.canvas_glyphs import (
    _LOAD_TARGET_OPTIONS,
    _SUPPORT_OPTIONS,
    _SUPPORT_OPTIONS_3D,
    DOF_LEGEND,
    _paint_load_glyph,
    _paint_node_kind_glyph,
    _paint_ribbon_glyph,
    _paint_support_glyph,
    _render_dof_icon,
    _render_glyph_icon,
    _render_load_diagram,
)
from openframe.features.model.presentation.current_page_only_stack import _CurrentPageOnlyStack
from openframe.features.model.presentation.modeling_3d_input import _Modeling3DInputMixin
from openframe.features.model.presentation.modeling_load3d import _Load3DPanelMixin
from openframe.features.model.presentation.modeling_tree_roles import (
    _TREE_DEFINITION_ROLE,
    _TREE_ENTITY_ROLE,
)
from openframe.features.model.presentation.modeling_work_tree import _WorkTreeMixin
from openframe.features.model.presentation.floor_load_type_manager_dialog import (
    FloorLoadTypeManagerDialog,
)
from openframe.features.model.presentation.load_case_manager_dialog import LoadCaseManagerDialog
from openframe.features.model.presentation.load_combination_manager_dialog import (
    LoadCombinationManagerDialog,
)
from openframe.features.model.presentation.model_sidebar import LOAD_CASE_PRESENTATION
from openframe.features.model.presentation.safe_spinbox import (
    DownwardComboBox,
    SafeComboBox,
    SafeDoubleSpinBox,
    SafeSpinBox,
)
from openframe.features.model.presentation.section_material_panel import SectionMaterialPanel
from openframe.features.model.presentation.selection_status_panel import SelectionStatusPanel
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
from openframe.features.model.presentation.story_manager_dialog import StoryManagerDialog
from openframe.features.results.presentation.results_workspace import ResultsWorkspace
from openframe.features.viewport.items.support_item import SUPPORT_NAMES
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport


class ModelingInterfacePage(
    # Mixins first: eventFilter lives on _Modeling3DInputMixin and must beat
    # QFrame's own (do-nothing) version, same MRO reason as StaticsDrawingCanvas.
    _Modeling3DInputMixin,
    _WorkTreeMixin,
    _Load3DPanelMixin,
    QFrame,
):
    """One-screen workflow: draw, inspect, assign conditions, and review results."""

    #: Emitted with the saved script's path once "정밀해석으로 내보내기" writes
    #: it - the canvas's own solvers stop at determinate statics/eigenvalue
    #: analysis, so unlocking nonlinear static/time history means handing the
    #: model to the "OpenSeesPy 파일 불러오기" pipeline instead. A parent
    #: workspace (outside this page's own reach) is the one that actually
    #: opens it there.
    analysis_script_exported = Signal(Path)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        start_in_3d: bool = False,
        run_analysis_service: RunAnalysisService | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("modelingInterfacePage")
        self._start_in_3d = start_in_3d
        self._run_analysis_service = run_analysis_service
        self._analysis_run_thread: AnalysisRunThread | None = None
        self._analysis_temp_script: Path | None = None
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._model_name = "New 3D Model" if start_in_3d else "New 2D Model"
        self._vertical_axis = "Z" if start_in_3d else "Y"
        self._gravity_direction = "-Z" if start_in_3d else "-Y"
        self._gravity_acceleration = 9.81
        self._user_materials: list[dict[str, object]] = []
        self._user_sections: list[dict[str, object]] = []
        # The Element tab's "what the next drawn member gets" pick. It stays
        # None until both a saved material and section are selected; 2D may
        # keep drawing with its defaults while 3D requires an explicit pair.
        self._active_element_kwargs: dict[str, object] | None = None
        self._known_2d_element_tags: set[int] = set()
        self._applying_2d_active_properties = False
        self._solver = MaterialFreeStaticsSolver()
        self._solve_thread: MaterialFreeSolveThread | None = None
        self.analysis_progress = AnalysisProgressBanner(self)
        self.analysis_progress.cancel_requested.connect(self._cancel_full_analysis)
        self.canvas = StaticsDrawingCanvas()
        # Default 집중하중 input mode - plain Fx/Fy, same as every other axis
        # field in this app; "부재 수직" (magnitude+auto-angle, see
        # ``_build_perpendicular_load_fields``) is an opt-in toggle for when
        # the load is naturally given relative to a sloped member instead.
        self.load_input_mode = "component"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # 2D and 3D share one authoring shell. Dimension-specific behaviour
        # lives inside the pages, not in a second navigation system.
        root.addWidget(self._build_3d_workbench_bar())
        self.page_header = self._build_header()
        # The 3D workbench already has the document tabs and its own model
        # settings entry.  Keeping the 2D-style title/action header beneath
        # that ribbon created a third, unrelated toolbar row and pushed the
        # viewport noticeably below the Stitch reference.
        self.page_header.setVisible(not self._start_in_3d)
        root.addWidget(self.page_header)

        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(self._build_modeling_workspace())
        self.workspace_stack.addWidget(self._build_result_workspace())
        root.addWidget(self.workspace_stack, 1)
        if self._start_in_3d:
            self.model_settings_dialog = self._build_model_settings_dialog()
        self.footer_stack = QStackedWidget()
        self.footer_stack.setObjectName("direct2DFooterStack")
        self.footer_stack.addWidget(self._build_status_bar())
        self.footer_stack.addWidget(self._build_result_status_bar())
        root.addWidget(self.footer_stack)
        self.workspace_stack.currentChanged.connect(self.footer_stack.setCurrentIndex)
        self.workspace_stack.currentChanged.connect(self._workspace_page_changed)

        self.canvas.model_changed.connect(self._refresh_status)
        if not self._start_in_3d:
            self.canvas.model_changed.connect(self._apply_active_properties_to_new_2d_members)
        self.canvas.model_changed.connect(self._refresh_work_tree)
        if self._start_in_3d:
            # Every Load Case/Load Entry/Load Combination mutation emits this
            # signal (canvas_load_entries.py) - not just the add/update path
            # _commit_load3d_entry already refreshes directly, but also
            # delete/duplicate/hide/move/rename/delete-case, none of which
            # otherwise touch the viewport.
            self.canvas.load_state_changed.connect(self._refresh_load3d_viewport)
        self.canvas.draw_state_changed.connect(self._refresh_draw_readout)
        self.canvas.selection_changed.connect(self._selection_changed)
        self.canvas.property_drop_requested.connect(self._apply_property_drop)
        self.canvas.escape_requested.connect(self._activate_select_tool)
        self.preview_3d.plane_point_picked.connect(self._on_3d_plane_picked)
        self.preview_3d.node_picked.connect(self._on_3d_node_picked)
        self.preview_3d.member_picked.connect(self._on_3d_member_picked)
        if self._start_in_3d:
            # The chain-drawing preview line tracks self.canvas's own state
            # (chain_last_node), so any change to it - a point committed, the
            # chain broken, the tool switched away - has to drop the stale
            # rubber-band rather than leave it pointing at a segment that no
            # longer exists. The very next hover redraws it if a chain is
            # still open.
            self.canvas.draw_state_changed.connect(self._on_3d_draw_state_changed)
            self.preview_3d.node_hovered.connect(self._on_3d_node_hovered)
            self.preview_3d.plane_point_hovered.connect(self._on_3d_plane_hovered)
            self.preview_3d.hover_cleared.connect(self._on_3d_hover_cleared)
            self.preview_3d.selection_box_finished.connect(self._on_3d_box_selected)
            self.preview_3d.empty_space_clicked.connect(self.canvas.clear_selection)
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
        if self._start_in_3d:
            # self.canvas stays hidden in 3D mode, so it can never hold
            # keyboard focus and the shortcut above never fires while the
            # user is actually looking at (and clicking in) preview_3d - a
            # second copy scoped to the 3D viewport itself covers that.
            self.draw_space_shortcut_3d = QShortcut(
                QKeySequence(Qt.Key.Key_Space), self.preview_3d
            )
            self.draw_space_shortcut_3d.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            self.draw_space_shortcut_3d.activated.connect(self._activate_draw_tool)
            # Same reason as draw_space_shortcut_3d above: Delete/Ctrl+Z/Ctrl+Y
            # scoped only to self.canvas never fire once the user is actually
            # clicking around in preview_3d, since the hidden canvas can't
            # hold focus - so a node or member selected via the 3D viewport's
            # own drag-box could be selected but never deleted/undone.
            for standard, slot in (
                (QKeySequence.StandardKey.Delete, self.canvas.delete_selected),
                (QKeySequence.StandardKey.Undo, self.canvas.undo),
                (QKeySequence.StandardKey.Redo, self.canvas.redo),
            ):
                shortcut_3d = QShortcut(standard, self.preview_3d)
                shortcut_3d.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                shortcut_3d.activated.connect(slot)
            # Entering draw mode moves keyboard focus to the length/angle
            # entry, so Escape must be scoped to the whole 3D modeling page,
            # not only to preview_3d (which no longer owns focus at that point).
            self.escape_shortcut_3d = QShortcut(
                QKeySequence(Qt.Key.Key_Escape), self
            )
            self.escape_shortcut_3d.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            self.escape_shortcut_3d.activated.connect(self._handle_escape_shortcut_3d)
            # QLineEdit consumes Escape before a QShortcut in some Qt
            # platform plugins.  These are the two widgets that can own focus
            # during 3D drawing, so filter them as a deterministic fallback.
            self.preview_3d.quick_widget.installEventFilter(self)
            self.draw_entry.installEventFilter(self)
            # MIDAS-style "Active Only" view isolation: F2 hides everything
            # except the current selection (e.g. one story's nodes/members),
            # Ctrl+A shows the whole model again. Scoped to the whole page,
            # same reason as escape_shortcut_3d above - the selection can be
            # made either on the hidden 2D canvas or by dragging a box in
            # preview_3d itself, and either way the shortcut has to fire
            # regardless of which of them currently owns focus.
            self.isolate_shortcut_3d = QShortcut(QKeySequence(Qt.Key.Key_F2), self)
            self.isolate_shortcut_3d.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.isolate_shortcut_3d.activated.connect(self._isolate_selection_3d)
            self.show_all_shortcut_3d = QShortcut(QKeySequence("Ctrl+A"), self)
            self.show_all_shortcut_3d.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.show_all_shortcut_3d.activated.connect(self.preview_3d.clear_isolate)
        self.fit_shortcut = QShortcut(QKeySequence("F"), self.canvas)
        self.fit_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.fit_shortcut.activated.connect(self.canvas.fit_model)

        if self._start_in_3d:
            self._enable_3d_mode()
        self._activate_workbench_tab("model", show_settings=False)
        self._activate_select_tool()
        self._refresh_status()

    # --- layout ------------------------------------------------------------

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("direct2DPageHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.page_title = QLabel(
            "3D Structure Model" if self._start_in_3d else "2D Structure Model"
        )
        self.page_title.setObjectName("direct2DPageTitle")
        self.page_description = QLabel(
            "Create geometry, assign structural properties, boundary conditions and loads."
        )
        self.page_description.setObjectName("direct2DPageDescription")
        text.addWidget(self.page_title)
        text.addWidget(self.page_description)
        layout.addLayout(text)
        layout.addStretch(1)

        self.header_controls_stack = QStackedWidget()
        self.header_controls_stack.setObjectName("direct2DHeaderControls")
        self.header_controls_stack.addWidget(self._build_model_header_controls())
        self.header_controls_stack.addWidget(self._build_result_header_controls())
        layout.addWidget(self.header_controls_stack)

        return header

    def _build_model_header_controls(self) -> QWidget:
        controls = QWidget()
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        model_type = QVBoxLayout()
        model_type.setSpacing(2)
        model_type_label = QLabel("MODEL TYPE")
        model_type_label.setObjectName("direct2DFieldLabel")
        model_type.addWidget(model_type_label)
        self.model_type_selector = QComboBox()
        self.model_type_selector.setObjectName("direct2DModelType")
        if self._start_in_3d:
            self.model_type_selector.addItem("3D Frame", "frame")
        else:
            self.model_type_selector.addItem("2D Frame", "frame")
            self.model_type_selector.addItem("2D Truss", "truss")
            self.model_type_selector.currentIndexChanged.connect(
                self._model_type_changed
            )
        model_type.addWidget(self.model_type_selector)
        layout.addLayout(model_type)

        self.model_ready_badge = QLabel("●  READY FOR ANALYSIS")
        self.model_ready_badge.setObjectName("direct2DReadyBadge")
        layout.addWidget(self.model_ready_badge)

        # This toggle is created here so its public attribute and solver
        # wiring remain unchanged, then placed in the bottom analysis strip.
        self.truss_mode_toggle = QPushButton("트러스 모드")
        self.truss_mode_toggle.setObjectName("modelingToggleButton")
        self.truss_mode_toggle.setCheckable(True)
        self.truss_mode_toggle.setToolTip(
            "켜면 이제부터 그리는 부재가 양단 힌지로 연결된 트러스 부재(축력만 전달)로 "
            "그려집니다. 해석 후에는 부재마다 축력 값이 하나씩 표시됩니다."
        )
        self.truss_mode_toggle.toggled.connect(self._toggle_truss_mode)
        self.truss_mode_toggle.hide()
        self.self_weight_toggle = QCheckBox("자중 포함")
        self.self_weight_toggle.setToolTip(
            "켜면 해석 시 부재 단위중량(부재 창의 \"단위중량 ρ\")과 단면적으로 계산한 "
            "자중을 등분포하중처럼 더합니다. 단위중량을 입력하지 않은 부재는 빠집니다."
        )
        self.self_weight_toggle.toggled.connect(self._toggle_self_weight)
        self.export_analysis_button = QPushButton("정밀해석으로 내보내기…")
        self.export_analysis_button.setObjectName("direct2DSecondaryButton")
        self.export_analysis_button.setToolTip(
            "이 모델을 실행 가능한 OpenSeesPy 스크립트(.py)로 저장하고, "
            "\"OpenSeesPy 파일 불러오기\" 화면에서 엽니다 - 비선형정적·시간이력·"
            "고유치(모드)·P-Delta 등 이 캔버스의 자체 솔버가 지원하지 않는 정밀 "
            "해석을 그대로 돌릴 수 있습니다. 2D 모델만 가능하며, 모든 부재에 실제 "
            "재료·단면이 필요합니다."
        )
        self.export_analysis_button.clicked.connect(self._export_for_full_analysis)
        layout.addWidget(self.export_analysis_button)
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
        self.view_results_button.setObjectName("directModelOpenButton")
        self.view_results_button.setEnabled(False)
        self.view_results_button.clicked.connect(
            lambda: self.workspace_stack.setCurrentIndex(1)
        )
        return controls

    def _build_result_header_controls(self) -> QWidget:
        controls = QWidget()
        layout = QHBoxLayout(controls)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        # RESULT CASE lives once in ResultsWorkspace.toolbar - duplicating it
        # here made the results chrome feel padded and toy-like.
        back = QPushButton("BACK TO MODEL")
        back.setObjectName("direct2DSecondaryButton")
        back.clicked.connect(lambda: self.workspace_stack.setCurrentIndex(0))
        layout.addWidget(back)
        rerun = QPushButton("RE-RUN ANALYSIS")
        rerun.setObjectName("direct2DPrimaryButton")
        rerun.clicked.connect(self.solve)
        layout.addWidget(rerun)
        return controls

    #: Tab order mirrors the actual modeling workflow (place geometry → give
    #: it material/section → support it → load it → analyze → read results)
    #: instead of an arbitrary grouping, so the top bar itself reads as the
    #: sequence of steps rather than a menu.
    _WORKBENCH_TABS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("model", "Model"),
        ("node", "Node"),
        ("properties", "Properties"),
        ("element", "Element"),
        ("boundary", "Supports"),
        ("story", "Story"),
        ("loads", "Loads"),
        ("analysis", "Analysis"),
        ("results", "Results"),
    )

    _WORKBENCH_CATEGORIES: ClassVar[dict[str, tuple[str, ...]]] = {
        "model": (),
        "node": (
            "add",
            "translate_node",
            "rotate_node",
            "mirror_node",
            "arch",
            "kind",
        ),
        "properties": ("member",),
        "element": ("element_picker", "move", "rotate", "mirror"),
        "boundary": ("support",),
        "story": ("story",),
        "loads": ("load",),
        "analysis": ("analysis",),
        "results": (),
    }

    def _build_3d_workbench_bar(self) -> QFrame:
        """The shared 2D/3D row of document-work tabs directly under the
        application header — Model/Node/Properties/Element/Supports/Story/
        Loads/Analysis/Results. Order follows how a building model is built:
        geometry → material/section → supports → stories/diaphragms → loads →
        analyze → results. A tab click both picks which form the left dock
        shows (``_activate_workbench_tab``) and switches the canvas tool that
        step needs.
        """
        bar = QFrame()
        bar.setObjectName("modelingWorkbenchBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 12, 0)
        layout.setSpacing(8)

        self.workbench_group = QButtonGroup(self)
        self.workbench_group.setExclusive(True)
        self.workbench_buttons: dict[str, QToolButton] = {}
        for index, (key, label) in enumerate(self._WORKBENCH_TABS):
            button = QToolButton()
            button.setObjectName("workbenchTab")
            button.setText(label)
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, tab=key: self._activate_workbench_tab(tab)
            )
            self.workbench_group.addButton(button, index)
            self.workbench_buttons[key] = button
            layout.addWidget(button)
            # In 2D, material and section authoring is part of Element itself.
            # Keeping a second Properties destination made the same member
            # assignment look like a multi-step save/select/apply workflow.
            if not self._start_in_3d and key == "properties":
                button.hide()
        layout.addStretch(1)

        # 선택/Member (Node 탭이 그리기 모드로 자동 전환하는 것과 별개로) stay
        # as real objects — every tool activator in this class still flips
        # their checked state (``_activate_select_tool``/``_activate_draw_
        # tool``) and V/L/Space keep working as shortcuts — they are just no
        # longer shown as their own ribbon row.
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.select_tool = self._ribbon_mode_button(
            "선택", "V", "select", self._activate_select_tool
        )
        self.draw_tool = self._ribbon_mode_button(
            "Member",
            "L / Space · 연속 클릭으로 부재를 그립니다",
            "member",
            self._activate_draw_tool,
        )
        return bar

    def _ribbon_icon_button(self, label: str, tooltip: str, glyph_key: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ribbonToolButton")
        button.setText(label)
        button.setToolTip(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # "node_kind" reuses the 노드 유형 category's own rigid-joint glyph
        # (see 지점/노드 유형 icon rows) instead of ``_paint_ribbon_glyph`` -
        # a button that opens that exact category should look like it.
        if glyph_key == "node_kind":
            paint = lambda p, c: _paint_node_kind_glyph(p, False, c)
        else:
            paint = lambda p, c, k=glyph_key: _paint_ribbon_glyph(p, k, c)
        button.setIcon(_render_glyph_icon(paint))
        button.setIconSize(QSize(22, 22))
        return button

    def _ribbon_mode_button(
        self, label: str, tooltip: str, glyph_key: str, slot
    ) -> QToolButton:
        button = self._ribbon_icon_button(label, tooltip, glyph_key)
        button.setCheckable(True)
        button.clicked.connect(slot)
        self.tool_group.addButton(button)
        return button

    def _build_3d_left_panel(self) -> QStackedWidget:
        """Shared contextual authoring dock, hidden until a tool needs settings.

        Global model settings already have their focused dialog and the
        workbench tabs expose material/section/support/load entry points.
        Keeping a second model-navigation tree permanently visible only
        duplicated those controls and reduced the modeling viewport.
        """
        stack = QStackedWidget()
        stack.setObjectName("modelingLeftDock")
        # QStackedWidget is a plain QWidget, which Qt never paints
        # stylesheet border/background for unless this attribute is set
        # (only QFrame and its subclasses do that automatically) - without
        # it, theme.py's "QStackedWidget#modelingLeftDock { border-right:
        # 1px solid #c4c5d5; }" is defined but silently never rendered,
        # which is why the boundary with the canvas looked unstyled while
        # the matching one on the Work Tree side (a QFrame) did not.
        stack.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        stack.setFixedWidth(320)
        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(True)
        self.category_buttons: dict[str, QToolButton] = {}
        # Compatibility actions for code paths that address a modeling
        # category directly. They are intentionally not laid out: the
        # visible navigation is the shared workbench + Node/Element picker.
        for index, (key, label) in enumerate(self._CATEGORY_OPTIONS):
            action = QToolButton(stack)
            action.setText(label)
            action.setCheckable(True)
            action.hide()
            action.clicked.connect(
                lambda _checked=False, i=index: self._show_category_by_index(i)
            )
            self.category_group.addButton(action, index)
            self.category_buttons[key] = action
        self._editor_scroll = self._build_editor_scroll()
        self.left_editor_index = stack.addWidget(self._editor_scroll)
        stack.setCurrentIndex(self.left_editor_index)
        stack.hide()
        self.left_panel_stack = stack
        return stack

    def _save_user_material(self, definition: dict[str, object]) -> None:
        material = dict(definition)
        name = str(material.get("name", "")).strip()
        if not name:
            return
        existing = next(
            (entry for entry in self._user_materials if entry.get("name") == name), None
        )
        if existing is None:
            material["id"] = f"MAT-{len(self._user_materials) + 1:03d}"
            self._user_materials.append(material)
        else:
            material["id"] = existing["id"]
            existing.clear()
            existing.update(material)
        self._refresh_work_tree()
        self.determinacy_status.setText(f"물성 '{name}'을 워크트리에 저장했습니다.")

    def _save_user_section(self, definition: dict[str, object]) -> None:
        section = dict(definition)
        name = str(section.get("name", "")).strip()
        if not name:
            return
        existing = next(
            (entry for entry in self._user_sections if entry.get("name") == name), None
        )
        if existing is None:
            section["id"] = f"SEC-{len(self._user_sections) + 1:03d}"
            self._user_sections.append(section)
        else:
            section["id"] = existing["id"]
            existing.clear()
            existing.update(section)
        self._refresh_work_tree()
        self.determinacy_status.setText(f"섹션 '{name}'을 워크트리에 저장했습니다.")

    def _refresh_element_property_selectors(self) -> None:
        if not hasattr(self, "element_material_selector"):
            return
        previous_material = self.element_material_selector.currentData()
        previous_section = self.element_section_selector.currentData()
        for combo, placeholder, definitions, previous in (
            (
                self.element_material_selector,
                "Material 선택…",
                self._user_materials,
                previous_material,
            ),
            (
                self.element_section_selector,
                "Section 선택…",
                self._user_sections,
                previous_section,
            ),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(placeholder, None)
            for definition in definitions:
                combo.addItem(
                    f"{definition.get('id', '')} : {definition.get('name', '')}",
                    definition.get("id"),
                )
            index = combo.findData(previous)
            combo.setCurrentIndex(max(index, 0))
            combo.blockSignals(False)
        self._element_property_selection_changed()

    def _inspector_card(self, title: str) -> tuple[QFrame, QFormLayout]:
        card = QFrame()
        card.setObjectName("inspectorCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        header = QLabel(title)
        header.setObjectName("inspectorCardHeader")
        card_layout.addWidget(header)
        body = QWidget()
        body.setObjectName("inspectorCardBody")
        form = QFormLayout(body)
        form.setContentsMargins(12, 10, 12, 10)
        form.setSpacing(8)
        card_layout.addWidget(body)
        return card, form

    def _build_member_info_card(self) -> QWidget:
        """일반/그룹 info for whichever single member is selected — Start/End
        Node and Length are read-only (this app has no "reconnect a member's
        endpoints" operation to back an editable field with, unlike the
        reference mock's own text inputs), and 그룹 is the same live-derived
        Columns/Beams split the 모델 탐색기 tree counts, just for this one
        member. Actual editing (단면/재료/힌지) stays exactly where it already
        was, inside ``category_stack``'s 부재 page — this card sits above it.
        """
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        general, general_form = self._inspector_card("일반 (Member)")
        self.member_start_node_label = QLabel()
        general_form.addRow("Start Node", self.member_start_node_label)
        self.member_end_node_label = QLabel()
        general_form.addRow("End Node", self.member_end_node_label)
        self.member_length_label = QLabel()
        general_form.addRow("Length", self.member_length_label)
        root.addWidget(general)

        group, group_form = self._inspector_card("그룹")
        self.member_group_label = QLabel()
        group_form.addRow("Group", self.member_group_label)
        root.addWidget(group)
        return container

    def _update_member_info_card(self, member_tag: int | None) -> None:
        card = getattr(self, "member_info_card", None)
        if card is None:
            return
        if member_tag is None:
            card.setVisible(False)
            return
        element = self.canvas.elements[member_tag]
        start = self.canvas.nodes[element.node_i]
        end = self.canvas.nodes[element.node_j]
        length = math.dist((start.x, start.y, start.z), (end.x, end.y, end.z))
        is_column = abs(start.x - end.x) < 1.0e-6 and abs(start.y - end.y) < 1.0e-6
        self.member_start_node_label.setText(f"N{element.node_i}")
        self.member_end_node_label.setText(f"N{element.node_j}")
        self.member_length_label.setText(f"{length:.3f} {self._unit_system.length}")
        self.member_group_label.setText("Columns" if is_column else "Beams")
        card.setVisible(True)

    def _build_model_settings_card(self) -> QWidget:
        """모델 설정 as an always-in-place inspector page instead of the
        modal dialog this replaces — General/Environment mirror
        ``ModelSettingsDialog``'s old fields exactly (see git history), and
        OpenSees Tcl is new: a live one-line preview of the ``ops.model(...)``
        call these settings will produce, refreshed on every apply.
        """
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        general, general_form = self._inspector_card("GENERAL")
        self.model_name_field = QLineEdit(self._model_name)
        general_form.addRow("Model Name", self.model_name_field)
        self.model_type_field = QComboBox()
        self.model_type_field.addItem("3D 프레임", "frame")
        general_form.addRow("Model Type", self.model_type_field)
        root.addWidget(general)

        environment, env_form = self._inspector_card("ENVIRONMENT")
        dof_column = QVBoxLayout()
        dof_column.setSpacing(2)
        self.dof_field = QComboBox()
        self.dof_field.addItem("6", 6)
        self.dof_field.setEnabled(False)
        dof_column.addWidget(self.dof_field)
        dof_caption = QLabel("UX, UY, UZ, RX, RY, RZ")
        dof_caption.setObjectName("inspectorFieldCaption")
        dof_column.addWidget(dof_caption)
        env_form.addRow("Degrees of\nFreedom", dof_column)

        units_row = QHBoxLayout()
        self.force_unit_field = QComboBox()
        self.force_unit_field.addItems(FORCE_UNITS)
        units_row.addWidget(self.force_unit_field)
        self.length_unit_field = QComboBox()
        self.length_unit_field.addItems(LENGTH_UNITS)
        units_row.addWidget(self.length_unit_field)
        env_form.addRow("Units", units_row)

        self.vertical_axis_field = QComboBox()
        self.vertical_axis_field.addItems(("Z", "Y"))
        env_form.addRow("Vertical Axis", self.vertical_axis_field)

        gravity_row = QHBoxLayout()
        self.gravity_acceleration_field = QDoubleSpinBox()
        self.gravity_acceleration_field.setRange(-100.0, 100.0)
        self.gravity_acceleration_field.setDecimals(4)
        self.gravity_acceleration_field.setValue(-self._gravity_acceleration)
        gravity_row.addWidget(self.gravity_acceleration_field)
        self.gravity_direction_field = QComboBox()
        self.gravity_direction_field.addItems(("-Z", "+Z", "-Y", "+Y"))
        self.gravity_direction_field.setCurrentText(self._gravity_direction)
        gravity_row.addWidget(self.gravity_direction_field)
        env_form.addRow("Gravity", gravity_row)
        root.addWidget(environment)

        tcl_card = QFrame()
        tcl_card.setObjectName("inspectorCard")
        tcl_layout = QVBoxLayout(tcl_card)
        tcl_layout.setContentsMargins(0, 0, 0, 0)
        tcl_layout.setSpacing(0)
        tcl_header = QLabel("OPENSEES TCL")
        tcl_header.setObjectName("inspectorCardHeader")
        tcl_layout.addWidget(tcl_header)
        self.opensees_tcl_preview = QLabel()
        self.opensees_tcl_preview.setObjectName("modelSettingsCommandPreview")
        self.opensees_tcl_preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.opensees_tcl_preview.setWordWrap(True)
        tcl_layout.addWidget(self.opensees_tcl_preview)
        root.addWidget(tcl_card)

        apply_button = QPushButton("설정 적용")
        apply_button.setObjectName("setupContinueButton")
        apply_button.clicked.connect(self._apply_model_settings_and_close)
        root.addWidget(apply_button)
        root.addStretch(1)

        self.model_type_field.setEnabled(not self.canvas.elements)
        self._refresh_opensees_tcl_preview()
        return page

    def _build_model_settings_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setObjectName("modelSettingsDialog")
        dialog.setWindowTitle("모델 설정")
        dialog.setModal(True)
        dialog.setMinimumWidth(480)
        dialog.setMaximumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel("모델 설정")
        title.setObjectName("modelSettingsDialogTitle")
        layout.addWidget(title)
        hint = QLabel("3D 모델 공간, 단위계와 중력 방향을 설정합니다.")
        hint.setObjectName("setupSectionHint")
        layout.addWidget(hint)
        layout.addWidget(self._build_model_settings_card())
        dialog.adjustSize()
        return dialog

    def _show_model_settings_dialog(self) -> None:
        dialog = self.model_settings_dialog
        dialog.adjustSize()
        dialog.open()

    def _apply_model_settings_and_close(self) -> None:
        self._apply_model_settings_inline()
        self.model_settings_dialog.accept()

    def _refresh_opensees_tcl_preview(self) -> None:
        label = getattr(self, "opensees_tcl_preview", None)
        if label is not None:
            label.setText("ops.model('basic', '-ndm', 3, '-ndf', 6)")

    def _apply_model_settings_inline(self) -> None:
        self._model_name = self.model_name_field.text().strip() or "New 3D Model"
        self._vertical_axis = self.vertical_axis_field.currentText()
        self._gravity_direction = self.gravity_direction_field.currentText()
        self._gravity_acceleration = -self.gravity_acceleration_field.value()
        self.set_unit_system(
            UnitSystem(
                force=self.force_unit_field.currentText(),
                length=self.length_unit_field.currentText(),
            )
        )
        self._refresh_model_settings_summary()
        self._refresh_opensees_tcl_preview()
        self.determinacy_status.setText("모델 설정을 적용했습니다.")

    def _activate_workbench_tab(self, key: str, *, show_settings: bool = True) -> None:
        if key not in self.workbench_buttons:
            return
        self.workbench_buttons[key].setChecked(True)
        self.node_subcategory_row.setVisible(key == "node")
        self.element_subcategory_row.setVisible(key == "element")
        if not self._start_in_3d:
            self.page_header.setVisible(key == "model")
        if hasattr(self, "load_task_bar"):
            self.load_task_bar.setVisible(key == "loads")
        if hasattr(self, "right_panel_stack"):
            self.right_panel_stack.setCurrentIndex(
                self.right_panel_pages["load_inspector" if key == "loads" else "default"]
            )

        if key == "model":
            if self.workspace_stack.currentIndex() != 0:
                self.workspace_stack.setCurrentIndex(0)
            self.left_panel_stack.hide()
            if self._start_in_3d and show_settings:
                self._show_model_settings_dialog()
            else:
                self._activate_select_tool()
            return

        # Each step of the workflow puts the canvas in whatever tool it
        # actually needs, so the tab click alone is enough - there is no
        # separate 선택/Member row to click first any more. 지점/하중 reuse
        # their own richer activators (narrower selection filter, tailored
        # hint text) instead of the plain select tool; both already call
        # ``_show_category`` themselves.
        if key == "node":
            self._node_subcategory_clicked("add")
        elif key == "boundary":
            self._activate_support_tool()
        elif key == "loads":
            self._activate_load_tool()
        elif key == "element":
            self._element_subcategory_clicked(self._active_element_subcategory)
        elif key == "story":
            self._activate_select_tool()
            self._show_category("story", sync_workbench=False)
            if self._start_in_3d and show_settings:
                self._open_story_manager()
        else:
            self._activate_select_tool()
            categories = self._WORKBENCH_CATEGORIES[key]
            if categories:
                self._show_category(categories[0], sync_workbench=False)
            else:
                self.category_stack.setCurrentIndex(self.category_pages["empty"])
                self.left_panel_stack.hide()

        # Results is a real workspace, not merely a post-solve action.  Let the
        # user open it before running analysis so the available result families
        # and WAITING inspector state are visible while the model is being set
        # up.  The footer's "View results" shortcut can remain disabled until
        # computed values exist.
        if key == "results":
            self.workspace_stack.setCurrentIndex(1)
        elif key != "results" and self.workspace_stack.currentIndex() != 0:
            self.workspace_stack.setCurrentIndex(0)

    def _refresh_model_settings_summary(self) -> None:
        button = getattr(self, "model_settings_summary_button", None)
        if button is not None:
            button.setText(
                f"3D Frame · 6DOF · {self._unit_system.force}, {self._unit_system.length}"
                "   ·   모델 설정"
            )

    def _build_modeling_workspace(self) -> QWidget:
        page = QWidget()
        page.setObjectName("direct2DModelingWorkspace")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_3d_left_panel())
        if self._start_in_3d:
            # An explicit divider widget rather than relying on
            # QStackedWidget#modelingLeftDock's own border-right (theme.py) -
            # that rule alone was not actually visible: a QStackedWidget's
            # current page is resized to fill its full contents rect, and in
            # practice nothing forced that page to leave the border's 1px
            # column unpainted, so the child's own background silently
            # covered it. A dedicated thin QFrame between the panels paints
            # on top of both neighbours instead of depending on either one's
            # box model, matching the boundary already visible on the
            # opposite side (QScrollArea#modelingInspectorScroll's
            # border-left, which works because nothing sits to its right).
            self.left_dock_divider = QFrame()
            self.left_dock_divider.setObjectName("modelingLeftDockDivider")
            self.left_dock_divider.setFixedWidth(1)
            layout.addWidget(self.left_dock_divider)
            layout.addWidget(self._build_canvas_panel(), 1)
            layout.addWidget(self._build_selection_panel())
        else:
            # Same divider as the 3D branch above, for the same reason: the
            # editor panel and the selection panel are both QScrollAreas
            # whose own border-left (theme.py's #modelingInspectorScroll,
            # #modelingSelectionInspector) only ever paints a boundary
            # against whatever sits to *their* left, so the editor panel
            # on this side had no boundary against the canvas at all - a
            # dedicated 1px QFrame between them paints on top of both
            # neighbours instead of depending on either one's box model.
            self.left_dock_divider = QFrame()
            self.left_dock_divider.setObjectName("modelingLeftDockDivider")
            self.left_dock_divider.setFixedWidth(1)
            layout.addWidget(self.left_dock_divider)
            layout.addWidget(self._build_canvas_panel(), 1)
            layout.addWidget(self._build_selection_panel())
        return page

    def _rail_tool(self, text: str, shortcut: str, slot) -> QPushButton:
        """A select/draw canvas-mode toggle, shared by the 2D category bar
        (``_build_category_bar``) and the 3D task panel's own tool row
        (``_build_3d_task_panel``) — only these two govern what a click on
        the canvas does, so both keep them in their own exclusive
        ``tool_group`` rather than mixed in with category/workbench
        buttons."""
        button = QPushButton(text)
        button.setObjectName("railToolButton")
        button.setCheckable(True)
        button.setToolTip(f"{text} ({shortcut})")
        button.clicked.connect(slot)
        self.tool_group.addButton(button)
        return button

    def _build_canvas_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("direct2DCanvasPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.mode_label = QLabel()
        self.mode_label.setContentsMargins(10, 6, 10, 6)
        self.mode_label.setObjectName("setupSummaryHint")
        layout.addWidget(self.mode_label)
        layout.addWidget(self._build_level_bar())
        if self._start_in_3d:
            layout.addWidget(self._build_load_task_bar())

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

        self.entry_bar = self._build_entry_bar()
        # In 3D these controls duplicate the contextual Node/Element tabs and
        # the work-plane bar above the viewport. Keep the objects alive for
        # shortcuts and internal selection-filter routing, but do not spend a
        # permanent row on Grid/Snap/Ortho/typed 2D-style entry. The compact
        # precision strip remains visible in the 2D workspace where it is the
        # primary drawing aid.
        self.entry_bar.setVisible(not self._start_in_3d)
        layout.addWidget(self.entry_bar)
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
        self.new_plane_offset_label = QLabel(f"위치 ({self._unit_system.length})")
        self.new_plane_offset.setToolTip(
            f"평면도는 Z 높이, 정면도는 Y, 측면도는 X 위치입니다. 단위: {self._unit_system.length}"
        )
        layout.addWidget(self.new_plane_offset_label)
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
        self._rebuild_grid_snap_options()
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
    #: canvas — order here is both the button order and the left-hand editor
    #: page order. Nothing is pinned any more: every one of these, including
    #: 노드 추가/이동 (previously always-on in the right panel), is
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
        ("move", "이동"),
        ("arch", "아치"),
        ("support", "지점"),
        ("kind", "노드 유형"),
        ("member", "부재"),
        ("load", "하중"),
    )

    def _build_category_bar(self) -> QFrame:
        """The single-row bar above the canvas that picks what the left-hand
        editor panel shows — see ``_CATEGORY_OPTIONS``. An exclusive
        ``QButtonGroup`` already gives exactly the interaction wanted: click
        a category to show it, click a different one to switch, and
        clicking the already-active one is a no-op (Qt never lets an
        exclusive group end up with nothing checked once something has been
        checked) — so the panel stays open on whatever was last picked
        instead of needing an explicit close button.

        선택/그리기 and the UNDO/REDO/DELETE/FIT commands used to live in
        their own 72px-wide vertical rail to the left of the canvas, along
        with 지점/속성/하중 shortcuts that only ever did what this same bar's
        own 지점/부재/하중 buttons already do - a whole extra column just to
        duplicate three buttons. That rail is gone; 선택/그리기 open this bar
        instead (a separate ``tool_group``, since a canvas *mode* is not a
        *category*), and the commands sit at the bar's own trailing edge.
        """
        bar = QFrame()
        bar.setObjectName("direct2DCanvasToolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)

        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.select_tool = self._rail_tool("선택", "V", self._activate_select_tool)
        self.draw_tool = self._rail_tool("그리기", "L / Space", self._activate_draw_tool)
        layout.addWidget(self.select_tool)
        layout.addWidget(self.draw_tool)
        layout.addSpacing(10)

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

        for text, tooltip, slot in (
            ("UNDO", "Ctrl+Z", self.canvas.undo),
            ("REDO", "Ctrl+Y", self.canvas.redo),
            ("DELETE", "Delete", self.canvas.delete_selected),
            ("FIT", "F · 모델 전체가 보이도록 맞춥니다", self.canvas.fit_model),
        ):
            button = QPushButton(text)
            button.setObjectName("railCommandButton")
            button.setToolTip(tooltip)
            button.clicked.connect(slot)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return bar

    def _show_category_by_index(self, index: int) -> None:
        # 지점/하중 keep their richer 2D activators (select tool + a
        # convenience selection-filter narrow, see ``_activate_support_tool``
        # / ``_activate_load_tool``) instead of the plain category switch
        # every other button here uses - they used to be reachable only from
        # the now-removed tool rail's duplicate 지점/하중 shortcuts, and that
        # behaviour is worth keeping now that this bar is their only entry
        # point.
        key = self._CATEGORY_OPTIONS[index][0]
        if key == "support":
            self._activate_support_tool()
        elif key == "load":
            self._activate_load_tool()
        else:
            self._show_category(key)

    def _show_category(self, key: str, *, sync_workbench: bool = True) -> None:
        if sync_workbench:
            for tab_key, categories in self._WORKBENCH_CATEGORIES.items():
                if key in categories:
                    self.workbench_buttons[tab_key].setChecked(True)
                    break
        button = self.category_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        self.category_stack.setCurrentIndex(self.category_pages[key])
        self.left_panel_stack.setFixedWidth(320)
        self.left_panel_stack.setCurrentIndex(self.left_editor_index)
        self.left_panel_stack.show()
        title_by_category = {
                "add": "Node",
                "move": "Translate",
                "rotate": "Rotate Copy",
                "mirror": "Mirror Copy",
                "translate_node": "Translate",
                "rotate_node": "Rotate Copy",
                "mirror_node": "Mirror Copy",
                "arch": "Arch",
                "support": "Supports",
                "kind": "Node Type",
                "member": "Properties",
                "load": "Loads",
                "element_picker": "Element",
                "analysis": "Analysis",
                "story": "Story",
        }
        self.editor_title.setText(title_by_category.get(key, "Tool Settings"))
        # The category bar (this method) is the one place every category
        # switch passes through, from either entry point: the rail's 지점
        # button (_activate_support_tool, which narrows the filter to
        # "노드만" for convenience *before* calling this) or a direct click
        # on this bar's own 이동·복사/부재/노드 추가/etc. buttons (which never
        # touch the filter at all). Without this, a filter narrowed by 지점
        # stayed narrowed no matter which category was opened next - a
        # member click during 이동·복사 (or any other non-지점 category)
        # would be silently ignored with no visible reason why, the same
        # trap ``_load_target_changed`` stopped causing on the load side.
        # Widening here whenever a different category shows keeps 지점's
        # own narrowed filter intact only while its own page is up.
        if key != "support":
            self.selection_filter.setCurrentIndex(self.selection_filter.findData("all"))

    #: Node gets its own translate/rotate/mirror set, mirroring Element's.
    #: Translate contains MIDAS-style Copy/Move modes and a repeat count, so
    #: separate Duplicate and linear Array entries would only expose the same
    #: operation twice. MIDAS keeps Node and Element separate (Node mode never
    #: drags a member's far endpoint along; Element mode always does), which the
    #: ``selection_filter`` narrow to "nodes" (vs. Element's "elements") in
    #: ``_node_subcategory_clicked``/``_element_subcategory_clicked`` below
    #: enforces at the selection layer - the canvas-side operations
    #: themselves (``transform_selected_nodes`` etc.) are shared as-is.
    _NODE_SUBCATEGORIES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("add", "Create Node"),
        ("translate_node", "Translate Node"),
        ("rotate_node", "Rotate Copy Node"),
        ("mirror_node", "Mirror Copy Node"),
        ("arch", "Arch"),
        ("kind", "Node Type"),
    )

    _ELEMENT_SUBCATEGORIES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("element_picker", "Create Element"),
        ("move", "Translate Element"),
        ("rotate", "Rotate Copy Element"),
        ("mirror", "Mirror Copy Element"),
    )

    #: MIDAS-style structural intent for members drawn from Create Element.
    #: Tension-only / compression-only / cable are axial-only like a truss,
    #: but each has its own uniaxial law (ElasticPPGap / ENT / optional
    #: prestress) and a type-specific 설정창 rather than sharing the beam
    #: I/J form.
    _ELEMENT_TYPE_OPTIONS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("general_beam", "General Beam"),
        ("truss", "Truss"),
        ("tension_only", "Tension-only"),
        ("compression_only", "Compression-only"),
        ("cable", "Cable"),
    )

    #: Only "add" (클릭으로 새 노드/부재를 그림) needs draw mode - the other
    #: three all act on a node/member that already exists, so clicking into
    #: them switches back to select or a click would place a new node
    #: instead of picking the one meant to be moved/re-typed.
    _NODE_SUBCATEGORY_DRAW: ClassVar[frozenset[str]] = frozenset({"add"})

    def _build_node_subcategory_row(self) -> QWidget:
        """The Node tab's own action picker — a plain dropdown (native
        "click to expand the list, pick one, it closes itself" behaviour)
        instead of a custom toggle+list, matching the reference "Tree Menu"
        combo (Create/Delete/Translate/... Nodes) the user pointed to:
        the combo itself is the compact, always-visible control, and
        whichever action is current shows directly in its closed state.
        """
        row = QWidget()
        row.setObjectName("nodeSubcategoryRow")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._active_node_subcategory = self._NODE_SUBCATEGORIES[0][0]
        self.node_subcategory_combo = QComboBox()
        self.node_subcategory_combo.setObjectName("nodeSubcategoryCombo")
        for key, label in self._NODE_SUBCATEGORIES:
            self.node_subcategory_combo.addItem(label, key)
        self.node_subcategory_combo.currentIndexChanged.connect(
            self._node_subcategory_combo_changed
        )
        # QSS ``padding`` on the popup's QAbstractItemView does not reserve
        # trailing space after the last row (a long-standing Qt quirk) - the
        # last item's text ends up sitting right on the popup's bottom
        # border with no breathing room, reading as "cut off". Content
        # margins on the view itself are a real widget property, not a
        # box-model hint, so they reliably add the gap QSS padding here does
        # not.
        self.node_subcategory_combo.view().setContentsMargins(0, 4, 0, 8)
        layout.addWidget(self.node_subcategory_combo)

        self.node_subcategory_row = row
        return row

    def _build_element_subcategory_row(self) -> QWidget:
        row = QWidget()
        row.setObjectName("elementSubcategoryRow")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._active_element_subcategory = self._ELEMENT_SUBCATEGORIES[0][0]
        self.element_subcategory_combo = QComboBox()
        self.element_subcategory_combo.setObjectName("elementSubcategoryCombo")
        for key, label in self._ELEMENT_SUBCATEGORIES:
            self.element_subcategory_combo.addItem(label, key)
        self.element_subcategory_combo.currentIndexChanged.connect(
            self._element_subcategory_combo_changed
        )
        self.element_subcategory_combo.view().setContentsMargins(0, 4, 0, 8)
        layout.addWidget(self.element_subcategory_combo)

        self.element_subcategory_row = row
        return row

    def _element_subcategory_combo_changed(self, index: int) -> None:
        key = self.element_subcategory_combo.itemData(index)
        if key is not None:
            self._element_subcategory_clicked(key)

    def _element_subcategory_clicked(self, key: str) -> None:
        self._active_element_subcategory = key
        index = self.element_subcategory_combo.findData(key)
        if index != -1 and self.element_subcategory_combo.currentIndex() != index:
            self.element_subcategory_combo.blockSignals(True)
            self.element_subcategory_combo.setCurrentIndex(index)
            self.element_subcategory_combo.blockSignals(False)
        if key == "element_picker" and (
            not self._start_in_3d or self._active_element_kwargs is not None
        ):
            self._activate_draw_tool()
        else:
            self._activate_select_tool()
        self._show_category(key, sync_workbench=False)
        if key in {"move", "rotate", "mirror"}:
            self.selection_filter.setCurrentIndex(
                self.selection_filter.findData("elements")
            )

    def _node_subcategory_combo_changed(self, index: int) -> None:
        key = self.node_subcategory_combo.itemData(index)
        if key is not None:
            self._node_subcategory_clicked(key)

    def _node_subcategory_clicked(self, key: str) -> None:
        self._active_node_subcategory = key
        combo = getattr(self, "node_subcategory_combo", None)
        if combo is not None:
            index = combo.findData(key)
            if index != -1 and combo.currentIndex() != index:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
        self._activate_select_tool()
        self._show_category(key, sync_workbench=False)
        if key in {
            "translate_node",
            "rotate_node",
            "mirror_node",
        }:
            self.selection_filter.setCurrentIndex(
                self.selection_filter.findData("nodes")
            )

    def _build_element_category(self) -> QWidget:
        """Create members and own the complete current-property workflow.

        In 2D the values in this page are the active pen: Space-drawn members
        receive them automatically, while the same values can be applied to
        an existing selection with one explicit button. 3D retains the saved
        library-pair selector because its staged creation workflow depends on
        reusable work-tree definitions.
        """
        section = QWidget()
        section.setObjectName("elementCreatePanel")
        root = QVBoxLayout(section)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        type_card, type_root = self._section("Element Type")
        self.element_type_card = type_card
        type_hint = QLabel("다음에 그릴 부재의 구조 거동을 선택합니다.")
        type_hint.setWordWrap(True)
        type_hint.setObjectName("setupSectionHint")
        type_root.addWidget(type_hint)
        self.element_type_selector = QComboBox()
        self.element_type_selector.setObjectName("elementTypeSelector")
        for key, label in self._ELEMENT_TYPE_OPTIONS:
            self.element_type_selector.addItem(label, key)
        self.element_type_selector.setToolTip(
            "다음에 그릴 부재의 구조 형식을 선택합니다. Tension-only / "
            "Compression-only / Cable은 축력만 전달하며, 아래 거동 설정에서 "
            "갭·프리스트레스를 지정합니다."
        )
        self.element_type_selector.currentIndexChanged.connect(
            self._element_type_selection_changed
        )
        type_root.addWidget(self.element_type_selector)
        root.addWidget(type_card)

        behavior_card, behavior_root = self._section("부재 거동 설정")
        self.element_behavior_settings_card = behavior_card
        self.element_behavior_hint = QLabel()
        self.element_behavior_hint.setWordWrap(True)
        self.element_behavior_hint.setObjectName("setupSectionHint")
        self.element_behavior_hint.setMaximumWidth(272)
        behavior_root.addWidget(self.element_behavior_hint)
        behavior_form = QFormLayout()
        behavior_form.setContentsMargins(0, 0, 0, 0)
        self.element_gap_field = self._number(0.0)
        self.element_gap_field.setRange(0.0, 1_000_000.0)
        self.element_gap_field.setToolTip(
            "인장 저항이 시작되기 전의 초기 유간입니다. 0이면 인장 즉시 저항합니다."
        )
        self.element_gap_field.valueChanged.connect(self._directional_pen_changed)
        self.element_gap_label = QLabel("초기 갭")
        behavior_form.addRow(self.element_gap_label, self.element_gap_field)
        self.element_prestress_field = self._number(0.0)
        self.element_prestress_field.setToolTip(
            "케이블에 미리 도입하는 인장력입니다. 0이 아니면 기하비선형(corotTruss)로 해석합니다."
        )
        self.element_prestress_field.valueChanged.connect(self._directional_pen_changed)
        self.element_prestress_label = QLabel("프리스트레스")
        behavior_form.addRow(self.element_prestress_label, self.element_prestress_field)
        behavior_root.addLayout(behavior_form)
        self.apply_element_behavior_button = QPushButton("선택 부재에 거동 설정 적용")
        self.apply_element_behavior_button.setObjectName("direct2DSecondaryButton")
        self.apply_element_behavior_button.setToolTip(
            "이미 그린 Tension-only / Compression-only / Cable 부재에 "
            "위 갭·프리스트레스를 적용합니다. 새로 그리는 부재에는 자동 반영됩니다."
        )
        self.apply_element_behavior_button.clicked.connect(
            self._apply_directional_settings_to_selection
        )
        behavior_root.addWidget(self.apply_element_behavior_button)
        behavior_card.hide()
        root.addWidget(behavior_card)

        properties_card, properties_root = self._section(
            "현재 부재 설정" if not self._start_in_3d else "Material & Section"
        )
        self.element_properties_card = properties_card
        property_hint = QLabel(
            "여기 입력된 물성과 단면이 현재 설정입니다. Space로 새로 그리는 부재에는 "
            "자동 적용되고, 기존 부재는 선택 후 아래 적용 버튼을 누르면 됩니다."
            if not self._start_in_3d
            else "Properties에서 저장한 Material과 Section을 모두 선택하세요."
        )
        property_hint.setWordWrap(True)
        property_hint.setObjectName("setupSectionHint")
        properties_root.addWidget(property_hint)

        saved_property_picker = QWidget() if not self._start_in_3d else None
        self.element_saved_property_picker = saved_property_picker
        property_form = (
            QFormLayout(saved_property_picker)
            if saved_property_picker is not None
            else QFormLayout()
        )
        property_form.setContentsMargins(0, 0, 0, 0)
        self.element_property_form = property_form
        self.element_material_selector = QComboBox()
        self.element_material_selector.setObjectName("elementMaterialSelector")
        self.element_material_selector.currentIndexChanged.connect(
            self._element_property_selection_changed
        )
        property_form.addRow("Material", self.element_material_selector)
        self.element_section_selector = QComboBox()
        self.element_section_selector.setObjectName("elementSectionSelector")
        self.element_section_selector.currentIndexChanged.connect(
            self._element_property_selection_changed
        )
        property_form.addRow("Section", self.element_section_selector)
        if saved_property_picker is None:
            properties_root.addLayout(property_form)
        else:
            properties_root.addWidget(saved_property_picker)
            saved_property_picker.hide()

        self.active_element_status = QLabel(
            "현재 입력값을 확인하는 중입니다."
            if not self._start_in_3d
            else "Element Type을 고르고 Material과 Section을 선택하세요."
        )
        self.active_element_status.setWordWrap(True)
        self.active_element_status.setObjectName("setupSectionHint")
        properties_root.addWidget(self.active_element_status)

        if not self._start_in_3d:
            self.element_current_property_panel = SectionMaterialPanel()
            self.element_current_property_panel.set_streamlined_assignment_mode()
            # This panel is the live current setting, not a library editor.
            # Saving a pair is therefore unnecessary and would recreate the
            # exact two-stage workflow this page is replacing.
            self.element_current_property_panel.streamlined_assignment_hint.setText(
                "입력값을 바꾸면 즉시 '현재 설정'이 됩니다. 별도로 저장할 필요가 없습니다."
            )
            self.element_current_property_panel.property_set_save_button.hide()
            self.element_current_property_panel.property_set_save_status.hide()
            self.element_current_property_panel.apply_button.setText(
                "선택 부재에 현재 설정 적용"
            )
            self.element_current_property_panel.apply_button.setObjectName(
                "elementApplyCurrentPropertiesButton"
            )
            self.element_current_property_panel.apply_requested.connect(
                self._apply_current_element_properties_to_selection
            )
            self.element_current_property_panel.edited.connect(
                self._element_current_properties_edited
            )
            properties_root.addWidget(self.element_current_property_panel)

            self.load_selected_element_properties_button = QPushButton(
                "선택 부재의 설정 불러오기"
            )
            self.load_selected_element_properties_button.setObjectName(
                "direct2DSecondaryButton"
            )
            self.load_selected_element_properties_button.setToolTip(
                "부재 하나를 선택한 뒤 누르면 실제 적용되어 있는 물성과 단면을 위 입력창에 불러옵니다."
            )
            self.load_selected_element_properties_button.clicked.connect(
                self._load_selected_element_properties
            )
            properties_root.addWidget(self.load_selected_element_properties_button)

            self.element_assignment_selection_status = QLabel()
            self.element_assignment_selection_status.setObjectName("setupSectionHint")
            self.element_assignment_selection_status.setWordWrap(True)
            properties_root.addWidget(self.element_assignment_selection_status)
        root.addWidget(properties_card)

        self.start_element_drawing_button = QPushButton(
            "현재 설정으로 부재 그리기 (Space)"
            if not self._start_in_3d
            else "Create Element 시작"
        )
        self.start_element_drawing_button.setEnabled(not self._start_in_3d)
        self.start_element_drawing_button.clicked.connect(self._activate_draw_tool)
        root.addWidget(self.start_element_drawing_button)
        root.addStretch(1)
        self._refresh_element_property_selectors()
        if not self._start_in_3d:
            self._sync_element_assignment_selection_state()
        return section

    def _element_type_selection_changed(self, _index: int | None = None) -> None:
        """Make the Create Element type the pen used for subsequent members."""
        behavior = self.element_type_selector.currentData()
        axial_only = behavior != "general_beam"
        self.canvas.element_family = "truss" if axial_only else "frame"
        self.canvas.element_behavior = behavior

        # Keep the older model-level controls consistent without letting their
        # signals collapse a refined axial choice (e.g. Cable) back to Truss.
        self.truss_mode_toggle.blockSignals(True)
        self.truss_mode_toggle.setChecked(axial_only)
        self.truss_mode_toggle.blockSignals(False)
        if not self._start_in_3d:
            model_family = "truss" if axial_only else "frame"
            model_index = self.model_type_selector.findData(model_family)
            if model_index >= 0:
                self.model_type_selector.blockSignals(True)
                self.model_type_selector.setCurrentIndex(model_index)
                self.model_type_selector.blockSignals(False)

        self._element_property_selection_changed()
        self._refresh_directional_pen_card()

    _DIRECTIONAL_BEHAVIOR_HINTS: ClassVar[dict[str, str]] = {
        "tension_only": (
            "인장만 저항하는 축력 부재입니다. 압축을 받으면 강성이 0이 되어 "
            "슬랙 상태가 됩니다. 재료·단면(E, A)은 아래 Material/Section에서 지정하세요."
        ),
        "compression_only": (
            "압축만 저항하는 축력 부재입니다. 인장을 받으면 강성이 0이 됩니다. "
            "재료·단면(E, A)은 아래 Material/Section에서 지정하세요."
        ),
        "cable": (
            "인장전담 케이블입니다. 프리스트레스가 있으면 기하비선형(corotTruss)로 "
            "해석하고, 0이면 인장전담 트러스와 같습니다. 재료·단면(E, A)은 아래에서 지정하세요."
        ),
    }

    def _refresh_directional_pen_card(self) -> None:
        """Show the type-specific 설정창 only for tension/compression/cable.

        General Beam / Truss keep the Material & Section card they already
        had - inventing a second empty form there would look like those types
        were unfinished too.
        """
        if not hasattr(self, "element_behavior_settings_card"):
            return
        behavior = self.element_type_selector.currentData()
        directional = behavior in self._DIRECTIONAL_BEHAVIOR_HINTS
        self.element_behavior_settings_card.setVisible(directional)
        if not directional:
            return
        self.element_behavior_hint.setText(self._DIRECTIONAL_BEHAVIOR_HINTS[behavior])
        show_gap = behavior in ("tension_only", "cable")
        show_prestress = behavior == "cable"
        self.element_gap_label.setVisible(show_gap)
        self.element_gap_field.setVisible(show_gap)
        self.element_prestress_label.setVisible(show_prestress)
        self.element_prestress_field.setVisible(show_prestress)
        self._refresh_directional_unit_labels()
        self._directional_pen_changed()

    def _directional_pen_changed(self, _value: float | None = None) -> None:
        """Keep the drawing pen in sync so the next Space-drawn member
        inherits the 설정창 without an extra Apply click."""
        if not hasattr(self, "element_gap_field"):
            return
        self.canvas.element_gap = float(self.element_gap_field.value())
        self.canvas.element_prestress = float(self.element_prestress_field.value())

    def _apply_directional_settings_to_selection(self) -> None:
        if not self.canvas.selected_elements:
            self.active_element_status.setText(
                "⚠ 적용할 기존 부재를 먼저 선택하세요. 새로 그리는 부재에는 자동 반영됩니다."
            )
            return
        self._directional_pen_changed()
        self.canvas.apply_behavior_settings_to_selection(
            gap=self.canvas.element_gap,
            prestress=self.canvas.element_prestress,
        )
        count = len(self.canvas.selected_elements)
        self.active_element_status.setText(
            f"✓ 선택 부재 {count}개에 거동 설정(갭·프리스트레스)을 적용했습니다."
        )

    def _refresh_directional_unit_labels(self) -> None:
        if not hasattr(self, "element_gap_field"):
            return
        length = self._unit_system.length
        force = self._unit_system.force
        self.element_gap_label.setText(f"초기 갭 ({length})")
        self.element_gap_field.setSuffix(f" {length}")
        self.element_prestress_label.setText(f"프리스트레스 ({force})")
        self.element_prestress_field.setSuffix(f" {force}")
        if hasattr(self, "member_gap_field"):
            self.member_gap_label.setText(f"초기 갭 ({length})")
            self.member_gap_field.setSuffix(f" {length}")
            self.member_prestress_label.setText(f"프리스트레스 ({force})")
            self.member_prestress_field.setSuffix(f" {force}")

    #: Label + the dialog class that captures "what kind of run this is
    #: meant to be" for every AnalysisKind this canvas cannot execute
    #: directly yet - all four now share the same wide settings dialog (see
    #: analysis_settings_dialogs.py's own module docstring); ``dialog_cls``
    #: stays per-row (rather than a plain bool) so ``_open_analysis_settings_
    #: dialog`` and the ``is_linear = dialog_cls is None`` check below stay
    #: unchanged in shape even though every non-None entry is now literally
    #: the same class.
    # Every AnalysisKind AnalysisSettingsPanel's own ANALYSIS TYPE combo
    # offers, one-for-one - Response Spectrum used to be reachable only by
    # picking it from *inside* the settings dialog, invisible from this list,
    # which is exactly the two-controls-for-one-choice confusion that combo
    # is now hidden for (see AnalysisSettingsDialog). Keep the two lists in
    # sync if AnalysisSettingsPanel's own combo ever grows another kind.
    _ANALYSIS_METHOD_OPTIONS: ClassVar[tuple[tuple[str, AnalysisKind, type | None], ...]] = (
        ("선형탄성 (Linear Elastic)", AnalysisKind.LINEAR_STATIC, None),
        ("비선형 정적 (Pushover)", AnalysisKind.NONLINEAR_STATIC, AnalysisSettingsDialog),
        ("모드/고유치 (Modal)", AnalysisKind.MODAL, AnalysisSettingsDialog),
        ("좌굴 (Buckling)", AnalysisKind.BUCKLING, AnalysisSettingsDialog),
        ("시간이력 (Time History)", AnalysisKind.TIME_HISTORY, AnalysisSettingsDialog),
        ("응답스펙트럼 (Response Spectrum)", AnalysisKind.RESPONSE_SPECTRUM, AnalysisSettingsDialog),
    )
    #: Routed through ``_run_full_analysis`` and the shared OpenSees worker
    #: pipeline (export script -> ``RunAnalysisService``) instead of the
    #: in-canvas ``MaterialFreeStaticsSolver``.
    _FULL_ANALYSIS_KINDS: ClassVar[frozenset[AnalysisKind]] = frozenset(
        {
            AnalysisKind.MODAL,
            AnalysisKind.BUCKLING,
            AnalysisKind.TIME_HISTORY,
            AnalysisKind.RESPONSE_SPECTRUM,
        }
    )
    _ANALYSIS_DISPLAY_NAMES: ClassVar[dict[AnalysisKind, str]] = {
        AnalysisKind.LINEAR_STATIC: "Linear Static",
        AnalysisKind.NONLINEAR_STATIC: "Nonlinear Static",
        AnalysisKind.MODAL: "Modal (Eigenvalue)",
        AnalysisKind.TIME_HISTORY: "Time History",
        AnalysisKind.BUCKLING: "Elastic Buckling",
        AnalysisKind.RESPONSE_SPECTRUM: "Response Spectrum",
    }

    def _build_analysis_category(self) -> QWidget:
        """3D workbench's Analysis tab. The header's own 정정성 검사 및 해석/
        정밀해석으로 내보내기 buttons (``solve``/``_export_for_full_analysis``)
        already do the actual work and stay untouched (2D shares that header
        unconditionally) - this page just gives Analysis a home in the
        workbench flow instead of the blank page it showed before, with its
        own run/export buttons wired to those same handlers.

        Linear Static and Nonlinear Static (Pushover) actually run from here.
        Picking any other method swaps 해석하기 for a 설정... button that
        opens the same wide ``AnalysisSettingsPanel``-hosting dialog SETUP
        uses (``analysis_settings_dialogs.AnalysisSettingsDialog`` -
        see its own module docstring for why this used to be four separate,
        much narrower dialogs and no longer is), rather than cramming a
        time-history-sized settings form into this panel's fixed 320px
        width. This canvas's own solver has not grown to run Modal/Buckling/
        Time History in-process yet, so what that dialog collects for those
        kinds is only staged in ``self._analysis_settings`` - so a student
        does not have to re-enter it if they switch methods and back -
        ready for whichever future step bridges it into a real solve
        (exporting the 3D model to a script and running it through
        SETUP's engine, once ``export_opensees_script`` grows a 3D case;
        it is 2D-only today). Nonlinear Static also stages its settings
        there, but its 해석하기 click reads the handful of keys
        ``MaterialFreeStaticsSolver.solve_nonlinear_static`` actually takes
        back out of ``self._analysis_settings`` (see ``_solve_nonlinear_
        static``'s own ``_NONLINEAR_STATIC_SOLVER_KEYS`` filter - the panel
        now stages several more advanced keys than this in-canvas solver
        understands) and runs that lumped-plasticity pushover for steel
        members carrying a yield strength, not full material nonlinearity
        (see that method's own scoping note).
        """
        self._analysis_settings: dict[str, dict] = {}
        section, root = self._section("Analysis", show_title=False)

        # Analysis Case skeleton (Case create/duplicate/rename/delete,
        # per-case PRE-CHECK) - added alongside the existing method
        # combo/dialog flow below, not replacing it yet. Nothing here is
        # read by solve()/_solve_nonlinear_static() in this pass; those
        # still run entirely off self.analysis_method_selector/
        # self._analysis_settings, unchanged. See
        # analysis_settings_sidebar.py's own module docstring for the
        # target design this is the first slice of.
        self.analysis_case_store = AnalysisCaseStore(self)
        self.analysis_settings_sidebar = AnalysisSettingsSidebar(
            self.analysis_case_store, self.canvas.build_model
        )
        root.addWidget(self.analysis_settings_sidebar)

        hint = QLabel(
            "이 화면에서 바로 실행되는 해석은 선형탄성과 비선형 정적(Pushover, 강재 "
            "집중소성힌지)입니다 — 부정정 구조를 정확히 풀려면 모든 부재에 실제 "
            "재료·단면(E/A/I)이 필요합니다."
        )
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        # A wrapped QLabel's sizeHint() ignores any width a later layout
        # would constrain it to - this 2-sentence hint reported ~480px
        # unwrapped, well past this panel's fixed-320px budget, the same
        # trap the Loads tab's seismic/wind generators hit earlier this
        # session. Pre-existing, just never asserted by a test until the
        # new Analysis Case sidebar below made the whole page's sizeHint
        # visibly wrong; fixed alongside it rather than left half-broken.
        hint.setMaximumWidth(272)
        root.addWidget(hint)

        # Label above the combo, not a QFormLayout row beside it - "해석
        # 방법" + this combo's own longest item ("비선형 정적 (Pushover)")
        # together were already past this panel's fixed-320px budget
        # (QFormLayout adds the label's width to the field's, not just the
        # field's own), same trap as the hint labels above.
        method_label = QLabel("해석 방법")
        root.addWidget(method_label)
        self.analysis_method_selector = QComboBox()
        for label, kind, _dialog_cls in self._ANALYSIS_METHOD_OPTIONS:
            self.analysis_method_selector.addItem(label, kind.value)
        self.analysis_method_selector.currentIndexChanged.connect(self._on_analysis_method_changed)
        # Its own longest item ("비선형 정적 (Pushover)") wants 282px, which
        # combined with this section's own 20px margins clears the 296px
        # budget by only 6px - capped rather than left to round-trip through
        # every width-safety check on a hair's-width margin. The closed
        # combo's displayed text still shows in full at this width; only a
        # much longer future label would ever actually elide.
        self.analysis_method_selector.setMaximumWidth(272)
        root.addWidget(self.analysis_method_selector)

        self.analysis_settings_button = QPushButton("설정...")
        self.analysis_settings_button.clicked.connect(self._open_analysis_settings_dialog)
        root.addWidget(self.analysis_settings_button)
        self.analysis_settings_summary = QLabel()
        self.analysis_settings_summary.setObjectName("setupSectionHint")
        self.analysis_settings_summary.setWordWrap(True)
        root.addWidget(self.analysis_settings_summary)

        self.analysis_run_button = QPushButton("해석하기")
        self.analysis_run_button.setObjectName("setupContinueButton")
        self.analysis_run_button.clicked.connect(self.solve)
        root.addWidget(self.analysis_run_button)

        self.task_results_button = QPushButton("결과 보기")
        self.task_results_button.setEnabled(False)
        self.task_results_button.clicked.connect(lambda: self.workspace_stack.setCurrentIndex(1))
        root.addWidget(self.task_results_button)

        advanced_hint = QLabel(
            "모드/고유치·좌굴·시간이력·응답스펙트럼은 설정...으로 옵션을 저장한 뒤 "
            "해석하기로 실행할 수 있습니다."
        )
        advanced_hint.setWordWrap(True)
        advanced_hint.setObjectName("setupSectionHint")
        advanced_hint.setMaximumWidth(272)
        root.addWidget(advanced_hint)
        export_button = QPushButton("정밀해석으로 내보내기…")
        export_button.setObjectName("direct2DSecondaryButton")
        export_button.clicked.connect(self._export_for_full_analysis)
        root.addWidget(export_button)

        root.addStretch(1)
        self._on_analysis_method_changed()
        return section

    def _current_analysis_method_option(self) -> tuple[str, AnalysisKind, type | None]:
        index = max(self.analysis_method_selector.currentIndex(), 0)
        return self._ANALYSIS_METHOD_OPTIONS[index]

    def _on_analysis_method_changed(self, _index: int | None = None) -> None:
        _label, kind, dialog_cls = self._current_analysis_method_option()
        is_linear = dialog_cls is None
        # Preview the Results sidebar's section set (and its analysis-kind
        # label) for whichever method is now selected, not just once a run
        # actually starts (_run_full_analysis's own call) - picking "좌굴
        # (Buckling)" here should already show BUCKLING/mode-shape-style
        # sections, not leave the last-run kind's stale ones up. Guarded:
        # this fires once during __init__ (_build_analysis_category, inside
        # _build_modeling_workspace) before _build_result_workspace has
        # created self.results.
        if hasattr(self, "results"):
            self.results.set_analysis_kind(kind)
        # Nonlinear Static is the one non-linear method actually wired to a
        # real solve now (MaterialFreeStaticsSolver.solve_nonlinear_static,
        # a lumped-plasticity pushover - see its own docstring for scope).
        # Every other kind here (Modal/Buckling/Time History) still only
        # collects settings, unchanged.
        can_run = self._can_run_selected_analysis(kind, is_linear)
        self.analysis_settings_button.setVisible(not is_linear)
        self.analysis_settings_summary.setVisible(not is_linear)
        if self._analysis_run_thread is not None and self._analysis_run_thread.isRunning():
            self.analysis_run_button.setEnabled(False)
        else:
            self.analysis_run_button.setEnabled(can_run)
        if kind in self._FULL_ANALYSIS_KINDS and self._run_analysis_service is None:
            run_tooltip = "정밀해석 실행 서비스가 연결되지 않았습니다."
        elif not can_run:
            run_tooltip = "이 방법은 아직 실행에 연결되지 않았습니다."
        else:
            run_tooltip = ""
        self.analysis_run_button.setToolTip(run_tooltip)
        if not is_linear:
            has_settings = kind.value in self._analysis_settings
            self.analysis_settings_summary.setText(
                "✓ 설정을 저장했습니다." if has_settings else "아직 설정하지 않았습니다."
            )

    def _can_run_selected_analysis(self, kind: AnalysisKind, is_linear: bool) -> bool:
        if is_linear or kind == AnalysisKind.NONLINEAR_STATIC:
            return True
        if kind in self._FULL_ANALYSIS_KINDS and self._run_analysis_service is not None:
            return True
        return False

    def _shared_analysis_settings_panel(self) -> AnalysisSettingsPanel:
        """One ``AnalysisSettingsPanel`` reused across every 설정... click,
        so a value entered for one analysis kind is still there if the
        student switches methods and comes back - the panel's own widgets
        hold their state across an ``analysis_type`` combo change; a fresh
        panel per dialog open would silently discard that every time.
        """
        if not hasattr(self, "_analysis_settings_panel"):
            self._analysis_settings_panel = AnalysisSettingsPanel()
        return self._analysis_settings_panel

    def _open_analysis_settings_dialog(self) -> None:
        _label, kind, dialog_cls = self._current_analysis_method_option()
        if dialog_cls is None:
            return
        panel = self._shared_analysis_settings_panel()
        panel.set_model(self.canvas.build_model())
        panel.set_unit_system(self._unit_system)
        # This tab's own 해석 방법 combo is the one place the kind gets
        # picked - the dialog hides the panel's own ANALYSIS TYPE row (see
        # AnalysisSettingsDialog) precisely so there is nowhere inside it to
        # quietly land on a different kind than what is shown here.
        kind_index = panel.analysis_type.findData(kind)
        if kind_index >= 0:
            panel.analysis_type.setCurrentIndex(kind_index)
        dialog = dialog_cls(panel, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.detach()  # reclaim the panel before `dialog` is garbage-collected
        if not accepted:
            return
        self._analysis_settings[kind.value] = panel.build_options()
        self._on_analysis_method_changed()

    def _element_property_selection_changed(self, _index: int | None = None) -> None:
        material_id = self.element_material_selector.currentData()
        section_id = self.element_section_selector.currentData()
        material = next(
            (item for item in self._user_materials if item.get("id") == material_id),
            None,
        )
        section = next(
            (item for item in self._user_sections if item.get("id") == section_id),
            None,
        )
        if material is None or section is None:
            if not self._start_in_3d and hasattr(self, "element_current_property_panel"):
                self._element_current_properties_edited(clear_saved_selection=False)
                return
            self._active_element_kwargs = None
            self.start_element_drawing_button.setEnabled(not self._start_in_3d)
            property_hint = (
                "기본 속성으로 부재를 생성합니다. 저장한 Material과 Section을 "
                "선택하면 새 부재에 함께 적용됩니다."
                if not self._start_in_3d
                else "Properties에서 저장한 Material과 Section을 모두 선택하세요."
            )
            self.active_element_status.setText(property_hint)
            return
        self._set_active_element_properties(
            {
                "shape": section["shape"],
                "source": section["source"],
                "dimensions": dict(section["dimensions"]),
                "area": float(section["area"]),
                "iy": float(section["iy"]),
                "iz": float(section["iz"]),
                "j": float(section["j"]),
                "elastic": float(material["elastic"]),
                "density": float(material.get("density", 0.0)),
                "section_id": section.get("database_id") or section_id,
                "material_id": material_id,
                "material_category": material.get("category"),
                "material_grade": material.get("grade"),
            },
            material_label=str(material.get("name") or material_id),
            section_label=str(section.get("name") or section_id),
        )

    def _set_active_element_properties(
        self,
        properties: dict[str, object],
        *,
        material_label: str | None = None,
        section_label: str | None = None,
    ) -> None:
        self._active_element_kwargs = dict(properties)
        material_label = material_label or self.element_material_selector.currentText()
        section_label = section_label or self.element_section_selector.currentText()
        elastic = float(properties.get("elastic", 0.0))
        area = float(properties.get("area", 0.0))
        inertia = float(properties.get("iy", 0.0))
        self.active_element_status.setText(
            f"현재 설정: {material_label} / {section_label}\n"
            f"E {elastic:g} {self._unit_system.stress} · "
            f"A {area:g} {self._unit_system.length}² · "
            f"I {inertia:g} {self._unit_system.length}⁴\n"
            "✓ 새 부재에 자동 적용됩니다."
        )
        self.start_element_drawing_button.setEnabled(True)

    def _element_current_properties_edited(
        self, *, clear_saved_selection: bool = True
    ) -> None:
        """Promote the 2D Element editor's live values to the drawing pen."""
        panel = getattr(self, "element_current_property_panel", None)
        if panel is None:
            return
        properties = panel.current_edit_kwargs()
        if properties is None:
            self._active_element_kwargs = None
            self.active_element_status.setText(
                "⚠ 단면 치수를 확인하세요. 유효한 A/I가 계산되면 현재 설정으로 사용됩니다."
            )
            return
        if clear_saved_selection:
            for combo in (self.element_material_selector, self.element_section_selector):
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
        material_label = panel.material_grade_combo.currentText().strip() or "직접 입력 물성"
        section_label = (
            panel.designation_combo.currentText().strip()
            if panel.source_database.isChecked()
            else panel.section_name.text().strip()
        ) or panel.shape_combo.currentText().strip()
        self._set_active_element_properties(
            properties,
            material_label=material_label,
            section_label=section_label,
        )

    def _apply_current_element_properties_to_selection(self) -> None:
        """Apply the same current pen values to already-drawn 2D members."""
        panel = self.element_current_property_panel
        properties = panel.current_edit_kwargs()
        if properties is None:
            self.active_element_status.setText(
                "⚠ 단면 치수가 유효하지 않아 적용하지 못했습니다."
            )
            return
        if not self.canvas.selected_elements:
            self.element_assignment_selection_status.setText(
                "⚠ 적용할 기존 부재를 먼저 선택하세요. 새 부재에는 현재 설정이 자동 적용됩니다."
            )
            return
        count = len(self.canvas.selected_elements)
        self._element_current_properties_edited()
        self.canvas.apply_full_section_to_selection(**properties)
        self.element_assignment_selection_status.setText(
            f"✓ 선택 부재 {count}개에 현재 물성·단면(E/A/I)을 적용했습니다."
        )
        self.selection_summary.setText(
            f"✓ 부재 {count}개에 현재 물성·단면(E/A/I)을 적용했습니다."
        )
        self._sync_selection_status()

    def _load_selected_element_properties(self) -> None:
        """Explicitly inspect one member without silently replacing the pen."""
        if self.canvas.selected_nodes or len(self.canvas.selected_elements) != 1:
            self.element_assignment_selection_status.setText(
                "⚠ 설정을 불러올 부재 하나만 선택하세요."
            )
            return
        member_tag = next(iter(self.canvas.selected_elements))
        self.element_current_property_panel.load_from_element(
            self.canvas.elements[member_tag]
        )
        if self.element_current_property_panel.current_edit_kwargs() is None:
            self._active_element_kwargs = None
            self.active_element_status.setText(
                f"부재 M-{member_tag}에는 아직 유효한 물성·단면이 없습니다. 위에서 입력하세요."
            )
        else:
            self._element_current_properties_edited()
            self.element_assignment_selection_status.setText(
                f"✓ 부재 M-{member_tag}에 실제 적용된 설정을 불러왔습니다."
            )

    def _sync_element_assignment_selection_state(self) -> None:
        """Keep the Element card explicit about what Apply will affect."""
        button = getattr(self, "load_selected_element_properties_button", None)
        status = getattr(self, "element_assignment_selection_status", None)
        if button is None or status is None:
            return
        count = len(self.canvas.selected_elements)
        button.setEnabled(not self.canvas.selected_nodes and count == 1)
        if count == 0:
            status.setText(
                "선택 부재 없음 · 새로 그리는 부재에는 위 현재 설정이 자동 적용됩니다."
            )
        elif self.canvas.selected_nodes:
            status.setText("부재만 선택하면 현재 설정을 적용하거나 불러올 수 있습니다.")
        elif count == 1:
            member_tag = next(iter(self.canvas.selected_elements))
            status.setText(
                f"부재 M-{member_tag} 선택됨 · 적용 또는 실제 설정 불러오기를 선택하세요."
            )
        else:
            status.setText(f"부재 {count}개 선택됨 · 현재 설정을 한 번에 적용할 수 있습니다.")

    def _apply_active_element_to_new_members(self, new_element_tags: set[int]) -> None:
        """Give a just-drawn member the Element tab's selected definitions.

        This works the same way a CAD tool's "current layer" governs
        what gets drawn next rather than anything already on the canvas.
        A no-op both when nothing was selected yet and when this particular
        click only continued the chain without creating a new member (e.g.
        clicking the same node the chain already ends on)."""
        if not new_element_tags or self._active_element_kwargs is None:
            return
        previous_selection = set(self.canvas.selected_elements)
        self.canvas.selected_elements = set(new_element_tags)
        # Drawing already recorded "before this member existed". A second
        # snapshot here restored to a section-less stick on the first
        # Ctrl+Z - the thin leftover that needed another undo to vanish.
        with self.canvas.pause_history():
            self.canvas.apply_full_section_to_selection(**self._active_element_kwargs)
        self.canvas.selected_elements = previous_selection | new_element_tags
        if not self._start_in_3d and hasattr(self, "element_assignment_selection_status"):
            count = len(new_element_tags)
            self.element_assignment_selection_status.setText(
                f"✓ 새 부재 {count}개에 현재 물성·단면을 자동 적용했습니다."
            )

    def _apply_active_properties_to_new_2d_members(self) -> None:
        """Give newly drawn 2D members the optional Element-tab definition.

        The 2D canvas creates members internally during mouse interaction,
        so the page cannot wrap that call the way the 3D picker does. The
        model-changed signal is the common commit boundary; tracking known
        tags makes this additive and the recursion guard absorbs the second
        signal emitted by applying the properties themselves.
        """
        current_tags = set(self.canvas.elements)
        new_tags = current_tags - self._known_2d_element_tags
        self._known_2d_element_tags = current_tags
        if (
            self._applying_2d_active_properties
            or self._active_element_kwargs is None
            or not new_tags
        ):
            return
        self._applying_2d_active_properties = True
        try:
            self._apply_active_element_to_new_members(new_tags)
        finally:
            self._known_2d_element_tags = set(self.canvas.elements)
            self._applying_2d_active_properties = False

    def _build_2d_editor_panel(self) -> QScrollArea:
        """The category editor's own left-hand column, independent of the
        read-only Selection Status column on the right (``_build_selection_
        panel``) — the two used to share one vertical splitter, which read
        as a single cluttered panel for something as simple as 노드
        이동·복사/아치. Splitting them mirrors the 3D workbench's
        tools-left/status-right layout: this scroll area is the same fixed
        300px width as the 3D task panel, and needs no manual resizing
        between categories since it is no longer sharing height with
        anything else — a short category (지점) just leaves blank space
        below it instead of stealing height from a sibling pane.
        """
        editor_scroll = self._build_editor_scroll()
        editor_scroll.setFixedWidth(300)
        editor_scroll.setMinimumHeight(160)
        self._editor_scroll = editor_scroll
        return editor_scroll

    def _build_editor_scroll(self) -> QScrollArea:
        """The splitter's top pane: 아무 카테고리도 고르지 않았으면
        비어 있고, 상단 카테고리 바(``_build_category_bar``)에서 하나를
        고르면 그 내용만 여기 나타난다 — 예전엔 노드 추가·이동복사배열만
        항상 떠 있고 나머지(지점/노드유형/부재/하중)는 캔버스 위 아코디언에
        있었는데, 그 비대칭 자체가 발견성 문제였다(부재 노드 삽입은 스크롤해야
        보이는 마지막 섹션이라 처음 쓰는 사람은 있는지도 몰랐다). 지금은
        카테고리 전부 같은 자격으로, 클릭하기 전엔 아무것도 차지하지 않고
        클릭하면 그 하나만 이 폭(320px) 안에서 세로로 펼쳐진다 — 가로 폭
        한계 때문에 글자가 잘리던 문제도 이걸로 같이 해결된다.
        """
        panel = QFrame()
        panel.setObjectName("modelingPropertyPanel")
        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        self.editor_title = QLabel("PROPERTY EDITOR")
        self.editor_title.setObjectName("direct2DInspectorTitle")
        root.addWidget(self.editor_title)
        self.selection_summary = QLabel()
        self.selection_summary.setObjectName("setupSectionTitle")
        self.selection_summary.setWordWrap(True)
        root.addWidget(self.selection_summary)

        root.addWidget(self._build_node_subcategory_row())
        root.addWidget(self._build_element_subcategory_row())
        self.element_subcategory_row.hide()

        self.category_stack = _CurrentPageOnlyStack()
        # QStackedWidget's own vertical size policy still allows it to grow
        # past sizeHint() when this scroll area's widgetResizable(True) hands
        # it more height than the current page needs (every category shorter
        # than 노드 추가/이동·복사 - 지점, 하중, 노드 유형, 부재, 아치). Capping
        # it at Maximum forces that surplus into the trailing addStretch(1)
        # below instead, where it reads as one predictable gap after the
        # panel rather than the stack silently inflating the current page.
        self.category_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.category_stack.currentChanged.connect(lambda _index: self.category_stack.updateGeometry())
        self.category_pages: dict[str, int] = {}
        empty = QLabel("위에서 카테고리를 고르면\n여기에 설정이 표시됩니다.")
        empty.setObjectName("setupSectionHint")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.category_pages["empty"] = self.category_stack.addWidget(empty)
        builders = {
            "add": self._build_add_category,
            "move": (
                self._build_element_translate_section
                if self._start_in_3d
                else self._build_transform_section
            ),
            "arch": self._build_arch_category,
            "support": self._build_support_category,
            "kind": self._build_node_kind_category,
            "member": self._build_member_category,
            "load": self._build_3d_load_category if self._start_in_3d else self._build_load_category,
        }
        for key, _label in self._CATEGORY_OPTIONS:
            self.category_pages[key] = self.category_stack.addWidget(builders[key]())
        self.category_pages["element_picker"] = self.category_stack.addWidget(
            self._build_element_category()
        )
        self.category_pages["rotate"] = self.category_stack.addWidget(
            self._build_rotate_copy_section()
        )
        self.category_pages["mirror"] = self.category_stack.addWidget(
            self._build_mirror_copy_section()
        )
        self.category_pages["analysis"] = self.category_stack.addWidget(
            self._build_analysis_category()
        )
        self.category_pages["story"] = self.category_stack.addWidget(
            self._build_story_category()
        )
        # Node and Element keep separate selection scopes, while each
        # Translate page owns its own MIDAS-style Copy/Move mode.
        self.category_pages["translate_node"] = self.category_stack.addWidget(
            self._build_node_translate_section()
        )
        self.category_pages["rotate_node"] = self.category_stack.addWidget(
            self._build_node_rotate_copy_section()
        )
        self.category_pages["mirror_node"] = self.category_stack.addWidget(
            self._build_node_mirror_copy_section()
        )
        self.category_stack.setCurrentIndex(self.category_pages["empty"])
        root.addWidget(self.category_stack)
        root.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("modelingInspectorScroll")
        scroll.setWidgetResizable(True)
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
        self.support_angle_axis: QComboBox | None = None
        if self._start_in_3d:
            # Only a 3D model can need an incline that isn't in the XY plane
            # - 2D always rotates about Z (this combo's default), matching
            # this project's original 2D-only convention exactly, so the 2D
            # workspace never shows this row at all.
            axis_row = QHBoxLayout()
            axis_row.addWidget(QLabel("회전축"))
            self.support_angle_axis = QComboBox()
            self.support_angle_axis.setObjectName("supportAngleAxisSelector")
            for key, label in (("x", "X축"), ("y", "Y축"), ("z", "Z축(수직)")):
                self.support_angle_axis.addItem(label, key)
            self.support_angle_axis.setCurrentIndex(self.support_angle_axis.findData("z"))
            self.support_angle_axis.setToolTip(
                "경사각(°)이 어느 전역축을 기준으로 회전하는지 선택합니다."
            )
            self.support_angle_axis.currentIndexChanged.connect(
                lambda _index: self._apply_support()
            )
            axis_row.addWidget(self.support_angle_axis, 1)
            root.addLayout(axis_row)
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
        # Rows 0/2 hold the checkboxes (translation, then rotation); rows 1/3
        # hold this legend, directly under its matching checkbox row - *2 on
        # the checkbox row leaves that gap for the legend rather than the
        # legend colliding with the row 1 that i // 3 would otherwise put
        # rotation's own checkboxes in.
        self.support_dof_checks: dict[str, QCheckBox] = {}
        for i, dof in enumerate(("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")):
            box = QCheckBox(dof)
            box.toggled.connect(self._apply_support)
            self.support_dof_checks[dof] = box
            custom_layout.addWidget(box, (i // 3) * 2, i % 3)
        self.support_dof_legend_cells: dict[str, QWidget] = {}
        for i, (name, kind, color) in enumerate(DOF_LEGEND):
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(3)
            icon = QLabel()
            icon.setPixmap(_render_dof_icon(kind, color))
            icon.setFixedSize(20, 20)
            cell_layout.addWidget(icon)
            text = QLabel(name)
            text.setStyleSheet(f"color: {color}; font-weight: 700;")
            cell_layout.addWidget(text)
            cell_layout.addStretch(1)
            custom_layout.addWidget(cell, (i // 3) * 2 + 1, i % 3)
            self.support_dof_legend_cells[name] = cell
        legend_hint = QLabel(
            "체크 = 그 방향으로 이동(Ux/Uy/Uz)하거나 그 축 둘레로 회전(Rx/Ry/Rz)하지 "
            "못하도록 구속 · 해제 = 자유"
        )
        legend_hint.setWordWrap(True)
        legend_hint.setObjectName("setupSectionHint")
        custom_layout.addWidget(legend_hint, 4, 0, 1, 3)
        if self._start_in_3d:
            # Elastic (finite-stiffness) support - a separate small grid
            # below the DOF checkboxes/legend rather than interleaved with
            # them, so this never has to touch that grid's existing
            # row/column scheme. Only ever read when the CUSTOM preset is
            # active (see _apply_support) - a rigidly-restrained DOF ignores
            # its own spring value regardless (BoundaryCondition.
            # spring_stiffnesses' own docstring).
            spring_header = QLabel("탄성 스프링 강성 (구속 해제한 방향에만 적용, 0 = 스프링 없음)")
            spring_header.setObjectName("setupSectionHint")
            spring_header.setWordWrap(True)
            custom_layout.addWidget(spring_header, 5, 0, 1, 3)
            # A single spanning cell holding its own vertical list of rows,
            # not six cells spread across the checkbox grid's own 3 columns -
            # "Ux (kN/m)" plus a spin box is far wider than a bare "Ux"
            # checkbox, so sharing those columns forced them to balloon well
            # past the panel's fixed 320px width (visible as the whole left
            # dock widening and the Story Manager button below getting
            # clipped). One column at a time keeps this cell's own minimum
            # width to a single label+field, which always fits.
            spring_section = QWidget()
            spring_layout = QVBoxLayout(spring_section)
            spring_layout.setContentsMargins(0, 0, 0, 0)
            spring_layout.setSpacing(4)
            self.support_spring_fields: dict[str, SafeDoubleSpinBox] = {}
            self.support_spring_field_labels: dict[str, QLabel] = {}
            for dof in ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz"):
                field_row = QWidget()
                field_layout = QHBoxLayout(field_row)
                field_layout.setContentsMargins(0, 0, 0, 0)
                field_layout.setSpacing(4)
                dof_label = QLabel(dof)
                dof_label.setFixedWidth(80)
                field_layout.addWidget(dof_label)
                self.support_spring_field_labels[dof] = dof_label
                field = self._number(0.0)
                field.editingFinished.connect(self._apply_support)
                field_layout.addWidget(field, 1)
                self.support_spring_fields[dof] = field
                spring_layout.addWidget(field_row)
            custom_layout.addWidget(spring_section, 6, 0, 1, 3)
            self._refresh_support_spring_unit_labels()
        self.support_custom_row.setVisible(False)
        root.addWidget(self.support_custom_row)

        root.addStretch(1)
        return section

    def _build_story_category(self) -> QWidget:
        """Story tab left dock: short guidance + launcher for the dedicated
        Story Manager dialog (auto-detect floors, per-story elevation, rigid
        diaphragm on/off). The real editing UI stays in that small window so
        the modeling viewport is not crowded with a floor table.
        """
        section, root = self._section("Story", show_title=False)
        if not self._start_in_3d:
            hint = QLabel(
                "Story(층)와 강체 다이아프램은 3D 건물 모델에서만 사용합니다."
            )
            hint.setObjectName("setupSectionHint")
            hint.setWordWrap(True)
            root.addWidget(hint)
            root.addStretch(1)
            return section

        hint = QLabel(
            "절점 Z좌표로 층을 자동 인식하고, 층마다 노드 높이와 강체 다이아프램 "
            "사용/미사용을 설정합니다. Auto로 층을 만든 뒤 횡력(지진·풍) 해석에 "
            "필요한 다이아프램만 켜면 됩니다."
        )
        hint.setObjectName("setupSectionHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        story_button = QPushButton("Story Manager (층 관리)...")
        story_button.setObjectName("storyManagerButton")
        story_button.setToolTip(
            "별도 창에서 층 자동 감지, 노드 높이, 강체 다이아프램 사용/미사용을 설정합니다."
        )
        story_button.clicked.connect(self._open_story_manager)
        root.addWidget(story_button)
        root.addStretch(1)
        return section

    def _open_story_manager(self) -> None:
        dialog = StoryManagerDialog(self.canvas, unit_system=self._unit_system, parent=self)
        dialog.exec()
        self._refresh_3d_preview()

    def _build_node_kind_category(self) -> QWidget:
        section, root = self._section("노드 유형", show_title=False)
        root.addWidget(self._build_node_kind_icon_row())
        root.addStretch(1)
        return section

    def _build_member_category(self) -> QWidget:
        section, root = self._section("부재", show_title=False)
        root.addWidget(self._build_member_bar_content())
        root.addStretch(1)
        return section

    # ================================================================
    # 3D Loads tab (canvas_load_entries.py's own store - see that file's
    # module docstring for why this is entirely separate from the 2D/legacy
    # nodal_loads/element_loads path just below). Nothing here reaches the
    # solver yet.
    # ================================================================

    _LOAD3D_KIND_GROUPS: ClassVar[tuple[tuple[tuple[str, ...], str, str], ...]] = (
        (("nodal",), "Nodal Loads", "NL"),
        (
            ("member_point", "member_moment", "member_uniform", "member_linear", "member_partial"),
            "Member Loads",
            "ML",
        ),
        (("floor",), "Floor Loads", "FL"),
        (("self_weight",), "Self Weight", "SW"),
    )

    def _build_load_category(self) -> QWidget:
        section, root = self._section("하중", show_title=False)
        root.addWidget(self._build_load_bar_content())
        root.addStretch(1)
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
        root.addStretch(1)
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
        root.addStretch(1)
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
        default_coordinate = "0, 0, 0" if self._start_in_3d else "0, 0"
        self.node_xy = QLineEdit(default_coordinate)
        # Public 3D-facing alias; node_xy remains for the existing 2D API and
        # project tests that already use the combined X/Y field.
        self.node_xyz = self.node_xy
        self.node_xy.setPlaceholderText(default_coordinate)
        self.node_xy.setToolTip(
            "현재 길이 단위로 좌표를 입력합니다 — 쉼표, 공백, 괄호 형식을 모두 사용할 수 있습니다."
        )
        self.node_dx = self._number(1.0)
        self.node_dy = self._number(0.0)
        self.node_repeat = SafeSpinBox()
        self.node_repeat.setRange(1, 1000)
        self.node_coordinate_label = QLabel()
        self.node_dx_label = QLabel()
        self.node_dy_label = QLabel()
        form.addRow(self.node_coordinate_label, self.node_xy)
        form.addRow(self.node_dx_label, self.node_dx)
        form.addRow(self.node_dy_label, self.node_dy)
        if self._start_in_3d:
            self.node_dz = self._number(0.0)
            self.node_dz_label = QLabel()
            form.addRow(self.node_dz_label, self.node_dz)
        form.addRow("생성 개수", self.node_repeat)
        root.addLayout(form)
        add = QPushButton("노드 추가")
        add.clicked.connect(self._add_nodes_from_coordinates)
        root.addWidget(add)
        self.create_section_hint = QLabel()
        self.create_section_hint.setWordWrap(True)
        self.create_section_hint.setObjectName("setupSectionHint")
        root.addWidget(self.create_section_hint)
        self._refresh_create_section_unit_labels()
        self._refresh_create_section_hint()
        return section

    def _refresh_create_section_unit_labels(self) -> None:
        if not hasattr(self, "node_coordinate_label"):
            return
        length = self._unit_system.length
        if self._start_in_3d:
            self.node_coordinate_label.setText(f"좌표 (X, Y, Z) [{length}]")
        else:
            self.node_coordinate_label.setText(f"좌표 (X, Y) [{length}]")
        self.node_dx_label.setText(f"증분 dX ({length})")
        self.node_dy_label.setText(f"증분 dY ({length})")
        if hasattr(self, "node_dz_label"):
            self.node_dz_label.setText(f"증분 dZ ({length})")

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
            origin = "0, 0, 0" if self._start_in_3d else "0, 0"
            self.create_section_hint.setText(
                f"원점({origin}) 기준으로 추가합니다. 노드를 하나 선택하면 그 노드가 "
                "기준점이 됩니다."
            )
        else:
            self.create_section_hint.setText(
                f"노드 {selected}개가 선택돼 기준점이 모호합니다 — 지금은 원점(0, 0) 기준으로 "
                "추가됩니다. 노드를 하나만 선택하면 그 노드가 기준점이 됩니다."
            )

    def _build_support_icon_row(self) -> QWidget:
        """Icon buttons for 지점 조건, one per ``self._support_options`` entry,
        applied the moment you click one — no separate 적용 button, matching
        the instant-apply feel of the 부재 단부 핀 해제 checkboxes below. Each
        icon mirrors the symbol ``SupportItem`` draws on the canvas so the
        button you clicked and the glyph that appears on the model read as
        the same shape.

        3D gets its own preset set (``_SUPPORT_OPTIONS_3D``, 6-DOF-complete)
        instead of reusing 2D's 3-tuple ``_SUPPORT_OPTIONS`` - those used to
        get silently zero-padded to 6 DOF at solve time, which meant "고정"
        left every rotation free and "핀" left Uz free, both wrong. Picked
        once here off ``self._start_in_3d`` (stable for the page's whole
        lifetime, unlike ``self.canvas.ndm`` which ``enter_3d_mode()`` only
        flips to 3 partway through construction) and reused by every other
        method below instead of the module-level constants directly.

        A 3-column grid, not one long row - six-plus icons abreast never fit
        the 우측 패널's fixed 300px width, and this is exactly the kind of
        "more icons added over time, no more horizontal room" clipping the
        category bar itself used to hit. A grid just adds another row
        instead of squeezing.
        """
        self._support_options = _SUPPORT_OPTIONS_3D if self._start_in_3d else _SUPPORT_OPTIONS
        row = QWidget()
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.support_group = QButtonGroup(self)
        self.support_group.setExclusive(True)
        self.support_buttons: dict[int, QToolButton] = {}
        columns = 3
        for index, (label, tooltip, glyph_key, _restraints) in enumerate(self._support_options):
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
        is_custom = checked is not None and self._support_options[self.support_group.id(checked)][3] is None
        self.support_custom_row.setVisible(is_custom)
        three_d = self.canvas.ndm == 3
        for dof, box in self.support_dof_checks.items():
            visible = three_d or dof in {"Ux", "Uy", "Rz"}
            box.setVisible(visible)
            self.support_dof_legend_cells[dof].setVisible(visible)

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
        if self.support_angle_axis is not None:
            axis_index = self.support_angle_axis.findData(boundary.angle_axis if boundary else "z")
            self.support_angle_axis.blockSignals(True)
            self.support_angle_axis.setCurrentIndex(axis_index if axis_index != -1 else self.support_angle_axis.findData("z"))
            self.support_angle_axis.blockSignals(False)

        dof = 6 if self.canvas.ndm == 3 else 3
        restraints = tuple(boundary.restraints[:dof]) if boundary else ()
        restraints += (False,) * (dof - len(restraints))
        preset_index = next(
            (
                index
                for index, (_, _, _, template) in enumerate(self._support_options)
                if template is not None and len(template) == dof and tuple(template) == restraints
            ),
            None,
        )
        if preset_index is not None:
            self.support_buttons[preset_index].setChecked(True)
        else:
            self.support_buttons[len(self._support_options) - 1].setChecked(True)  # 커스텀
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
        template = self._support_options[self.support_group.id(checked)][3]
        if template is None:
            order = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz") if self.canvas.ndm == 3 else ("Ux", "Uy", "Rz")
            restraints = tuple(self.support_dof_checks[dof].isChecked() for dof in order)
        else:
            restraints = template
        spring_stiffnesses: tuple[float | None, ...] = ()
        if template is None and hasattr(self, "support_spring_fields"):
            spring_stiffnesses = tuple(
                self.support_spring_fields[dof].value() or None
                for dof in ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
            )
        angle_axis = (
            self.support_angle_axis.currentData()
            if self.support_angle_axis is not None
            else "z"
        )
        self.canvas.apply_support_to_selection(
            restraints, self.support_angle.value(), spring_stiffnesses, angle_axis
        )
        self._sync_selection_status()

    def _build_transform_section(self) -> QWidget:
        """2D quick Translate page with Copy/Move modes and repeat count."""
        section, root = self._section("이동", show_title=False)
        transform_hint = QLabel(
            "위쪽 툴바의 '선택 필터'를 노드만/부재만으로 바꿔 옮기거나 "
            "복사할 대상을 고르세요 — 부재를 선택하면 양쪽 끝 노드까지 함께 "
            "이동·복사됩니다."
        )
        transform_hint.setWordWrap(True)
        transform_hint.setObjectName("setupSectionHint")
        root.addWidget(transform_hint)
        root.addWidget(QLabel("Mode"))
        self.node_transform_operation = QComboBox()
        self.node_transform_operation.addItem("Copy", "copy")
        self.node_transform_operation.addItem("Move", "move")
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
        form.addRow("Number of Times", self.node_transform_repeat)
        root.addLayout(form)
        self.copy_node_attributes = QCheckBox("Copy Node Attributes (지점·절점하중)")
        self.copy_node_attributes.setChecked(False)
        root.addWidget(self.copy_node_attributes)
        self.copy_element_loads = QCheckBox("Copy Element Loads (부재하중)")
        self.copy_element_loads.setChecked(False)
        root.addWidget(self.copy_element_loads)
        self._sync_transform_form()
        apply_button = QPushButton("선택 항목에 적용")
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
        # Without this, the two setupSectionHint labels above (transform_hint,
        # mirror_hint) were the only vertically-growable items in this layout -
        # every field/button/combo around them has a Fixed policy - so whenever
        # this page was allocated more height than its content needs (which
        # the scroll area's widgetResizable(True) does for any page shorter
        # than the splitter's editor pane), Qt had nowhere else to put the
        # surplus and stretched those two labels instead. A QLabel's text
        # stays top-aligned inside its own box, so the label itself looked
        # unchanged while a large blank gap opened up right below it - twice
        # (once after each hint), not once at the end where it would read as
        # ordinary trailing whitespace. An explicit trailing stretch gives Qt
        # something that actually wants the surplus, so every control here
        # keeps its natural size and any leftover space collects in one place
        # at the bottom instead.
        root.addStretch(1)
        return section

    def _build_transform_offset_form(
        self, *, dx_label: str = "dX", dy_label: str = "dY"
    ) -> tuple[QFormLayout, QDoubleSpinBox, QDoubleSpinBox]:
        """The center X/Y pair used by the Node and Element rotate-copy pages.

        Local widgets avoid the two pages overwriting each other's references.
        """
        form = QFormLayout()
        dx_field = self._number(1.0)
        dy_field = self._number(0.0)
        form.addRow(dx_label, dx_field)
        form.addRow(dy_label, dy_field)
        return form, dx_field, dy_field

    def _build_offset_line_form(self) -> tuple[QFormLayout, QLineEdit]:
        """Build the dimension-appropriate offset line for this document."""
        form = QFormLayout()
        if self._start_in_3d:
            offset_field = QLineEdit("0, 0, 0")
            offset_field.setPlaceholderText("dX, dY, dZ")
            offset_field.setToolTip(
                "쉼표 또는 공백으로 구분 — 예: \"3, 5, 2\". dZ는 현재 "
                "작업평면의 법선(수직) 축입니다."
            )
            form.addRow("dX, dY, dZ", offset_field)
        else:
            offset_field = QLineEdit("0, 0")
            offset_field.setPlaceholderText("dX, dY")
            offset_field.setToolTip("쉼표 또는 공백으로 구분 — 예: \"3, 5\".")
            form.addRow("dX, dY", offset_field)
        return form, offset_field

    @staticmethod
    def _parse_offset_line(
        text: str, *, include_z: bool = True
    ) -> tuple[float, float, float]:
        """Parse an ``_build_offset_line_form`` line into ``(dx, dy, dz)`` -
        2D callers explicitly discard a third token and always receive dz=0."""
        tokens = [token for token in re.split(r"[,\s]+", text.strip()) if token]
        values: list[float] = []
        component_count = 3 if include_z else 2
        for token in tokens[:component_count]:
            try:
                values.append(float(token))
            except ValueError:
                return (0.0, 0.0, 0.0)
        while len(values) < 3:
            values.append(0.0)
        return (values[0], values[1], values[2])

    def _build_transform_copy_option_checkboxes(
        self, root: QVBoxLayout
    ) -> tuple[QCheckBox, QCheckBox]:
        copy_node_cb = QCheckBox("Copy Node Attributes (지점·절점하중)")
        root.addWidget(copy_node_cb)
        copy_element_cb = QCheckBox("Copy Element Loads (부재하중)")
        root.addWidget(copy_element_cb)
        return copy_node_cb, copy_element_cb

    def _build_element_translate_section(self) -> QWidget:
        """Element Translate with MIDAS-style Copy/Move modes.

        Node and Element remain separate tools because Element translation
        carries both end nodes and the selected member. Linear array copying
        is simply Copy with ``Number of Times`` greater than one, so a second
        Duplicate/Array page would only repeat this form.
        """
        section, root = self._section("Element Translate", show_title=False)
        hint = QLabel(
            "부재를 선택하면 양쪽 끝 노드와 함께 복사됩니다. dX/dY는 현재 작업평면의 "
            "로컬 축, dZ는 그 평면의 법선(수직) 축 기준입니다."
        )
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)

        root.addWidget(QLabel("Mode"))
        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.element_translate_copy_mode = QRadioButton("Copy")
        self.element_translate_move_mode = QRadioButton("Move")
        self.element_translate_mode_group = QButtonGroup(section)
        self.element_translate_mode_group.addButton(self.element_translate_copy_mode)
        self.element_translate_mode_group.addButton(self.element_translate_move_mode)
        mode_layout.addWidget(self.element_translate_copy_mode)
        mode_layout.addWidget(self.element_translate_move_mode)
        mode_layout.addStretch(1)
        root.addWidget(mode_row)

        form, offset_field = self._build_offset_line_form()
        self.element_translate_offset = offset_field
        self.element_translate_repeat = SafeSpinBox()
        self.element_translate_repeat.setRange(1, 1000)
        form.addRow("Number of Times", self.element_translate_repeat)
        root.addLayout(form)

        (
            self.element_translate_copy_node_attributes,
            self.element_translate_copy_element_loads,
        ) = self._build_transform_copy_option_checkboxes(root)
        self.element_translate_apply_button = QPushButton("선택 부재 복사")

        def _sync_mode() -> None:
            is_copy = self.element_translate_copy_mode.isChecked()
            axis_note = (
                " dX/dY는 현재 작업평면의 로컬 축, dZ는 그 평면의 "
                "법선(수직) 축 기준입니다."
                if self._start_in_3d
                else ""
            )
            form.setRowVisible(self.element_translate_repeat, is_copy)
            self.element_translate_copy_node_attributes.setVisible(is_copy)
            self.element_translate_copy_element_loads.setVisible(is_copy)
            self.element_translate_apply_button.setText(
                "선택 부재 복사" if is_copy else "선택 부재 이동"
            )
            hint.setText(
                (
                    (
                        "부재를 선택하면 양쪽 끝 노드와 함께 복사됩니다. "
                        "Number of Times만큼 같은 간격으로 반복 복사합니다."
                    )
                    if is_copy
                    else "부재를 선택하면 양쪽 끝 노드와 함께 이동됩니다."
                )
                + axis_note
            )

        def _apply() -> None:
            dx, dy, dz = self._parse_offset_line(
                offset_field.text(), include_z=self._start_in_3d
            )
            if self.element_translate_move_mode.isChecked():
                if self._start_in_3d:
                    self.canvas.transform_selected_nodes("move", dx, dy, dz=dz)
                else:
                    self.canvas.transform_selected_nodes("move", dx, dy)
                return
            kwargs = {
                "copy_node_attributes": self.element_translate_copy_node_attributes.isChecked(),
                "copy_element_loads": self.element_translate_copy_element_loads.isChecked(),
            }
            if self._start_in_3d:
                self.canvas.transform_selected_nodes(
                    "copy",
                    dx,
                    dy,
                    self.element_translate_repeat.value(),
                    dz=dz,
                    **kwargs,
                )
            else:
                self.canvas.transform_selected_nodes(
                    "copy", dx, dy, self.element_translate_repeat.value(), **kwargs
                )

        self.element_translate_copy_mode.toggled.connect(_sync_mode)
        self.element_translate_apply_button.clicked.connect(_apply)
        root.addWidget(self.element_translate_apply_button)
        self.element_translate_copy_mode.setChecked(True)
        _sync_mode()
        root.addStretch(1)
        return section

    def _build_rotate_copy_section(self) -> QWidget:
        section, root = self._section("Element Rotate Copy", show_title=False)
        hint = QLabel("부재를 선택하면 중심점 기준으로 회전 복사됩니다.")
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)
        form, center_x_field, center_y_field = self._build_transform_offset_form(
            dx_label="중심 X", dy_label="중심 Y"
        )
        angle_field = self._number(90.0)
        angle_field.setToolTip(
            "복사할 때마다 누적되는 회전각 — 예: 3개·30°면 원본 기준 30°/60°/90° 위치에 복사됩니다."
        )
        form.addRow("회전각(°)", angle_field)
        repeat_field = SafeSpinBox()
        repeat_field.setRange(1, 1000)
        form.addRow("반복 개수", repeat_field)
        dz_field: QDoubleSpinBox | None = None
        if self._start_in_3d:
            dz_field = self._number(0.0)
            dz_field.setToolTip(
                "반복마다 누적되는 법선(수직) 축 이동량 — 나선형 계단처럼 회전하면서 "
                "동시에 올라가는 복사에 사용합니다. 0이면 순수 평면 회전 복사입니다."
            )
            form.addRow("반복당 dZ", dz_field)
        root.addLayout(form)
        copy_node_cb, copy_element_cb = self._build_transform_copy_option_checkboxes(root)
        apply_button = QPushButton("선택 항목에 적용")

        def _apply() -> None:
            if dz_field is None:
                self.canvas.rotate_copy_selection(
                    center_x_field.value(),
                    center_y_field.value(),
                    angle_field.value(),
                    repeat_field.value(),
                    copy_node_attributes=copy_node_cb.isChecked(),
                    copy_element_loads=copy_element_cb.isChecked(),
                )
                return
            self.canvas.rotate_copy_selection(
                center_x_field.value(),
                center_y_field.value(),
                angle_field.value(),
                repeat_field.value(),
                dz=dz_field.value(),
                copy_node_attributes=copy_node_cb.isChecked(),
                copy_element_loads=copy_element_cb.isChecked(),
            )

        apply_button.clicked.connect(_apply)
        root.addWidget(apply_button)
        root.addStretch(1)
        return section

    def _build_mirror_copy_section(self) -> QWidget:
        section, root = self._section("Element Mirror Copy", show_title=False)
        hint = QLabel("대칭 복사 — 절반만 그린 뒤 축을 기준으로 나머지를 만듭니다.")
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)
        mirror_row = QHBoxLayout()
        axis_field = QComboBox()
        axis_field.addItem("수직선 X =", "x")
        axis_field.addItem("수평선 Y =", "y")
        mirror_row.addWidget(axis_field)
        value_field = self._number(0.0)
        mirror_row.addWidget(value_field, 1)
        root.addLayout(mirror_row)
        copy_node_cb, copy_element_cb = self._build_transform_copy_option_checkboxes(root)
        apply_button = QPushButton("선택 노드 대칭 복사")

        def _apply() -> None:
            self.canvas.mirror_selection(
                axis_field.currentData(),
                value_field.value(),
                copy_node_attributes=copy_node_cb.isChecked(),
                copy_element_loads=copy_element_cb.isChecked(),
            )

        apply_button.clicked.connect(_apply)
        root.addWidget(apply_button)
        root.addStretch(1)
        return section

    def _build_node_translate_section(self) -> QWidget:
        """Node-only MIDAS-style Translate page with Copy/Move modes."""
        section, root = self._section("Node Translate", show_title=False)
        hint = QLabel("선택한 노드를 지정한 간격으로 복사합니다.")
        if self._start_in_3d:
            hint.setText(
                "선택한 노드를 지정한 간격으로 복사합니다. dZ는 현재 작업평면의 "
                "법선(수직) 축입니다."
            )
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)

        root.addWidget(QLabel("Mode"))
        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.node_translate_copy_mode = QRadioButton("Copy")
        self.node_translate_move_mode = QRadioButton("Move")
        self.node_translate_mode_group = QButtonGroup(section)
        self.node_translate_mode_group.addButton(self.node_translate_copy_mode)
        self.node_translate_mode_group.addButton(self.node_translate_move_mode)
        mode_layout.addWidget(self.node_translate_copy_mode)
        mode_layout.addWidget(self.node_translate_move_mode)
        mode_layout.addStretch(1)
        root.addWidget(mode_row)

        form, offset_field = self._build_offset_line_form()
        self.node_translate_offset = offset_field
        self.node_translate_repeat = SafeSpinBox()
        self.node_translate_repeat.setRange(1, 1000)
        form.addRow("Number of Times", self.node_translate_repeat)
        root.addLayout(form)
        self.node_translate_copy_node_attributes = QCheckBox(
            "Copy Node Attributes (지점·절점하중)"
        )
        root.addWidget(self.node_translate_copy_node_attributes)
        self.node_translate_apply_button = QPushButton("선택 노드 복사")

        def _sync_mode() -> None:
            is_copy = self.node_translate_copy_mode.isChecked()
            axis_note = (
                " dZ는 현재 작업평면의 법선(수직) 축입니다."
                if self._start_in_3d
                else ""
            )
            form.setRowVisible(self.node_translate_repeat, is_copy)
            self.node_translate_copy_node_attributes.setVisible(is_copy)
            self.node_translate_apply_button.setText(
                "선택 노드 복사" if is_copy else "선택 노드 이동"
            )
            hint.setText(
                (
                    (
                        "선택한 노드를 지정한 간격으로 Number of Times만큼 반복 복사합니다."
                    )
                    if is_copy
                    else "선택한 노드를 지정한 만큼 이동합니다."
                )
                + axis_note
            )

        def _apply() -> None:
            dx, dy, dz = self._parse_offset_line(
                offset_field.text(), include_z=self._start_in_3d
            )
            if self.node_translate_move_mode.isChecked():
                if not self._start_in_3d:
                    self.canvas.transform_selected_nodes("move", dx, dy)
                    return
                self.canvas.transform_selected_nodes("move", dx, dy, dz=dz)
                return
            if not self._start_in_3d:
                self.canvas.transform_selected_nodes(
                    "copy",
                    dx,
                    dy,
                    self.node_translate_repeat.value(),
                    copy_node_attributes=self.node_translate_copy_node_attributes.isChecked(),
                )
                return
            self.canvas.transform_selected_nodes(
                "copy",
                dx,
                dy,
                self.node_translate_repeat.value(),
                dz=dz,
                copy_node_attributes=self.node_translate_copy_node_attributes.isChecked(),
            )

        self.node_translate_copy_mode.toggled.connect(_sync_mode)
        self.node_translate_apply_button.clicked.connect(_apply)
        root.addWidget(self.node_translate_apply_button)
        self.node_translate_copy_mode.setChecked(True)
        _sync_mode()
        root.addStretch(1)
        return section

    def _build_node_rotate_copy_section(self) -> QWidget:
        section, root = self._section("Node Rotate Copy", show_title=False)
        hint = QLabel("선택한 노드를 중심점 기준으로 회전 복사합니다.")
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)
        form, center_x_field, center_y_field = self._build_transform_offset_form(
            dx_label="중심 X", dy_label="중심 Y"
        )
        angle_field = self._number(90.0)
        angle_field.setToolTip(
            "복사할 때마다 누적되는 회전각 — 예: 3개·30°면 원본 기준 30°/60°/90° 위치에 복사됩니다."
        )
        form.addRow("회전각(°)", angle_field)
        repeat_field = SafeSpinBox()
        repeat_field.setRange(1, 1000)
        form.addRow("반복 개수", repeat_field)
        dz_field: QDoubleSpinBox | None = None
        if self._start_in_3d:
            dz_field = self._number(0.0)
            dz_field.setToolTip(
                "반복마다 누적되는 법선(수직) 축 이동량 — 나선형 계단처럼 회전하면서 "
                "동시에 올라가는 복사에 사용합니다. 0이면 순수 평면 회전 복사입니다."
            )
            form.addRow("반복당 dZ", dz_field)
        root.addLayout(form)
        copy_node_cb, copy_element_cb = self._build_transform_copy_option_checkboxes(root)
        apply_button = QPushButton("선택 항목에 적용")

        def _apply() -> None:
            if dz_field is None:
                self.canvas.rotate_copy_selection(
                    center_x_field.value(),
                    center_y_field.value(),
                    angle_field.value(),
                    repeat_field.value(),
                    copy_node_attributes=copy_node_cb.isChecked(),
                    copy_element_loads=copy_element_cb.isChecked(),
                )
                return
            self.canvas.rotate_copy_selection(
                center_x_field.value(),
                center_y_field.value(),
                angle_field.value(),
                repeat_field.value(),
                dz=dz_field.value(),
                copy_node_attributes=copy_node_cb.isChecked(),
                copy_element_loads=copy_element_cb.isChecked(),
            )

        apply_button.clicked.connect(_apply)
        root.addWidget(apply_button)
        root.addStretch(1)
        return section

    def _build_node_mirror_copy_section(self) -> QWidget:
        section, root = self._section("Node Mirror Copy", show_title=False)
        hint = QLabel("대칭 복사 — 절반만 그린 뒤 축을 기준으로 나머지를 만듭니다.")
        hint.setWordWrap(True)
        hint.setObjectName("setupSectionHint")
        root.addWidget(hint)
        mirror_row = QHBoxLayout()
        axis_field = QComboBox()
        axis_field.addItem("수직선 X =", "x")
        axis_field.addItem("수평선 Y =", "y")
        mirror_row.addWidget(axis_field)
        value_field = self._number(0.0)
        mirror_row.addWidget(value_field, 1)
        root.addLayout(mirror_row)
        copy_node_cb, copy_element_cb = self._build_transform_copy_option_checkboxes(root)
        apply_button = QPushButton("선택 노드 대칭 복사")

        def _apply() -> None:
            self.canvas.mirror_selection(
                axis_field.currentData(),
                value_field.value(),
                copy_node_attributes=copy_node_cb.isChecked(),
                copy_element_loads=copy_element_cb.isChecked(),
            )

        apply_button.clicked.connect(_apply)
        root.addWidget(apply_button)
        root.addStretch(1)
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
        """Section/material plus per-end pin release, for one selected member
        — the content shown on the 부재 category page. Mid-span node
        insertion and equal subdivision live on their own 노드 분할 category
        page instead (``_build_member_edit_section``) — they add
        nodes/geometry rather than set a property on the member itself.

        A member always has two ends regardless of which node tags they land on, so
        the checkboxes are labelled with the actual node numbers when the selection
        changes rather than fixed "start/end" text.

        Section input is per member (select one, type its own dimensions or
        pick a Master DB designation), not one global value for the whole
        model — a hand-drawn cantilever, portal frame etc. can freely mix
        member sizes. ``SectionMaterialPanel`` owns everything section/
        material-shaped (see its own module docstring for the Custom/
        Database split); this method only wires its ``apply_requested``
        signal to the canvas and keeps the two pin-release checkboxes, which
        are a per-member property but not a section/material one.
        """
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.section_material_panel = SectionMaterialPanel()
        self.section_material_panel.set_compact_mode()
        # Properties has the same reusable material/section workflow in 2D
        # and 3D. Element creation may consume a saved pair, while applying
        # directly to selected existing members remains available.
        self.section_material_panel.set_visible_groups(material=True, section=True)
        self.section_material_panel.material_saved.connect(self._save_user_material)
        self.section_material_panel.section_saved.connect(self._save_user_section)
        self.section_material_panel.property_set_saved.connect(
            self._activate_saved_property_set
        )
        self.section_material_panel.apply_button.setVisible(True)
        if not self._start_in_3d:
            self.section_material_panel.set_streamlined_assignment_mode()
        else:
            self.section_material_panel.apply_button.setText("선택 부재에 물성·단면 적용")
        self.section_material_panel.apply_requested.connect(self._apply_member_section)
        self.section_material_panel.edited.connect(self._selection_status_edited)
        # A single selector owns which card is visible in both dimensions.
        properties_bar = QFrame()
        properties_bar.setObjectName("setupConfigBar")
        properties_bar_layout = QHBoxLayout(properties_bar)
        properties_bar_layout.setContentsMargins(12, 7, 12, 7)
        properties_bar_label = QLabel("PROPERTIES")
        properties_bar_label.setObjectName("fieldLabel")
        properties_bar_layout.addWidget(properties_bar_label)
        self.properties_selector = QComboBox()
        self.properties_selector.addItem("MATERIAL", "material")
        self.properties_selector.addItem("SECTION", "section")
        self.properties_selector.addItem("SECTION PROPERTIES", "section_properties")
        self.properties_selector.currentIndexChanged.connect(
            self._properties_selector_changed
        )
        properties_bar_layout.addWidget(self.properties_selector, 1)
        root.addWidget(properties_bar)
        for group in (
            self.section_material_panel.material_group,
            self.section_material_panel.section_group,
            self.section_material_panel.properties_group,
        ):
            group.set_header_visible(False)
        root.addWidget(self.section_material_panel)
        self._properties_selector_changed()
        section_hint = QLabel(
            "저장한 물성과 섹션은 오른쪽 워크트리에서 관리합니다."
            if self._start_in_3d
            else "정정구조는 없어도 풀리지만, 부정정 구조를 풀거나 실제 처짐 값을 "
            "보려면 선택한 부재마다 입력해야 합니다."
        )
        section_hint.setWordWrap(True)
        section_hint.setObjectName("setupSectionHint")
        root.addWidget(section_hint)

        member_behavior_card, member_behavior_root = self._section("부재 거동 설정")
        self.member_behavior_settings_card = member_behavior_card
        self.member_behavior_hint = QLabel()
        self.member_behavior_hint.setWordWrap(True)
        self.member_behavior_hint.setObjectName("setupSectionHint")
        self.member_behavior_hint.setMaximumWidth(272)
        member_behavior_root.addWidget(self.member_behavior_hint)
        member_behavior_form = QFormLayout()
        member_behavior_form.setContentsMargins(0, 0, 0, 0)
        self.member_gap_field = self._number(0.0)
        self.member_gap_field.setRange(0.0, 1_000_000.0)
        self.member_gap_label = QLabel("초기 갭")
        member_behavior_form.addRow(self.member_gap_label, self.member_gap_field)
        self.member_prestress_field = self._number(0.0)
        self.member_prestress_label = QLabel("프리스트레스")
        member_behavior_form.addRow(self.member_prestress_label, self.member_prestress_field)
        member_behavior_root.addLayout(member_behavior_form)
        self.apply_member_behavior_button = QPushButton("선택 부재에 거동 설정 적용")
        self.apply_member_behavior_button.clicked.connect(
            self._apply_member_behavior_settings
        )
        member_behavior_root.addWidget(self.apply_member_behavior_button)
        member_behavior_card.hide()
        root.addWidget(member_behavior_card)

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

        # 3D에서만 의미가 있음 - vecxz 자동선택이 비대칭 단면(Iy != Iz)의 실제
        # 강축/약축과 다를 수 있어서 회전으로 보정하는 용도. 2D/트러스 부재는
        # 이 필드를 애초에 안 읽으므로(_reference_vector가 3D 프레임에서만
        # 쓰임) 행 자체를 숨긴다 - 가시성은 _refresh_member_section에서 매
        # 선택마다 갱신.
        self.member_local_axis_row = QWidget()
        axis_layout = QVBoxLayout(self.member_local_axis_row)
        axis_layout.setContentsMargins(0, 0, 0, 0)
        axis_layout.setSpacing(6)
        angle_row = QHBoxLayout()
        angle_row.addWidget(QLabel("로컬축 회전각(°)"))
        self.member_local_axis_angle = self._number(0.0)
        self.member_local_axis_angle.setRange(-360.0, 360.0)
        self.member_local_axis_angle.setToolTip(
            "부재 자신의 축을 기준으로 로컬 y/z축을 회전시키는 각도. 0이면 자동선택된 "
            "방향을 그대로 씁니다 - 비대칭 단면(Iy≠Iz)의 강축/약축이 의도와 다르게 "
            "풀릴 때만 조정하면 됩니다."
        )
        self.member_local_axis_angle.editingFinished.connect(self._apply_member_local_axis_angle)
        angle_row.addWidget(self.member_local_axis_angle, 1)
        axis_layout.addLayout(angle_row)
        rotate_row = QHBoxLayout()
        axis_cw_button = QPushButton("↻ 시계 30°")
        axis_cw_button.setToolTip("로컬축 회전각을 시계 방향으로 30°씩 돌리고 바로 적용합니다.")
        axis_cw_button.clicked.connect(lambda: self._rotate_member_local_axis_angle(-30.0))
        rotate_row.addWidget(axis_cw_button)
        axis_ccw_button = QPushButton("↺ 반시계 30°")
        axis_ccw_button.setToolTip("로컬축 회전각을 반시계 방향으로 30°씩 돌리고 바로 적용합니다.")
        axis_ccw_button.clicked.connect(lambda: self._rotate_member_local_axis_angle(30.0))
        rotate_row.addWidget(axis_ccw_button)
        axis_layout.addLayout(rotate_row)
        self.member_local_axis_gizmo_toggle = QCheckBox("3D 뷰에 로컬축 표시")
        self.member_local_axis_gizmo_toggle.setToolTip(
            "선택 여부와 관계없이 모든 3D 부재의 로컬 y축(초록)·z축(분홍)을 3D 뷰에 "
            "짧은 선으로 표시합니다."
        )
        self.member_local_axis_gizmo_toggle.toggled.connect(self._toggle_local_axis_gizmo)
        axis_layout.addWidget(self.member_local_axis_gizmo_toggle)
        root.addWidget(self.member_local_axis_row)
        self.member_local_axis_row.setVisible(self._start_in_3d)

        # 3D beam-column 전용 (2D/트러스는 solver.py가 offset_i/j를 아예 안 읽음) -
        # 로컬축 행과 동일한 숨김/표시 패턴, _refresh_member_section에서 갱신.
        self.member_offset_row = QWidget()
        offset_layout = QFormLayout(self.member_offset_row)
        offset_layout.setContentsMargins(0, 0, 0, 0)
        self.member_offset_i = self._number(0.0)
        self.member_offset_i.setToolTip(
            "i단(첫 번째 절점)에서 부재 축을 따라 강체로 처리할 길이. 0이면 강체 단부 없음."
        )
        self.member_offset_i.editingFinished.connect(self._apply_member_rigid_offsets)
        self.member_offset_i_label = QLabel()
        offset_layout.addRow(self.member_offset_i_label, self.member_offset_i)
        self.member_offset_j = self._number(0.0)
        self.member_offset_j.setToolTip(
            "j단(두 번째 절점)에서 부재 축을 따라 강체로 처리할 길이. 0이면 강체 단부 없음."
        )
        self.member_offset_j.editingFinished.connect(self._apply_member_rigid_offsets)
        self.member_offset_j_label = QLabel()
        offset_layout.addRow(self.member_offset_j_label, self.member_offset_j)
        offset_hint = QLabel("기둥-보 접합부의 패널존처럼, 부재 끝 일부를 휘지 않는 강체로 처리합니다.")
        offset_hint.setObjectName("setupSectionHint")
        offset_hint.setWordWrap(True)
        offset_layout.addRow(offset_hint)
        root.addWidget(self.member_offset_row)
        self.member_offset_row.setVisible(self._start_in_3d)
        self._refresh_member_offset_unit_labels()
        return content

    def _refresh_member_offset_unit_labels(self) -> None:
        if not hasattr(self, "member_offset_i_label"):
            return
        self.member_offset_i_label.setText(f"i단 강체길이 ({self._unit_system.length})")
        self.member_offset_j_label.setText(f"j단 강체길이 ({self._unit_system.length})")

    def _apply_member_rigid_offsets(self) -> None:
        self.canvas.apply_rigid_offset_lengths_to_selection(
            self.member_offset_i.value(), self.member_offset_j.value()
        )

    def _build_load_bar_content(self, *, command_driven: bool = False) -> QWidget:
        """Every applicable load component as its own field, applied together.

        A direction dropdown plus one magnitude field cannot represent Fx and Fy
        at once: applying Fx, then switching the dropdown to Fy and applying
        again, silently discards Fx (each apply replaced the whole load). Showing
        every component side by side and applying them all in one click removes
        the trap instead of asking the user to remember it.

        Laid out as a vertical form (label above/beside its own field, one
        row per component via ``QFormLayout``) now that this lives in the
        left-hand editor panel rather than a fixed-height horizontal bar
        above the canvas - a form just grows another row as fields are
        added instead of running out of horizontal room and clipping text.
        """
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.load_command_form_title = QLabel("하중 설정")
        self.load_command_form_title.setObjectName("loadCommandTitle")
        root.addWidget(self.load_command_form_title)
        if command_driven:
            # The shared Load Case + operation controls live above this
            # settings card.  Only the command-specific diagram belongs here.
            self.load_diagram_label = QLabel()
            self.load_diagram_label.setObjectName("loadDiagramPanel")
            self.load_diagram_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(self.load_diagram_label)
        kind_title = QLabel("하중 종류")
        kind_title.setObjectName("loadStepTitle")
        self.load_target_row = self._build_load_target_icon_row()
        kind_title.setVisible(not command_driven)
        self.load_target_row.setVisible(not command_driven)
        root.addWidget(kind_title)
        root.addWidget(self.load_target_row)
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
        value_title = QLabel("하중 값")
        value_title.setObjectName("loadStepTitle")
        root.addWidget(value_title)
        self.load_coordinate_row = QWidget()
        coordinate_layout = QHBoxLayout(self.load_coordinate_row)
        coordinate_layout.setContentsMargins(0, 0, 0, 0)
        coordinate_layout.setSpacing(6)
        coordinate_label = QLabel("좌표계")
        coordinate_label.setObjectName("setupSectionHint")
        coordinate_layout.addWidget(coordinate_label)
        self.load_coordinate_system = QComboBox()
        self.load_coordinate_system.setObjectName("loadCoordinateSystem")
        self.load_coordinate_system.addItem("GLOBAL X / Y", "global")
        self.load_coordinate_system.addItem("LOCAL x / y", "local")
        self.load_coordinate_system.setToolTip(
            "GLOBAL은 구조물 전체 X/Y축 기준이며 선택된 각 부재의 로컬축으로 자동 "
            "변환됩니다. LOCAL은 부재 i→j 방향의 x축과 그에 수직인 y축 기준입니다."
        )
        self.load_coordinate_system.currentIndexChanged.connect(
            lambda _index: self._load_target_changed()
        )
        coordinate_layout.addWidget(self.load_coordinate_system, 1)
        root.addWidget(self.load_coordinate_row)
        self.load_form_layout = QFormLayout()
        self.load_form_layout.setSpacing(6)
        self.load_fields: dict[str, QDoubleSpinBox] = {}
        root.addLayout(self.load_form_layout)
        self.load_apply_button = QPushButton("선택 대상에 적용")
        self.load_apply_button.setObjectName("loadPrimaryButton")
        self.load_apply_button.setToolTip("선택 대상에 적용 (전체 성분)")
        self.load_apply_button.clicked.connect(self._apply_load)
        root.addWidget(self.load_apply_button)
        self._load_target_changed()
        return content

    def _toggle_load_input_mode(self, checked: bool) -> None:
        self.load_input_mode = "perpendicular" if checked else "component"
        self.load_mode_toggle.setText("성분(Fx,Fy) 직접 입력으로" if checked else "부재 수직 입력으로")
        self._load_target_changed()

    def _refresh_load_command_case_label(self) -> None:
        if not hasattr(self, "load_command_case_label"):
            return
        case = self.canvas.load_cases.get(self.canvas.active_load_case_id)
        self.load_command_case_label.setText(f"Load Case: {case.name if case is not None else '—'}")

    def _current_load_apply_mode(self) -> str:
        """"replace" whenever the Options group does not exist (the 2D path,
        which never builds ``load_apply_mode_group`` - see
        ``_build_load_bar_content``) - identical to what 적용 always did
        before this Options group existed."""
        buttons = getattr(self, "load_apply_mode_buttons", None)
        if not buttons:
            return "replace"
        for key, button in buttons.items():
            if button.isChecked():
                return key
        return "replace"

    def _on_load_apply_mode_changed(self) -> None:
        is_delete = self._current_load_apply_mode() == "delete"
        for field in getattr(self, "load_fields", {}).values():
            field.setEnabled(not is_delete)
        for widget_name in ("load_coordinate_system", "load_mode_toggle", "load3d_form_stack"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setEnabled(not is_delete)
        quick_button = getattr(self, "load_apply_button", None)
        if quick_button is not None:
            quick_button.setText("선택 대상에서 삭제" if is_delete else "선택 대상에 적용")
        entry_button = getattr(self, "load3d_apply_button", None)
        if entry_button is not None and getattr(self, "_editing_load_entry_id", None) is None:
            entry_button.setText("선택 대상에서 삭제" if is_delete else "적용")

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
        """Student-focused result viewer used only by direct 2D modeling."""
        page = QWidget()
        page.setObjectName("direct2DResultPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Both 2D and 3D direct modeling now share the exact same RESULT TYPES
        # sidebar as "OpenSeesPy 파일 불러오기" - the compact 2D-only variant
        # was already too narrow for its own button labels (content wider than
        # its own viewport, clipped with no horizontal scroll to reveal it).
        self.results = ResultsWorkspace(compact_2d=False)
        self.viewport = self.results.viewport
        layout.addWidget(self.results, 1)
        return page

    def _build_status_bar(self) -> QFrame:
        """The unit selector lives here, not just in the setup wizard's first
        step, because the 2D free-modeling path (``start_2d_model``) skips
        that wizard entirely and jumps straight to the canvas — without this,
        a 2D session had no way to ever leave the kN/m default. Changing a
        unit here rescales every already-entered model value (via
        ``set_unit_system`` → ``canvas.convert_units``) and refreshes labels
        so typed coordinates keep meaning the current length unit.
        """
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
            "힘/길이 단위를 바꿉니다. 이미 입력한 좌표·하중·단면 값은 같은 물리량이 "
            "되도록 자동 환산되고, 이후에 입력하는 숫자는 새 단위로 해석됩니다."
        )
        self.unit_force.currentTextChanged.connect(self._unit_selector_changed)
        layout.addWidget(self.unit_force)
        self.unit_length = QComboBox()
        self.unit_length.addItems(LENGTH_UNITS)
        self.unit_length.setCurrentText(self._unit_system.length)
        self.unit_length.setToolTip(self.unit_force.toolTip())
        self.unit_length.currentTextChanged.connect(self._unit_selector_changed)
        layout.addWidget(self.unit_length)
        layout.addSpacing(10)
        layout.addWidget(self.self_weight_toggle)
        layout.addWidget(self.view_results_button)
        return bar

    def _build_result_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("direct2DResultStatusBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 4)
        self.result_model_status = QLabel("0 NODES  |  0 MEMBERS  |  0 SUPPORTS  |  0 LOADS")
        layout.addWidget(self.result_model_status)
        layout.addStretch(1)
        self.result_unit_status = QLabel()
        layout.addWidget(self.result_unit_status)
        return bar

    def _unit_selector_changed(self) -> None:
        self.set_unit_system(UnitSystem(force=self.unit_force.currentText(), length=self.unit_length.currentText()))

    def _workspace_page_changed(self, index: int) -> None:
        showing_results = index == 1
        dimension = "3D" if self._start_in_3d else "2D"
        self.page_title.setText(
            f"{dimension} Structure Results"
            if showing_results
            else f"{dimension} Structure Model"
        )
        self.page_description.setText(
            "Review deformation, reactions and internal forces of the current structural model."
            if showing_results
            else "Create geometry, assign structural properties, boundary conditions and loads."
        )
        self.header_controls_stack.setCurrentIndex(1 if showing_results else 0)
        if not self._start_in_3d:
            self.page_header.setVisible(showing_results or self.workbench_buttons["model"].isChecked())
        if hasattr(self, "workbench_buttons"):
            if showing_results:
                self.workbench_buttons["results"].setChecked(True)
            elif self.workbench_buttons["results"].isChecked():
                self._activate_workbench_tab("model", show_settings=False)

    def _model_type_changed(self) -> None:
        is_truss = self.model_type_selector.currentData() == "truss"
        self.truss_mode_toggle.setChecked(is_truss)

    # --- behaviour ---------------------------------------------------------

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        """Rescale every already-entered value (node coordinates, section
        dimensions, materials, loads, springs, stories, ...) to the new
        units, then refresh every label that shows one - the two are kept
        as separate steps (``canvas.convert_units`` / ``_refresh_unit_
        system_ui``) because ``load_project_dict`` needs the second without
        the first (a freshly-loaded project's raw numbers are already
        expressed in its own saved unit system - converting them again
        against a mismatched "from" would double-convert everything the
        instant a project file is opened).
        """
        factors = unit_conversion_factors(self._unit_system, unit_system)
        if hasattr(self, "wind_q0"):
            if self.wind_calculation_method.currentData() == "direct":
                self.wind_q0.setValue(self.wind_q0.value() * factors.stress)
            self.wind_exposed_width.setValue(
                self.wind_exposed_width.value() * factors.length
            )
            self.seismic_eccentricity.setValue(
                self.seismic_eccentricity.value() * factors.length
            )
        if factors.force != 1.0:
            for name in ("element_prestress_field", "member_prestress_field"):
                field = getattr(self, name, None)
                if field is None:
                    continue
                field.blockSignals(True)
                field.setValue(field.value() * factors.force)
                field.blockSignals(False)
        self.canvas.convert_units(factors)
        self._scale_length_authoring_fields(factors.length)
        if hasattr(self, "element_gap_field"):
            # The spinboxes were rescaled above; the drawing pen still held
            # the pre-conversion numbers until this write-back.
            self._directional_pen_changed()
        self._unit_system = unit_system
        self._refresh_unit_system_ui(unit_system)
        if factors.length != 1.0 and self._start_in_3d and hasattr(self, "preview_3d"):
            # convert_units rebuilds levels as new WorkPlane objects; the
            # plane combo still held the pre-conversion identities, and the
            # 3D camera was still framed around the old (much smaller or
            # larger) extents - both made a unit change look like "nothing
            # moved" while new (0,0,5) clicks landed on the old visual spot.
            self._refresh_plane_selectors()
            self.preview_3d.set_active_plane(
                str(self.canvas.work_plane.kind), self.canvas.work_plane.offset
            )
            self.preview_3d.set_model(self.canvas.authoring_model(), reset_camera=True)

    def _scale_length_authoring_fields(self, length_factor: float) -> None:
        """Keep typed length defaults (node increments, new work-plane
        offset, rigid-end lengths) in the same physical size when the
        length unit changes - otherwise a leftover "1" still shows while
        suddenly meaning 1 mm instead of 1 m.
        """
        if length_factor == 1.0:
            return
        for name in (
            "node_dx",
            "node_dy",
            "node_dz",
            "new_plane_offset",
            "member_offset_i",
            "member_offset_j",
            "element_gap_field",
            "member_gap_field",
        ):
            field = getattr(self, name, None)
            if field is None:
                continue
            field.blockSignals(True)
            field.setValue(field.value() * length_factor)
            field.blockSignals(False)

    def _refresh_unit_system_ui(self, unit_system: UnitSystem) -> None:
        self.results.set_unit_system(unit_system)
        self.result_unit_status.setText(
            f"UNITS: {unit_system.force} · {unit_system.length}"
        )
        # Keep the status-bar selectors in sync when the unit system is set from
        # outside (e.g. the 3D wizard's own setup step) instead of by the user
        # picking directly from these combo boxes — blocked so setCurrentText
        # doesn't re-fire currentTextChanged and call back into this method.
        for combo, value in ((self.unit_force, unit_system.force), (self.unit_length, unit_system.length)):
            combo.blockSignals(True)
            combo.setCurrentText(value)
            combo.blockSignals(False)
        self._load_target_changed()
        self.section_material_panel.set_unit_system(unit_system)
        if hasattr(self, "element_current_property_panel"):
            self.element_current_property_panel.set_unit_system(unit_system)
            self._element_current_properties_edited(clear_saved_selection=False)
        self._refresh_load3d_unit_labels()
        self._refresh_support_spring_unit_labels()
        self._refresh_member_offset_unit_labels()
        self._refresh_directional_unit_labels()
        self._refresh_create_section_unit_labels()
        self._rebuild_grid_snap_options()
        if hasattr(self, "new_plane_offset_label"):
            self.new_plane_offset_label.setText(f"위치 ({unit_system.length})")
            self.new_plane_offset.setToolTip(
                f"평면도는 Z 높이, 정면도는 Y, 측면도는 X 위치입니다. 단위: {unit_system.length}"
            )
        self._sync_selection_status()
        self._refresh_model_settings_summary()

    def _rebuild_grid_snap_options(self) -> None:
        """Grid spacings are authored in the current length unit. Options are
        derived from a fixed meter palette so m/mm/ft/in all get the same
        physical choices, then the live ``canvas.grid`` value is re-selected.
        """
        if not hasattr(self, "snap"):
            return
        length = self._unit_system.length
        from_m = unit_conversion_factors(
            UnitSystem(force=self._unit_system.force, length="m"), self._unit_system
        )
        current = float(self.canvas.grid)
        self.snap.blockSignals(True)
        self.snap.clear()
        best_index = 0
        best_delta = float("inf")
        for index, value_m in enumerate((0.1, 0.25, 0.5, 1.0)):
            value = value_m * from_m.length
            self.snap.addItem(f"{value:g} {length}", value)
            delta = abs(value - current)
            if delta < best_delta:
                best_delta = delta
                best_index = index
        self.snap.setCurrentIndex(best_index)
        self.snap.blockSignals(False)
        self.canvas.grid = float(self.snap.currentData())

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
        data["element_behavior"] = self.element_type_selector.currentData()
        if self._start_in_3d:
            data["model_name"] = self._model_name
            data["vertical_axis"] = self._vertical_axis
            data["gravity_direction"] = self._gravity_direction
            data["gravity_acceleration"] = self._gravity_acceleration
            data["user_materials"] = [dict(material) for material in self._user_materials]
            data["user_sections"] = [dict(section) for section in self._user_sections]
            data["load_generator_settings"] = self._load_generator_settings()
        return data

    def load_project_dict(self, data: dict[str, object]) -> None:
        # The saved unit system must be adopted BEFORE canvas.load_dict()
        # populates raw values, not after: those values are already
        # expressed in this saved unit system, so calling the ordinary
        # set_unit_system() afterward (which also rescales stored values -
        # see its own docstring) would convert them a second time against a
        # "from" unit that never actually applied to this data.
        self._unit_system = UnitSystem(
            force=str(data.get("unit_force", self._unit_system.force)),
            length=str(data.get("unit_length", self._unit_system.length)),
        )
        self.canvas.load_dict(data)
        if self._start_in_3d:
            self._model_name = str(data.get("model_name", self._model_name))
            self._vertical_axis = str(data.get("vertical_axis", self._vertical_axis))
            self._gravity_direction = str(
                data.get("gravity_direction", self._gravity_direction)
            )
            self._gravity_acceleration = float(
                data.get("gravity_acceleration", self._gravity_acceleration)
            )
            stored_materials = data.get("user_materials", [])
            self._user_materials = (
                [dict(material) for material in stored_materials if isinstance(material, dict)]
                if isinstance(stored_materials, list)
                else []
            )
            stored_sections = data.get("user_sections", [])
            self._user_sections = (
                [dict(section) for section in stored_sections if isinstance(section, dict)]
                if isinstance(stored_sections, list)
                else []
            )
        self._refresh_unit_system_ui(self._unit_system)
        fallback_behavior = (
            "truss" if self.canvas.element_family == "truss" else "general_beam"
        )
        element_behavior = str(data.get("element_behavior", fallback_behavior))
        behavior_index = self.element_type_selector.findData(element_behavior)
        if behavior_index < 0:
            element_behavior = fallback_behavior
            behavior_index = self.element_type_selector.findData(element_behavior)
        self.element_type_selector.blockSignals(True)
        self.element_type_selector.setCurrentIndex(behavior_index)
        self.element_type_selector.blockSignals(False)
        self.canvas.element_family = (
            "frame" if element_behavior == "general_beam" else "truss"
        )
        self.canvas.element_behavior = element_behavior
        self._element_property_selection_changed()
        self.truss_mode_toggle.blockSignals(True)
        self.truss_mode_toggle.setChecked(self.canvas.element_family == "truss")
        self.truss_mode_toggle.blockSignals(False)
        if not self._start_in_3d:
            self.model_type_selector.blockSignals(True)
            self.model_type_selector.setCurrentIndex(
                self.model_type_selector.findData(
                    "truss" if self.canvas.element_family == "truss" else "frame"
                )
            )
            self.model_type_selector.blockSignals(False)
        self.self_weight_toggle.blockSignals(True)
        self.self_weight_toggle.setChecked(self.canvas.include_self_weight)
        self.self_weight_toggle.blockSignals(False)
        self.view_results_button.setEnabled(False)
        if hasattr(self, "task_results_button"):
            self.task_results_button.setEnabled(False)
        self.workspace_stack.setCurrentIndex(0)
        self._sync_property_panel()
        self._refresh_status()
        self._refresh_model_settings_summary()
        self._refresh_work_tree()
        if self._start_in_3d:
            self._restore_load_generator_settings(data.get("load_generator_settings"))

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
        stiffness. Failures still only reach the status bar here, never a
        popup — see ``_solve_completed``. A completed run shows the same
        「해석 완료」 dialog the import workspace already had.

        3D's own Analysis tab picks a method (``_ANALYSIS_METHOD_OPTIONS``)
        that this same button also triggers - Nonlinear Static routes to
        ``_solve_nonlinear_static`` instead of the plain linear solve below;
        every other kind there still can't reach this button at all (see
        ``_on_analysis_method_changed``'s ``can_run`` gate), and a 2D page
        has no ``analysis_method_selector`` to begin with, so this only ever
        branches for a 3D page with Nonlinear Static actually selected.
        """
        if self._solve_thread is not None and self._solve_thread.isRunning():
            return
        if self._analysis_run_thread is not None and self._analysis_run_thread.isRunning():
            return
        if self._start_in_3d and hasattr(self, "analysis_method_selector"):
            _label, kind, _dialog_cls = self._current_analysis_method_option()
            if kind == AnalysisKind.NONLINEAR_STATIC:
                self._solve_nonlinear_static()
                return
            if kind in self._FULL_ANALYSIS_KINDS:
                self._run_full_analysis(kind)
                return
        model = self.canvas.build_model()
        check = check_determinacy(model)
        self.determinacy_status.setText(f"정정성: {check.message}")
        self.solve_button.setEnabled(False)
        self.analysis_progress.show_running("정정성 해석")
        self.results.set_analysis_kind(AnalysisKind.LINEAR_STATIC)
        thread = MaterialFreeSolveThread(self._solver, model)
        thread.completed.connect(lambda result: self._solve_completed(model, check, result))
        thread.finished.connect(self._solve_thread_finished)
        self._solve_thread = thread
        thread.start()

    #: The only keys NonlinearStaticSolveThread's constructor (and, past it,
    #: MaterialFreeStaticsSolver.solve_nonlinear_static) actually accepts.
    #: AnalysisSettingsPanel.build_options() now stages 17 keys for this kind
    #: (algorithm/constraints/numberer/system/... - the same wider set SETUP
    #: exposes) since Phase 1 pointed this tab's 설정... button at that same
    #: panel instead of a dialog with only these 6 fields; this canvas's own
    #: solver has not grown to match yet (that is Phase 2 - see the
    #: engine-side work described where AnalysisSettingsDialog is used), so
    #: everything else staged is silently unused here, not an error.
    _NONLINEAR_STATIC_SOLVER_KEYS = frozenset(
        {"control_node", "control_dof", "num_steps", "tolerance", "max_iterations", "integrator_type"}
    )

    def _solve_nonlinear_static(self) -> None:
        """Nonlinear Static's own 해석하기 path - reads the settings staged
        by the shared ``AnalysisSettingsDialog`` (``_open_analysis_settings_
        dialog``) and runs ``MaterialFreeStaticsSolver.solve_nonlinear_
        static`` (a lumped-plasticity pushover - see that method's own
        docstring for what it does and does not model) instead of the plain
        elastic ``solve()``. Everything past this - the background thread,
        the completion/failure handling, the results view - is exactly
        ``solve()``'s own machinery, reused unchanged via
        ``_solve_completed``/``_solve_thread_finished``.
        """
        options = self._analysis_settings.get(AnalysisKind.NONLINEAR_STATIC.value)
        if not options:
            self.determinacy_status.setText(
                "먼저 '설정...' 버튼으로 비선형 정적(Pushover) 해석 설정을 입력하세요."
            )
            return
        model = self.canvas.build_model()
        if options["control_node"] not in model.nodes:
            self.determinacy_status.setText(
                f"제어 절점 {options['control_node']}가 모델에 없습니다 - 설정에서 실제 "
                "절점 번호를 입력하세요."
            )
            return
        solver_options = {
            key: value for key, value in options.items() if key in self._NONLINEAR_STATIC_SOLVER_KEYS
        }
        check = check_determinacy(model)
        self.determinacy_status.setText(f"정정성: {check.message}")
        self.analysis_run_button.setEnabled(False)
        self.analysis_progress.show_running("비선형 정적(Pushover) 해석")
        self.results.set_analysis_kind(AnalysisKind.NONLINEAR_STATIC)
        thread = NonlinearStaticSolveThread(self._solver, model, **solver_options)
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
        summary = (
            f"절점 {len(result.node_results)}개, 부재 {len(result.element_results)}개 "
            "결과가 준비되었습니다."
        )
        self.analysis_progress.show_completed(summary)
        self.results.set_model(model)
        self.results.show_result(result)
        self.results.set_result_type("reaction")
        self.view_results_button.setEnabled(True)
        if hasattr(self, "task_results_button"):
            self.task_results_button.setEnabled(True)
        self.workspace_stack.setCurrentIndex(1)
        self._notify_analysis_completed(self._completed_analysis_label(), summary)

    @staticmethod
    def _normalize_full_analysis_options(
        kind: AnalysisKind,
        options: dict[str, float | int | str | bool],
    ) -> dict[str, float | int | str | bool]:
        """Resolve time-history ground-motion paths before the worker subprocess
        starts - ``OpenSeesProcessRunner`` sets ``cwd`` to the temp script's
        parent, so relative paths from the settings dialog would otherwise miss
        files stored elsewhere on disk."""
        if kind != AnalysisKind.TIME_HISTORY:
            return options
        directions = options.get("directions")
        if not isinstance(directions, list):
            return options
        normalized_directions: list[dict[str, object]] = []
        for entry in directions:
            if not isinstance(entry, dict):
                continue
            item = dict(entry)
            path_value = item.get("path")
            if path_value:
                item["path"] = str(Path(str(path_value)).expanduser().resolve())
            normalized_directions.append(item)
        return {**options, "directions": normalized_directions}

    def _run_full_analysis(self, kind: AnalysisKind) -> None:
        """Export the 3D canvas to a temp OpenSeesPy script and run it through
        the same ``RunAnalysisService`` pipeline SETUP uses - deliberately no
        popups here (status bar only), matching this page's own ``solve()``
        failure style."""
        if self._analysis_run_thread is not None and self._analysis_run_thread.isRunning():
            return
        if self._run_analysis_service is None:
            self.determinacy_status.setText("해석 실행 서비스가 연결되지 않았습니다.")
            return
        options = self._analysis_settings.get(kind.value)
        if not options:
            self.determinacy_status.setText(
                f"먼저 '설정...' 버튼으로 {self._ANALYSIS_DISPLAY_NAMES[kind]} 해석 설정을 입력하세요."
            )
            return
        try:
            model = self.canvas.build_model()
        except Exception as error:  # noqa: BLE001 - surface any build failure in the status bar.
            self.determinacy_status.setText(f"모델 빌드 실패: {error}")
            return
        try:
            script = export_opensees_script(
                model, include_mass=True, length_unit=self._unit_system.length
            )
        except ValueError as error:
            self.determinacy_status.setText(f"보내기 실패: {error}")
            return
        try:
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                prefix="openframe-canvas-",
                delete=False,
                encoding="utf-8",
            )
            with handle:
                handle.write(script)
                source_path = Path(handle.name)
        except OSError as error:
            self.determinacy_status.setText(f"임시 스크립트 생성 실패: {error}")
            return
        normalized = self._normalize_full_analysis_options(kind, dict(options))
        # Thread the user-node allow-list and ndm so the worker subprocess can
        # project mechanism mode shapes onto the correct node set without
        # estimating tag ranges.  Popped in worker.py before solver dispatch.
        normalized["user_node_tags"] = sorted(model.nodes.keys())
        normalized["ndm"] = model.ndm
        request = AnalysisRequest(
            source_path=source_path,
            kind=kind,
            options=normalized,
        )
        errors = self._run_analysis_service.validate(request)
        if errors:
            try:
                source_path.unlink(missing_ok=True)
            except OSError:
                pass
            self.determinacy_status.setText(errors[0])
            return
        self._analysis_temp_script = source_path
        analysis_name = self._ANALYSIS_DISPLAY_NAMES[kind]
        self.analysis_run_button.setEnabled(False)
        self.results.set_analysis_kind(kind)
        self.analysis_progress.show_running(analysis_name)
        thread = AnalysisRunThread(self._run_analysis_service, request)
        thread.completed.connect(lambda result: self._full_analysis_completed(result, model, kind))
        thread.progress_changed.connect(self.analysis_progress.set_progress)
        thread.finished.connect(self._analysis_run_finished)
        self._analysis_run_thread = thread
        thread.start()

    def _analysis_kind_label(self, kind: AnalysisKind) -> str:
        """Korean selector label for ``kind`` - the English
        ``_ANALYSIS_DISPLAY_NAMES`` stay on the status bar where they already
        live; the completion dialog is UI-facing."""
        for label, option_kind, _dialog_cls in self._ANALYSIS_METHOD_OPTIONS:
            if option_kind == kind:
                return label
        return self._ANALYSIS_DISPLAY_NAMES.get(kind, "해석")

    def _completed_analysis_label(self) -> str:
        """Which method the in-canvas solver just finished.

        2D has no method selector (always the header's 정정성 해석). 3D
        reads the Analysis tab combo so Linear Static and Pushover do not
        both read as the same generic '해석'."""
        if self._start_in_3d and hasattr(self, "analysis_method_selector"):
            _label, kind, _dialog_cls = self._current_analysis_method_option()
            return self._analysis_kind_label(kind)
        return "정정성"

    def _notify_analysis_completed(self, analysis_name: str, summary: str) -> None:
        """Modal 'done' notice for every successful analysis kind.

        The canvas used to only flip to the results tab and update the
        progress banner, so a long modal/buckling/time-history run could
        finish with no blocking signal. Failures stay banner/status-bar
        only - see ``_solve_completed``."""
        QMessageBox.information(
            self,
            "해석 완료",
            f"{analysis_name} 해석이 완료되었습니다.\n\n{summary}\n\n"
            "결과 화면에서 확인할 수 있습니다.",
        )

    def _full_analysis_completed(
        self, result: AnalysisResult, model: object, kind: AnalysisKind
    ) -> None:
        analysis_name = self._ANALYSIS_DISPLAY_NAMES[kind]
        if result.status == AnalysisStatus.COMPLETED:
            if result.mode_shapes:
                summary = f"{len(result.mode_shapes)}개 모드 결과가 준비되었습니다."
            elif result.buckling_modes:
                summary = f"{len(result.buckling_modes)}개 좌굴모드 결과가 준비되었습니다."
            elif result.time_history:
                summary = f"{len(result.time_history)}개 시간이력 스텝 결과가 준비되었습니다."
            else:
                summary = (
                    f"절점 {len(result.node_results)}개, 부재 {len(result.element_results)}개 "
                    "결과가 준비되었습니다."
                )
            self.analysis_progress.show_completed(summary)
            self.determinacy_status.setText(f"{analysis_name} 해석 완료: {summary}")
            self.results.set_model(model)
            self.results.show_result(result)
            self.view_results_button.setEnabled(True)
            if hasattr(self, "task_results_button"):
                self.task_results_button.setEnabled(True)
            self.workspace_stack.setCurrentIndex(1)
            self._notify_analysis_completed(self._analysis_kind_label(kind), summary)
            return
        if result.status == AnalysisStatus.PARTIAL and result.buckling_modes:
            detail = " ".join(result.messages) or "요청한 모드 수보다 적은 유효 모드를 찾았습니다."
            self.analysis_progress.show_failed(detail)
            self.determinacy_status.setText(f"{analysis_name} 부분 결과: {detail}")
            self.results.set_model(model)
            self.results.show_result(result)
            if hasattr(self, "task_results_button"):
                self.task_results_button.setEnabled(True)
            return
        if result.status == AnalysisStatus.CANCELLED:
            self.analysis_progress.show_failed("해석이 취소되었습니다.")
            self.determinacy_status.setText("해석이 취소되었습니다.")
            return
        detail = " ".join(result.messages) or f"{analysis_name} 해석에 실패했습니다."
        self.analysis_progress.show_failed(detail)
        self.determinacy_status.setText(detail)

    def _cancel_full_analysis(self) -> None:
        thread = self._analysis_run_thread
        if thread is None or not thread.isRunning():
            return
        self.analysis_progress.show_cancelling()
        thread.request_cancel()

    def _analysis_run_finished(self) -> None:
        if hasattr(self, "analysis_run_button"):
            self._on_analysis_method_changed()
        if hasattr(self, "solve_button"):
            self.solve_button.setEnabled(True)
        thread = self._analysis_run_thread
        self._analysis_run_thread = None
        if thread is not None:
            thread.deleteLater()
        temp_script = self._analysis_temp_script
        self._analysis_temp_script = None
        if temp_script is not None:
            try:
                temp_script.unlink(missing_ok=True)
            except OSError:
                pass

    def _solve_thread_finished(self) -> None:
        self.solve_button.setEnabled(True)
        if hasattr(self, "analysis_run_button"):
            self._on_analysis_method_changed()
        thread = self._solve_thread
        self._solve_thread = None
        if thread is not None:
            thread.deleteLater()

    def _export_for_full_analysis(self) -> None:
        """Text generation is fast (no OpenSeesPy solve involved) so this runs
        synchronously, unlike ``solve()``'s background thread. Same
        no-popup-for-everyday-failures philosophy: a model that cannot be
        exported yet (still 3D, or missing section properties) gets the same
        status-bar message a doomed solve() would, not a dialog."""
        model = self.canvas.build_model()
        try:
            script = export_opensees_script(
                model, include_mass=True, length_unit=self._unit_system.length
            )
        except ValueError as error:
            self.determinacy_status.setText(f"내보내기 실패: {error}")
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "OpenSeesPy 스크립트로 내보내기", "model.py", "Python 파일 (*.py)"
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix != ".py":
            path = path.with_suffix(".py")
        try:
            path.write_text(script, encoding="utf-8")
        except OSError as error:
            self.determinacy_status.setText(f"내보내기 실패: {error}")
            return
        self.determinacy_status.setText(f"내보내기 완료: {path.name}")
        self.analysis_script_exported.emit(path)

    def _toggle_truss_mode(self, checked: bool) -> None:
        """Only affects members drawn from now on — a truss/frame member is a
        drawing-time choice (pinned both ends vs moment-connected), not a
        property that can be flipped retroactively without redrawing it."""
        self.canvas.element_family = "truss" if checked else "frame"
        if hasattr(self, "element_type_selector"):
            target_behavior = "truss" if checked else "general_beam"
            self.canvas.element_behavior = target_behavior
            behavior_index = self.element_type_selector.findData(target_behavior)
            if behavior_index >= 0:
                self.element_type_selector.blockSignals(True)
                self.element_type_selector.setCurrentIndex(behavior_index)
                self.element_type_selector.blockSignals(False)
                self._element_property_selection_changed()
        if not self._start_in_3d:
            target = "truss" if checked else "frame"
            index = self.model_type_selector.findData(target)
            if index >= 0 and self.model_type_selector.currentIndex() != index:
                self.model_type_selector.blockSignals(True)
                self.model_type_selector.setCurrentIndex(index)
                self.model_type_selector.blockSignals(False)

    def _toggle_self_weight(self, checked: bool) -> None:
        """A solve-time decision, unlike truss mode — it only changes what
        build_model() adds on top of whatever loads are already there, so
        toggling it back and forth freely (no redraw needed) is safe."""
        self.canvas.include_self_weight = checked

    def _set_mode(self, mode: str, description: str) -> None:
        self.canvas.set_mode(mode)
        self.mode_label.setText(description)
        self._sync_picking_mode()

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
        if self._start_in_3d and self._active_element_kwargs is None:
            self.select_tool.setChecked(True)
            self._set_mode(
                "select",
                "Create Element를 시작하려면 Material과 Section을 모두 선택하세요.",
            )
            self.workbench_buttons["element"].setChecked(True)
            self.node_subcategory_row.hide()
            self.element_subcategory_row.show()
            index = self.element_subcategory_combo.findData("element_picker")
            self.element_subcategory_combo.blockSignals(True)
            self.element_subcategory_combo.setCurrentIndex(index)
            self.element_subcategory_combo.blockSignals(False)
            self._active_element_subcategory = "element_picker"
            self._show_category("element_picker", sync_workbench=False)
            self.active_element_status.setText(
                "⚠ 물성·단면이 설정되지 않아 부재를 그릴 수 없습니다. "
                "Material과 Section을 모두 선택하세요."
            )
            self.selection_summary.setText("⚠ Create Element에 필요한 물성·단면이 없습니다.")
            return
        self.draw_tool.setChecked(True)
        if hasattr(self, "workbench_buttons"):
            self.workbench_buttons["element"].setChecked(True)
            self.node_subcategory_row.hide()
            self.element_subcategory_row.show()
            index = self.element_subcategory_combo.findData("element_picker")
            self.element_subcategory_combo.blockSignals(True)
            self.element_subcategory_combo.setCurrentIndex(index)
            self.element_subcategory_combo.blockSignals(False)
            self._active_element_subcategory = "element_picker"
        description = (
            "그리기 · 시작 노드와 끝 노드를 차례로 클릭합니다. "
            "부재가 완성되면 다음 클릭은 새 부재의 시작 노드가 됩니다. "
            "Esc로 그리기를 종료합니다."
            if self.canvas.ndm == 3
            else "그리기 · 연속 클릭으로 노드와 부재를 함께 만듭니다. "
            "아래 입력칸에 길이·각도를 쳐도 됩니다. Esc로 그리기를 종료합니다."
        )
        self._set_mode("draw", description)
        self.draw_entry.setFocus()
        self._sync_property_panel()
        self._refresh_draw_readout()

    def _activate_node_transform_tool(self) -> None:
        self.select_tool.setChecked(True)
        # Translate/rotate/mirror all understand a selected member -
        # picking "부재만" and clicking a member carries both its endpoints
        # along, MIDAS's separate Node/Element move-copy mode - but if the
        # 지점 tool ran right before this one, the filter it narrowed to
        # "노드만" would otherwise still be in effect here, silently
        # swallowing every member click with no visible reason why (the
        # exact "복사가 안 된다" trap _activate_select_tool's own filter
        # reset already exists to prevent). Reset to "전체" on entry, same
        # as every other tool activator below - the filter dropdown is
        # still right there to narrow it back down once inside this tool.
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("all"))
        self._set_mode(
            "select", "이동하거나 복사할 노드 또는 부재를 선택한 뒤 오른쪽 패널에서 적용하세요."
        )
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
        self._set_mode("select", "하중 명령을 선택하고 대상을 지정한 뒤 왼쪽 설정창에서 적용하세요.")
        if self._start_in_3d and hasattr(self, "load_task_bar"):
            self.load_task_bar.show()
        self._sync_property_panel()
        self._load_target_changed()
        self._show_category("load")

    def _selection_changed(self) -> None:
        self._sync_3d_selection_highlight()
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
        self._sync_element_assignment_selection_state()
        self._refresh_create_section_hint()
        self._update_member_info_card(member_tag)
        if member_tag is not None:
            self._refresh_member_section(member_tag)
        elif hasattr(self, "member_behavior_settings_card"):
            self.member_behavior_settings_card.hide()
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
        self._sync_selection_status()

    def _sync_selection_status(self) -> None:
        """Full re-render of the read-only Selection Status inspector (bottom
        splitter pane) from the model itself - called wherever
        ``_sync_property_panel`` already is (selection change, apply, undo/
        redo, project load), never from a bare keystroke. ``pending_edit``
        only matters when a member is selected; the panel ignores it
        otherwise."""
        self.selection_status_panel.refresh(
            self.canvas,
            pending_edit=self.section_material_panel.current_edit_kwargs(),
            unit_system=self._unit_system,
        )
        if hasattr(self, "load_inspector_status_panel"):
            self.load_inspector_status_panel.refresh(
                self.canvas,
                pending_edit=self.section_material_panel.current_edit_kwargs(),
                unit_system=self._unit_system,
            )

    def _selection_status_edited(self) -> None:
        """``SectionMaterialPanel.edited`` fired from a real keystroke -
        re-evaluate only the Applied/Pending Changes badge already on
        screen, never a full ``_sync_selection_status()`` (that would be
        indistinguishable from re-reading the model, which typing alone
        must never trigger)."""
        self.selection_status_panel.update_pending_status(
            self.section_material_panel.current_edit_kwargs()
        )

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
        self.member_local_axis_row.setVisible(self.canvas.ndm == 3)
        self.section_material_panel.set_shear_modulus_visible(self.canvas.ndm == 3)
        self.member_local_axis_angle.blockSignals(True)
        self.member_local_axis_angle.setValue(element.local_axis_angle)
        self.member_local_axis_angle.blockSignals(False)
        if hasattr(self, "member_offset_row"):
            self.member_offset_row.setVisible(self.canvas.ndm == 3)
            offset_i_length = math.sqrt(sum(component**2 for component in element.offset_i))
            offset_j_length = math.sqrt(sum(component**2 for component in element.offset_j))
            self.member_offset_i.blockSignals(True)
            self.member_offset_i.setValue(offset_i_length)
            self.member_offset_i.blockSignals(False)
            self.member_offset_j.blockSignals(True)
            self.member_offset_j.setValue(offset_j_length)
            self.member_offset_j.blockSignals(False)
        self.section_material_panel.load_from_element(element)
        self._refresh_member_behavior_card(element)

    def _refresh_member_behavior_card(self, element) -> None:
        """Properties-tab counterpart of the Create Element 설정창.

        Without this, a cable already on the canvas had nowhere to edit
        prestress after the fact - the drawing pen only affects members
        drawn next.
        """
        if not hasattr(self, "member_behavior_settings_card"):
            return
        behavior = element.properties.get("behavior", "truss")
        directional = behavior in self._DIRECTIONAL_BEHAVIOR_HINTS
        self.member_behavior_settings_card.setVisible(directional)
        if not directional:
            return
        self.member_behavior_hint.setText(self._DIRECTIONAL_BEHAVIOR_HINTS[behavior])
        show_gap = behavior in ("tension_only", "cable")
        show_prestress = behavior == "cable"
        self.member_gap_label.setVisible(show_gap)
        self.member_gap_field.setVisible(show_gap)
        self.member_prestress_label.setVisible(show_prestress)
        self.member_prestress_field.setVisible(show_prestress)
        raw_gap = element.properties.get("gap", 0.0)
        try:
            gap = float(raw_gap)
        except (TypeError, ValueError):
            gap = 0.0
        self.member_gap_field.blockSignals(True)
        self.member_gap_field.setValue(gap)
        self.member_gap_field.blockSignals(False)
        self.member_prestress_field.blockSignals(True)
        self.member_prestress_field.setValue(element.prestress)
        self.member_prestress_field.blockSignals(False)
        self._refresh_directional_unit_labels()

    def _apply_member_behavior_settings(self) -> None:
        if not self.canvas.selected_elements:
            self.selection_summary.setText(
                "⚠ 선택된 부재가 없어 거동 설정을 적용하지 못했습니다."
            )
            return
        self.canvas.apply_behavior_settings_to_selection(
            gap=float(self.member_gap_field.value()),
            prestress=float(self.member_prestress_field.value()),
        )
        count = len(self.canvas.selected_elements)
        self.selection_summary.setText(
            f"✓ 부재 {count}개에 거동 설정(갭·프리스트레스)을 적용했습니다."
        )
        self._sync_selection_status()

    def _properties_selector_changed(self, _index: int = 0) -> None:
        """Show only the MATERIAL/SECTION/SECTION PROPERTIES card the
        "PROPERTIES" dropdown currently names, hiding the other two - see
        _build_member_bar_content for why this replaced each card's own
        clickable header in the 3D Properties tab."""
        key = self.properties_selector.currentData()
        panel = self.section_material_panel
        for group, group_key in (
            (panel.material_group, "material"),
            (panel.section_group, "section"),
            (panel.properties_group, "section_properties"),
        ):
            active = key == group_key
            group.set_expanded(active)
            # Hiding just the body (set_expanded) leaves the two inactive
            # cards' own bordered/padded card frame empty but still visible -
            # a thin blank strip for each. Hide the whole card instead, so
            # only the one actually-selected card's frame ever shows.
            group.setVisible(active)

    @staticmethod
    def _section_kwargs_from_properties(properties: dict[str, float | str]) -> dict[str, object]:
        """Reconstruct ``apply_full_section_to_selection``'s full kwarg set
        from what a member's ``element.properties`` already carries, so a
        물성-only or 섹션-only drag-and-drop (``_apply_property_drop``) can
        overlay just the half that was dropped onto the untouched other half
        instead of going through ``apply_full_section_to_selection``'s own
        full-replace behaviour with zeros for whatever the drop didn't
        supply. Dimensions only round-trip for Rectangle - every other shape
        already drops them on write (see that method's own docstring)."""

        def number(key: str, default: float = 0.0) -> float:
            try:
                return float(properties.get(key, default))
            except (TypeError, ValueError):
                return default

        shape = str(properties.get("section_shape", "Rectangle"))
        return {
            "shape": shape,
            "source": str(properties.get("section_source", "custom")),
            "dimensions": (
                {"b": number("width"), "h": number("height")} if shape == "Rectangle" else {}
            ),
            "area": number("A"),
            "iy": number("Iy", number("I")),
            "iz": number("Iz"),
            "j": number("J"),
            "elastic": number("E"),
            "shear_modulus": properties.get("G"),
            "density": number("density"),
            "section_id": properties.get("section_id"),
            "material_id": properties.get("material_id"),
            "material_category": properties.get("material_category"),
            "material_grade": properties.get("material_grade"),
            "fy": number("Fy"),
            "strain_hardening_ratio": number("StrainHardeningRatio", 0.02),
            "zy": properties.get("Zy"),
            "zz": properties.get("Zz"),
        }

    def _apply_property_drop(self, kind: str, definition_id: str, element_tag: int) -> None:
        """A 물성/섹션 Work Tree row was dropped onto ``element_tag`` in the
        2D canvas (``canvas_input_events.py``'s dropEvent). Only the dropped
        half is overlaid onto the member's existing properties - dropping a
        물성 keeps its current 단면(A/Iy/Iz/J/shape), dropping a 섹션 keeps its
        current 물성(E/density/Fy) - see ``_section_kwargs_from_properties``.
        """
        element = self.canvas.elements.get(element_tag)
        if element is None:
            return
        kwargs = self._section_kwargs_from_properties(element.properties)
        if kind == "material":
            material = next(
                (item for item in self._user_materials if item.get("id") == definition_id), None
            )
            if material is None:
                return
            kwargs.update(
                elastic=float(material.get("elastic", kwargs["elastic"]) or 0.0),
                density=float(material.get("density", kwargs["density"]) or 0.0),
                fy=float(material.get("fy", kwargs["fy"]) or 0.0),
                # None, not the member's old G - a changed E must re-derive
                # the shear modulus, not keep the previous material's.
                shear_modulus=None,
                material_category=material.get("category"),
                material_grade=material.get("grade"),
            )
            label = str(material.get("name", "물성"))
        elif kind == "section":
            section = next(
                (item for item in self._user_sections if item.get("id") == definition_id), None
            )
            if section is None:
                return
            kwargs.update(
                shape=section.get("shape", kwargs["shape"]),
                source=section.get("source", kwargs["source"]),
                dimensions=dict(section.get("dimensions") or {}),
                area=float(section.get("area", kwargs["area"]) or 0.0),
                iy=float(section.get("iy", kwargs["iy"]) or 0.0),
                iz=float(section.get("iz", kwargs["iz"]) or 0.0),
                j=float(section.get("j", kwargs["j"]) or 0.0),
                section_id=section.get("database_id"),
            )
            label = str(section.get("name", "섹션"))
        else:
            return
        self._select_entity_from_tree("element", element_tag)
        self.canvas.apply_full_section_to_selection(**kwargs)
        self.selection_summary.setText(f"✓ 부재 {element_tag}에 '{label}'을(를) 드롭으로 적용했습니다.")
        self._sync_selection_status()

    def _apply_member_section(self) -> None:
        """Apply the Properties editor values to selected existing members."""
        properties = self.section_material_panel.current_application_kwargs()
        if not self.canvas.selected_elements:
            self.selection_summary.setText(
                "⚠ 선택된 부재가 없어 단면·재료를 적용하지 못했습니다 — 적용할 부재를 클릭하세요."
            )
            return
        count = len(self.canvas.selected_elements)
        self.canvas.apply_full_section_to_selection(**properties)
        self.selection_summary.setText(
            f"✓ 부재 {count}개에 단면·재료(E/A/I)와 단위중량을 적용했습니다."
        )
        self._sync_selection_status()

    def _activate_saved_property_set(self, material_name: str, section_name: str) -> None:
        """Use a newly saved 2D pair automatically for members drawn next."""
        material = next(
            (item for item in self._user_materials if item.get("name") == material_name),
            None,
        )
        section = next(
            (item for item in self._user_sections if item.get("name") == section_name),
            None,
        )
        if material is None or section is None:
            return
        material_index = self.element_material_selector.findData(material.get("id"))
        section_index = self.element_section_selector.findData(section.get("id"))
        if material_index >= 0:
            self.element_material_selector.setCurrentIndex(material_index)
        if section_index >= 0:
            self.element_section_selector.setCurrentIndex(section_index)

    def _apply_member_end_release(self, end: str, released: bool) -> None:
        member_tag = self._selected_member_tag()
        if member_tag is not None:
            self.canvas.set_member_end_release(member_tag, end, released)

    def _rotate_member_local_axis_angle(self, delta: float) -> None:
        """Nudge 로컬축 회전각 by ``delta`` degrees (wrapping into [0, 360))
        and apply immediately - mirrors ``_rotate_support_angle``, since a
        button click never fires ``editingFinished`` on its own."""
        self.member_local_axis_angle.setValue(
            (self.member_local_axis_angle.value() + delta) % 360.0
        )
        self._apply_member_local_axis_angle()

    def _apply_member_local_axis_angle(self) -> None:
        if not self.canvas.selected_elements:
            return
        self.canvas.apply_local_axis_angle_to_selection(self.member_local_axis_angle.value())
        self._sync_selection_status()

    def _toggle_local_axis_gizmo(self, visible: bool) -> None:
        # Looked up lazily (not connected to ``self.preview_3d`` directly) -
        # ``_build_member_bar_content`` runs before ``self.preview_3d`` is
        # constructed (``_build_canvas_panel`` builds the category bar before
        # the 3D preview panel), so an eager reference at connect-time would
        # raise AttributeError before the page ever finishes building.
        preview_3d = getattr(self, "preview_3d", None)
        if preview_3d is not None:
            preview_3d.set_local_axes_visible(visible)

    def _insert_member_station_node(self) -> None:
        member_tag = self._selected_member_tag()
        if member_tag is not None:
            self.canvas.add_member_station_node(member_tag, self.member_station.value())

    def _subdivide_member(self) -> None:
        member_tag = self._selected_member_tag()
        if member_tag is not None:
            self.canvas.subdivide_member(member_tag, self.member_segments.value())

    def _commit_draw_entry(self) -> None:
        if self._start_in_3d and self._active_element_kwargs is None:
            self._activate_draw_tool()
            return
        before = set(self.canvas.elements)
        if self.canvas.commit_entry(self.draw_entry.text()):
            self._apply_active_element_to_new_members(set(self.canvas.elements) - before)
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
        tooltip) since this now lives in the left-hand editor panel — a
        form just grows taller as fields are added instead of running out
        of horizontal room.

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
                # deleteLater alone leaves the detached QFormLayout labels
                # paintable until the event loop processes DeferredDelete.
                # During a 2D -> 3D switch that briefly draws old Fx/Fy/Mz
                # labels over the new six-component form. Hide immediately,
                # then dispose of them normally.
                widget.hide()
                widget.deleteLater()
        self.load_fields.clear()
        target = self._current_load_target()
        trapezoid = target == "element_trapezoid"
        is_node = target == "node"
        self.load_coordinate_row.setVisible(not is_node and self.canvas.ndm == 2)
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
                    unit = self._unit_system.force_per_length
                self.load_fields[component] = field
                global_member_load = (
                    not is_node
                    and self.canvas.ndm == 2
                    and self.load_coordinate_system.currentData() == "global"
                )
                if global_member_load:
                    axis = "X" if component.startswith("qx") else "Y"
                    end = ", j단" if component.endswith("_j") else ""
                    full_label = f"q{axis} (전역 {axis}{end})"
                else:
                    full_label = self._COMPONENT_LABELS[component]
                short_label = full_label.split(" ", 1)[0]
                if trapezoid and component in ("qx", "qy"):
                    short_label += "(i)"
                elif component.endswith("_j"):
                    short_label += "(j)"
                tooltip = f"{full_label} ({unit})"
                if global_member_load:
                    tooltip += " — 각 선택 부재의 로컬 qx/qy로 개별 변환"
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
        if hasattr(self, "load_diagram_label"):
            self.load_diagram_label.setPixmap(_render_load_diagram("node" if is_node else "element"))
        # Re-apply Delete's "grey out the values" state to the fields this
        # pass just rebuilt from scratch - a no-op when Options does not
        # exist (2D) or is not on Delete.
        self._on_load_apply_mode_changed()

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
        if not hasattr(self, "load_fields") or not self.load_fields or self._current_load_target() != "node":
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
        mode = self._current_load_apply_mode()
        if self._current_load_target() == "node":
            if not self.canvas.selected_nodes:
                self.selection_summary.setText(
                    "⚠ 선택된 노드가 없어 하중을 적용하지 못했습니다 — 하중을 받을 노드를 "
                    "클릭하세요 (부재를 함께 선택하려면 Ctrl+클릭)."
                )
                return
            self.canvas.apply_nodal_load_to_selection(self._node_load_values(), mode=mode)
            self._record_quick_load_entry()
        else:
            if not self.canvas.selected_elements:
                self.selection_summary.setText(
                    "⚠ 선택된 부재가 없어 하중을 적용하지 못했습니다 — 하중을 받을 부재를 클릭하세요."
                )
                return
            values = (self.load_fields["qx"].value(), self.load_fields["qy"].value())
            if "qx_j" in self.load_fields:
                values += (self.load_fields["qx_j"].value(), self.load_fields["qy_j"].value())
            coordinate_system = (
                str(self.load_coordinate_system.currentData())
                if self.canvas.ndm == 2
                else "local"
            )
            self.canvas.apply_uniform_load_to_selection(
                values, coordinate_system=coordinate_system, mode=mode
            )
            self._record_quick_load_entry()
        # A load actually landed - replace any stale ⚠ warning (e.g. from an
        # earlier failed attempt on this same selection) with the normal
        # selection summary, so success doesn't still look like an error.
        self._sync_property_panel()

    def _record_quick_load_entry(self) -> None:
        """Mirror solver-supported commands into the named Load Case store.

        The command picker should not force users to choose between an
        analysis-only load and a case-managed load. Nodal and the two member
        distribution commands therefore commit to both existing stores from
        the same Apply click. More advanced commands already use
        ``_apply_load3d`` directly.
        """
        if not self._start_in_3d or self.canvas.active_load_case_id is None:
            return
        command = str(self.load_command_combo.currentData())
        case_id = self.canvas.active_load_case_id
        if command == "nodal":
            values = self._node_load_values()
            padded = (*values, *(0.0 for _ in range(max(0, 6 - len(values)))))
            payload = NodalLoadEntry(
                fx=padded[0],
                fy=padded[1],
                fz=padded[2],
                mx=padded[3],
                my=padded[4],
                mz=padded[5],
            )
            targets = tuple(sorted(self.canvas.selected_nodes))
            if self._current_load_apply_mode() in {"replace", "delete"}:
                self._remove_matching_load_entries(case_id, "nodal", targets)
            if self._current_load_apply_mode() != "delete":
                self.canvas.add_load_entry(case_id, "nodal", targets, payload)
            return
        if command not in {"member_uniform", "member_linear"}:
            return
        end_suffix = command == "member_linear"
        targets = tuple(sorted(self.canvas.selected_elements))
        if self._current_load_apply_mode() in {"replace", "delete"}:
            self._remove_matching_load_entries(case_id, command, targets)
        if self._current_load_apply_mode() == "delete":
            return
        for axis in ("x", "y"):
            start = self.load_fields[f"q{axis}"].value()
            end = self.load_fields[f"q{axis}_j"].value() if end_suffix else start
            if start == 0.0 and end == 0.0:
                continue
            self.canvas.add_load_entry(
                case_id,
                command,
                targets,
                MemberDistributedLoadEntry(
                    coordinate_system="local",
                    direction=axis,
                    start_value=start,
                    end_value=end,
                ),
            )

    @staticmethod
    def _parse_xy_text(text: str) -> tuple[float, float] | None:
        """Accepts midas-style combined coordinate entry — "0, 0", "0 0",
        or "(0, 0)" — instead of forcing X and Y into separate fields."""
        cleaned = text.strip().strip("()[]").strip()
        parts = [part for part in cleaned.replace(",", " ").split() if part]
        if len(parts) != 2:
            return None
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            return None

    @staticmethod
    def _parse_xyz_text(text: str) -> tuple[float, float, float] | None:
        """Accept ``0 0 10``, ``0, 0, 10`` and bracketed equivalents."""
        cleaned = text.strip().strip("()[]").strip()
        parts = [part for part in cleaned.replace(",", " ").split() if part]
        if len(parts) != 3:
            return None
        try:
            return float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            return None

    def _add_nodes_from_coordinates(self) -> None:
        parsed = (
            self._parse_xyz_text(self.node_xy.text())
            if self._start_in_3d
            else self._parse_xy_text(self.node_xy.text())
        )
        if parsed is None:
            self.create_section_hint.setText(
                '좌표 형식을 읽을 수 없습니다 — "0, 0, 10"처럼 X, Y, Z를 입력하세요.'
                if self._start_in_3d
                else '좌표 형식을 읽을 수 없습니다 — "0, 0"처럼 X와 Y를 입력하세요.'
            )
            return
        base_x, base_y, base_z = 0.0, 0.0, 0.0
        if self.node_relative.isChecked() and len(self.canvas.selected_nodes) == 1:
            reference = self.canvas.nodes[next(iter(self.canvas.selected_nodes))]
            base_x, base_y = reference.x, reference.y
            if self._start_in_3d:
                base_z = reference.z
        x = base_x + parsed[0]
        y = base_y + parsed[1]
        z = base_z + parsed[2] if self._start_in_3d else 0.0
        dz = self.node_dz.value() if self._start_in_3d else 0.0
        self.canvas.begin_history_group()
        try:
            for index in range(self.node_repeat.value()):
                if self._start_in_3d:
                    # True X/Y/Z, bypassing the active work plane entirely -
                    # a typed coordinate is unambiguous, unlike a canvas
                    # click, so it does not need a plane to resolve it.
                    self.canvas._add_node_at(
                        (
                            x + self.node_dx.value() * index,
                            y + self.node_dy.value() * index,
                            z + dz * index,
                        )
                    )
                else:
                    self.canvas.add_node(
                        x + self.node_dx.value() * index,
                        y + self.node_dy.value() * index,
                    )
        finally:
            self.canvas.end_history_group()
        self._refresh_create_section_hint()

    def _sync_transform_form(self) -> None:
        """dX/dY relabel to 중심 X/중심 Y for 회전 복사 — same two fields, since
        a rotation's pivot point plays the same "where do I measure from" role
        an offset's dx/dy does, so this reuses them instead of adding a
        separate pair of fields only one operation would ever use. 회전각 is
        the one genuinely new field, shown only for that operation."""
        operation = self.node_transform_operation.currentData()
        is_rotate = operation == "rotate"
        is_copy = operation in {"copy", "rotate"}
        self.node_transform_dx_label.setText("중심 X" if is_rotate else "dX")
        self.node_transform_dy_label.setText("중심 Y" if is_rotate else "dY")
        self.node_transform_form.setRowVisible(self.node_transform_angle, is_rotate)
        self.node_transform_form.setRowVisible(self.node_transform_repeat, is_copy)
        self.copy_node_attributes.setVisible(is_copy)
        self.copy_element_loads.setVisible(is_copy)

    def _apply_node_transform(self) -> None:
        operation = self.node_transform_operation.currentData()
        if operation == "rotate":
            self.canvas.rotate_copy_selection(
                self.node_transform_dx.value(),
                self.node_transform_dy.value(),
                self.node_transform_angle.value(),
                self.node_transform_repeat.value(),
                copy_node_attributes=self.copy_node_attributes.isChecked(),
                copy_element_loads=self.copy_element_loads.isChecked(),
            )
            return
        self.canvas.transform_selected_nodes(
            operation,
            self.node_transform_dx.value(),
            self.node_transform_dy.value(),
            self.node_transform_repeat.value(),
            copy_node_attributes=self.copy_node_attributes.isChecked(),
            copy_element_loads=self.copy_element_loads.isChecked(),
        )

    def _apply_mirror(self) -> None:
        self.canvas.mirror_selection(
            self.mirror_axis.currentData(),
            self.mirror_value.value(),
            copy_node_attributes=self.copy_node_attributes.isChecked(),
            copy_element_loads=self.copy_element_loads.isChecked(),
        )

    def _refresh_status(self) -> None:
        """Footer counts and the live determinacy label.

        Uses ``authoring_model()`` (drawn members) rather than ``build_model()``
        (analysis mesh). The label is informational; ``solve()`` still runs
        ``check_determinacy`` on the analysis model before the solver starts.
        """
        model = self.canvas.authoring_model()
        load_count = (
            len(model.nodal_loads)
            + len(model.element_loads)
            + sum(1 for entry in self.canvas.load_entries.values() if not entry.hidden)
        )
        hinge_count = len(self.canvas.hinge_nodes)
        node_text = (
            f"노드 {len(model.nodes)} (절점 {hinge_count})" if hinge_count else f"노드 {len(model.nodes)}"
        )
        self.model_status.setText(
            f"{node_text}  |  부재 {len(model.elements)}  |  "
            f"지점 {len(model.boundaries)}  |  하중 {load_count}"
        )
        self.result_model_status.setText(
            f"{len(model.nodes)} NODES  |  {len(model.elements)} MEMBERS  |  "
            f"{len(model.boundaries)} SUPPORTS  |  {load_count} LOADS"
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
