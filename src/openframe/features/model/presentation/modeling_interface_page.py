"""Free-form authoring surface for 2D structural-mechanics models.

The layout keeps the canvas dominant: a narrow tool rail on the left, a coordinate
entry strip under the canvas, and a property panel on the right that follows the
selection.  Only selecting and drawing are tools; everything else — supports,
hinges, loads — is a property of whatever is selected, so adding a new kind of
object never adds another button to learn.
"""

import json
from pathlib import Path
from typing import Callable, ClassVar

from PySide6.QtCore import QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, FORCE_UNITS, LENGTH_UNITS, UnitSystem
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy
from openframe.features.model.drawing import PlaneKind
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
from openframe.features.results.presentation.results_workspace import ResultsWorkspace
from openframe.features.viewport.presentation.quick3d_viewport import Quick3DViewport


class SafeDoubleSpinBox(QDoubleSpinBox):
    """Prevent a scrolling gesture from silently changing an engineering value,
    and let the user type as many decimal places as they need. ``decimals()``
    is set generously high (see ``_number``) so Qt's input validator never
    blocks a keystroke; ``textFromValue`` then trims the trailing zeros that
    a high fixed ``decimals()`` would otherwise pad every displayed value
    with, so "5" still reads as "5", not "5.0000000000"."""

    def wheelEvent(self, event) -> None:
        event.ignore()

    def textFromValue(self, value: float) -> str:
        text = f"{value:.{self.decimals()}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"


class SafeSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


#: (button label, tooltip, glyph key, restraint preset). Restraint presets are always
#: the 2D (Ux, Uy, Rz) triple, matching the combo box they replaced — a 3D selection
#: never matches one of these by length and always falls through to "커스텀", exactly
#: as before.
_SUPPORT_OPTIONS: tuple[tuple[str, str, str, tuple[bool, bool, bool] | None], ...] = (
    ("자유", "자유 (지점 없음)", "free", (False, False, False)),
    ("핀", "핀 지점 (회전 자유)", "pin", (True, True, False)),
    ("수직롤러", "수직 롤러 — 수평(X) 반력만, 수직으로 구름", "roller_v", (True, False, False)),
    ("수평롤러", "수평 롤러 — 수직(Y) 반력만, 수평으로 구름", "roller_h", (False, True, False)),
    ("고정", "고정 지점", "fixed", (True, True, True)),
    ("커스텀", "커스텀 (자유도 직접 지정)", "custom", None),
)


def _paint_support_glyph(painter: QPainter, key: str, color: str) -> None:
    """Draw one support symbol on a 32x32 logical canvas.

    Deliberately mirrors the shapes ``SupportItem`` already draws on the canvas
    (features/viewport/items/support_item.py) so a button's icon and the glyph it
    places on the model are visually the same symbol, just simplified for icon size.
    """
    if key == "free":
        painter.drawEllipse(QRectF(13.0, 13.0, 6.0, 6.0))
        return
    if key == "fixed":
        painter.drawLine(16, 4, 16, 14)
        ground_pen = QPen(QColor(color), 2.4)
        ground_pen.setCosmetic(True)
        painter.setPen(ground_pen)
        painter.drawLine(6, 14, 26, 14)
        painter.setPen(QPen(QColor(color), 1.6))
        for x in range(6, 27, 5):
            painter.drawLine(x, 15, x - 4, 21)
        return
    if key == "pin":
        triangle = QPainterPath()
        triangle.moveTo(16, 4)
        triangle.lineTo(7, 18)
        triangle.lineTo(25, 18)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.drawLine(5, 19, 27, 19)
        for x in range(5, 28, 5):
            painter.drawLine(x, 20, x - 3, 25)
        return
    if key == "roller_h":
        # Restrains Uy only -> rests on the ground, free to roll horizontally.
        triangle = QPainterPath()
        triangle.moveTo(16, 4)
        triangle.lineTo(7, 16)
        triangle.lineTo(25, 16)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.drawEllipse(QRectF(8.0, 17.0, 6.0, 6.0))
        painter.drawEllipse(QRectF(18.0, 17.0, 6.0, 6.0))
        painter.drawLine(5, 25, 27, 25)
        return
    if key == "roller_v":
        # Restrains Ux only -> rests against a wall, free to roll vertically.
        triangle = QPainterPath()
        triangle.moveTo(20, 16)
        triangle.lineTo(8, 7)
        triangle.lineTo(8, 25)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.drawEllipse(QRectF(21.0, 8.0, 6.0, 6.0))
        painter.drawEllipse(QRectF(21.0, 18.0, 6.0, 6.0))
        painter.drawLine(29, 5, 29, 27)
        return
    # custom
    painter.drawLine(16, 4, 16, 10)
    painter.drawRect(QRectF(9.0, 10.0, 14.0, 12.0))
    painter.drawLine(7, 24, 25, 24)


def _paint_node_kind_glyph(painter: QPainter, hinge: bool, color: str) -> None:
    """강결(rigid joint) vs 활절점(hinge) — a crossed solid dot versus an open
    circle with the connecting lines stopping short of it, the standard textbook
    distinction between a moment-continuous and a moment-released joint."""
    if hinge:
        painter.drawLine(4, 16, 12, 16)
        painter.drawLine(20, 16, 28, 16)
        painter.drawEllipse(QRectF(11.0, 11.0, 10.0, 10.0))
        return
    painter.drawLine(16, 4, 16, 28)
    painter.drawLine(4, 16, 28, 16)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(12.5, 12.5, 7.0, 7.0))


#: (button label, tooltip, target key, glyph key) for the 하중 대상 icon row.
_LOAD_TARGET_OPTIONS: tuple[tuple[str, str, str, str], ...] = (
    ("집중하중", "노드에 힘·모멘트를 직접 가하는 절점 하중", "node", "point"),
    ("등분포하중", "부재 길이를 따라 균일하게 분포된 하중", "element", "uniform"),
    (
        "사다리꼴하중",
        "부재 양 끝(i, j)에서 크기가 다른 선형변화 분포하중 — 한쪽을 0으로 두면 삼각형 하중이 됩니다.",
        "element_trapezoid",
        "trapezoid",
    ),
)


def _paint_load_glyph(painter: QPainter, key: str, color: str) -> None:
    """집중하중(nodal point load) vs 등분포하중(uniform element load) vs
    사다리꼴하중(linearly-varying element load) — one arrow landing on a point,
    several evenly spaced same-length arrows hanging from a line, or arrows
    that grow from short to tall, the standard textbook symbols for each."""
    if key == "point":
        painter.drawLine(16, 3, 16, 19)
        head = QPainterPath()
        head.moveTo(16, 27)
        head.lineTo(11, 18)
        head.lineTo(21, 18)
        head.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(head)
        return
    if key == "trapezoid":
        # a line with three arrows of increasing length hanging from it
        painter.drawLine(4, 4, 28, 10)
        for x, top in ((7, 8), (16, 6), (25, 4)):
            painter.drawLine(x, top, x, 25)
            head = QPainterPath()
            head.moveTo(x, 29)
            head.lineTo(x - 3, 22)
            head.lineTo(x + 3, 22)
            head.closeSubpath()
            painter.setBrush(QColor(color))
            painter.drawPath(head)
        return
    # uniform: a line with three evenly spaced arrows hanging from it
    painter.drawLine(4, 6, 28, 6)
    for x in (9, 16, 23):
        painter.drawLine(x, 6, x, 19)
        head = QPainterPath()
        head.moveTo(x, 27)
        head.lineTo(x - 3, 19)
        head.lineTo(x + 3, 19)
        head.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(head)


def _render_glyph_icon(paint: Callable[[QPainter, str], None], size: int = 32) -> QIcon:
    """Build a QIcon with matched Off/On pixmaps (dark-slate / white) so a
    checkable QToolButton's icon reads correctly both unchecked (light
    background) and checked (filled accent-blue background) without any QSS
    icon-swapping tricks."""
    icon = QIcon()
    for color, state in (("#35485f", QIcon.State.Off), ("#ffffff", QIcon.State.On)):
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2.0)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color), 1.6)
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        paint(painter, color)
        painter.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon


class _RectangleSectionPreview(QWidget):
    """A tiny live-rendered rectangle, scaled to the member's own width:height
    ratio, so typing a section's dimensions gives an immediate visual instead
    of trusting two numbers to look "right" in your head."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.setToolTip("입력한 폭·높이 비율의 단면 미리보기")
        self._width = 0.3
        self._height = 0.5

    def set_dimensions(self, width: float, height: float) -> None:
        self._width = max(width, 0.001)
        self._height = max(height, 0.001)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        margin = 8.0
        box = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
        scale = min(box.width() / self._width, box.height() / self._height)
        rect_width = self._width * scale
        rect_height = self._height * scale
        rect = QRectF(
            box.center().x() - rect_width / 2.0,
            box.center().y() - rect_height / 2.0,
            rect_width,
            rect_height,
        )
        pen = QPen(QColor("#174ea6"), 1.6)
        painter.setPen(pen)
        painter.setBrush(QColor(23, 78, 166, 45))
        painter.drawRect(rect)


class _SlideOutGroup:
    """Accordion controller: expanding one member collapses every other one in
    the group. 지점/노드 유형/부재/하중 all live in the same canvas-top bar, and
    leaving more than one open at a time just recreates the "다 나열되어
    있다" clutter this bar exists to avoid."""

    def __init__(self) -> None:
        self._sections: list[_SlideOutSection] = []

    def add(self, section: "_SlideOutSection") -> None:
        self._sections.append(section)

    def notify_expanded(self, expanded: "_SlideOutSection") -> None:
        for section in self._sections:
            if section is not expanded:
                section.set_expanded(False)


class _SlideOutSection(QWidget):
    """A "title ▸" toggle that reveals ``content`` sliding open sideways.

    Used to keep the canvas-top bar (지점/노드 유형/부재/하중) compact by default
    instead of always showing every icon and field: most of the time you are
    drawing, not setting a support or a load, so those controls only need to
    be one click away, not permanently taking up width.
    """

    def __init__(
        self,
        title: str,
        content: QWidget,
        group: "_SlideOutGroup | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._content = content
        self._expanded_width: int | None = None
        self._group = group
        if group is not None:
            group.add(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("slideOutToggle")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._update_toggle_text()
        self.toggle_button.clicked.connect(self._toggle)
        layout.addWidget(self.toggle_button)

        content.setParent(self)
        content.setMaximumWidth(0)
        content.setMinimumWidth(0)
        layout.addWidget(content)

        self._animation = QPropertyAnimation(content, b"maximumWidth", self)
        self._animation.setDuration(160)

    def _update_toggle_text(self) -> None:
        arrow = "▾" if self.toggle_button.isChecked() else "▸"
        self.toggle_button.setText(f"{self._title} {arrow}")

    def _toggle(self, checked: bool) -> None:
        self.set_expanded(checked)

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded_width is None:
            # sizeHint() is only meaningful once the content has real children
            # laid out, which is true by the time this first runs (built in
            # the caller before wrapping it here).
            self._expanded_width = max(self._content.sizeHint().width(), 1)
        self.toggle_button.setChecked(expanded)
        self._update_toggle_text()
        self._animation.stop()
        self._animation.setStartValue(self._content.maximumWidth())
        self._animation.setEndValue(self._expanded_width if expanded else 0)
        self._animation.start()
        if expanded and self._group is not None:
            self._group.notify_expanded(self)


class _FloatingPropertiesWindow(QDialog):
    """A small non-modal window for a property editor whose content is too
    tall to sit inline in the canvas-top bar without stretching the whole
    bar's height and shrinking the canvas — 부재 속성 (section/material + pin
    releases + node insertion) is the one case of this so far, since it stacks
    several rows vertically while every other top-bar section (지점/노드 유형/
    하중) lays its content out as a single horizontal row. Non-modal so the
    canvas stays clickable to select a different member while the window is
    open — the fields inside it already resync to whatever is selected on
    every ``_sync_property_panel`` call, window open or not."""

    def __init__(
        self,
        title: str,
        content: QWidget,
        on_close: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle(title)
        self._on_close = on_close
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(content)
        self.setFixedWidth(320)

    def closeEvent(self, event) -> None:
        self._on_close()
        super().closeEvent(event)


class ModelingInterfacePage(QFrame):
    """One-screen workflow: draw, inspect, assign conditions, and review results."""

    def __init__(self, parent: QWidget | None = None, *, start_in_3d: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("modelingInterfacePage")
        self._start_in_3d = start_in_3d
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._solver = MaterialFreeStaticsSolver()
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
        layout.addWidget(self._build_node_property_bar())
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
        """This panel is deliberately minimal and fixed: 좌표로 노드 추가,
        이동·복사·배열, and 노드 삽입·등분할, all always visible, never
        collapsed. Every other selection-dependent editor (지점, 노드 유형,
        부재의 단면·재료·핀 해제, 하중) lives in the canvas-top bar's
        accordion instead (``_build_node_property_bar``). 노드 삽입·등분할
        moved out of that 부재 accordion and in here because it is a node/
        geometry operation in the same family as 이동·복사·배열, not a
        per-member property like section or material.
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

        root.addWidget(self._build_create_section())
        root.addWidget(self._build_transform_section())
        root.addWidget(self._build_member_edit_section())
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

    def _build_node_property_bar(self) -> QFrame:
        """지점/하중 — 캔버스 바로 위, 오른쪽 패널이 아니라 여기 고정된 가로
        막대에 둔다. 선택 여부와 무관하게 항상 사용 가능하고(오른쪽 패널의
        다른 always-on 위젯들과 동일한 이유 — no-op이 안전하고, 학생이 뭘 먼저
        선택할 필요 없이 바로 컨트롤을 찾을 수 있어야 함), 캔버스 폭을 그대로
        쓸 수 있다. 다만 그리는 동안에는 계속 필요한 게 아니라서, 기본은
        "제목 ▸"만 보이고 눌러야 옆으로 슬라이드 열리며 실제 아이콘/입력칸이
        나온다(``_SlideOutSection``). 지점/노드 유형/하중, 세 섹션은 한
        ``_SlideOutGroup``(아코디언)으로 묶여 있어 하나를 펼치면 나머지는
        자동으로 접힌다 — 여러 개를 동시에 펼쳐 두면 다시 다 나열된 느낌이
        되므로. **부재만 예외** — 단면·재료·핀 해제·노드 삽입까지 여러 줄이
        세로로 쌓여서, 이걸 옆으로 슬라이드하는 대신 인라인으로 펼치면 그
        높이만큼 막대 전체가 세로로 늘어나 캔버스가 줄어든다. 그래서 부재는
        슬라이드아웃이 아니라 별도의 작은 창(``_FloatingPropertiesWindow``,
        비모달)으로 띄운다 — 막대 높이에 영향을 주지 않고, 창이 열린 채로도
        캔버스에서 다른 부재를 계속 선택할 수 있다."""
        bar = QFrame()
        bar.setObjectName("directModelCommandBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)
        accordion = _SlideOutGroup()

        support_content = QWidget()
        support_layout = QHBoxLayout(support_content)
        support_layout.setContentsMargins(0, 0, 0, 0)
        support_layout.setSpacing(10)
        support_layout.addWidget(self._build_support_icon_row())
        support_layout.addWidget(QLabel("경사각(°)"))
        self.support_angle = self._number(0.0)
        self.support_angle.setRange(-360.0, 360.0)
        self.support_angle.setMaximumWidth(90)
        self.support_angle.setToolTip(
            "지지면이 수평에서 반시계 방향으로 기울어진 각도. 0이면 보통의 수평·수직 지점입니다."
        )
        self.support_angle.editingFinished.connect(self._apply_support)
        support_layout.addWidget(self.support_angle)
        self.support_custom_row = QWidget()
        custom_layout = QHBoxLayout(self.support_custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(8)
        self.support_dof_checks: dict[str, QCheckBox] = {}
        for dof in ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz"):
            box = QCheckBox(dof)
            box.toggled.connect(self._apply_support)
            self.support_dof_checks[dof] = box
            custom_layout.addWidget(box)
        self.support_custom_row.setVisible(False)
        support_layout.addWidget(self.support_custom_row)
        support_layout.addStretch(1)
        self.support_slide_out = _SlideOutSection("지점", support_content, group=accordion)
        layout.addWidget(self.support_slide_out)

        node_kind_content = QWidget()
        node_kind_layout = QHBoxLayout(node_kind_content)
        node_kind_layout.setContentsMargins(0, 0, 0, 0)
        node_kind_layout.setSpacing(6)
        node_kind_layout.addWidget(self._build_node_kind_icon_row())
        node_kind_layout.addStretch(1)
        self.node_kind_slide_out = _SlideOutSection("노드 유형", node_kind_content, group=accordion)
        layout.addWidget(self.node_kind_slide_out)

        member_button = QToolButton()
        member_button.setObjectName("slideOutToggle")
        member_button.setCheckable(True)
        member_button.setText("부재 ▸")
        member_button.setToolTip("선택한 부재의 단면·재료·핀 해제·노드 삽입을 작은 창에서 편집합니다.")
        member_button.clicked.connect(self._toggle_member_window)
        layout.addWidget(member_button)
        self.member_window_button = member_button
        self.member_window = _FloatingPropertiesWindow(
            "부재 속성", self._build_member_bar_content(), self._on_member_window_closed, self
        )

        self.load_slide_out = _SlideOutSection(
            "하중", self._build_load_bar_content(), group=accordion
        )
        layout.addWidget(self.load_slide_out)

        layout.addStretch(1)
        return bar

    def _build_support_icon_row(self) -> QWidget:
        """Icon buttons for 지점 조건, one per ``_SUPPORT_OPTIONS`` entry, applied
        the moment you click one — no separate 적용 button, matching the instant-
        apply feel of the 부재 단부 핀 해제 checkboxes below. Each icon mirrors the
        symbol ``SupportItem`` draws on the canvas so the button you clicked and the
        glyph that appears on the model read as the same shape."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.support_group = QButtonGroup(self)
        self.support_group.setExclusive(True)
        self.support_buttons: dict[int, QToolButton] = {}
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
            layout.addWidget(button)
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
        Always visible in the right panel, right under 좌표로 노드 추가 - not a
        collapsible section any more, since this panel now only ever holds
        these two always-on tools (every selection-dependent editor lives in
        the canvas-top bar instead).
        """
        section, root = self._section("노드 이동 · 복사 · 배열")
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
        노드 이동·복사·배열 rather than with the 부재 property window's
        section/material fields, since these add nodes instead of setting a
        property on the member that already exists.
        """
        section, root = self._section("부재 노드 삽입 · 등분할")
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
        selected member — the content shown inside the 부재 floating window
        (``_FloatingPropertiesWindow``), not an inline canvas-top-bar slide-out
        like 지점/노드 유형/하중, since this one stacks too many rows to slide
        open sideways without stretching the whole bar's height. Mid-span node
        insertion and equal subdivision live in the right panel's 노드 삽입·
        등분할 section instead (``_build_member_edit_section``) — they add
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
        section_row = QHBoxLayout()
        self.member_section_preview = _RectangleSectionPreview()
        section_row.addWidget(self.member_section_preview)
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
        section_row.addLayout(section_form, 1)
        root.addLayout(section_row)
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

        This is the content a 하중 ``_SlideOutSection`` reveals in the canvas-
        top bar — laid out horizontally, not as the vertical card it used to be
        in the right panel.
        """
        content = QWidget()
        root = QHBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(self._build_load_target_icon_row())
        self.load_form_layout = QHBoxLayout()
        self.load_form_layout.setSpacing(6)
        self.load_fields: dict[str, QDoubleSpinBox] = {}
        root.addLayout(self.load_form_layout)
        apply_button = QPushButton("적용")
        apply_button.setToolTip("선택 대상에 적용 (전체 성분)")
        apply_button.clicked.connect(self._apply_load)
        root.addWidget(apply_button)
        root.addStretch(1)
        self._load_target_changed()
        return content

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
        model = self.canvas.build_model()
        check = check_determinacy(model)
        self.determinacy_status.setText(f"정정성: {check.message}")
        # Real per-member (E, A, I) - set via the 부재 속성 section's 단면·재료
        # fields, stored on each Element's own properties - is what makes an
        # indeterminate 2D frame solvable at all. A determinate one solves
        # identically either way for reactions/N/V/M (equilibrium alone
        # already gives the exact answer), but still benefits: without any
        # member's section set, deflection has no absolute scale to report.
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

    def _activate_support_tool(self) -> None:
        self.select_tool.setChecked(True)
        self._set_mode("select", "지점을 적용할 노드를 선택한 뒤 위쪽 지점 막대에서 적용하세요.")
        self.selection_filter.setCurrentIndex(self.selection_filter.findData("nodes"))
        self._sync_property_panel()
        self.support_slide_out.set_expanded(True)

    def _activate_load_tool(self) -> None:
        self.select_tool.setChecked(True)
        self._set_mode("select", "하중을 적용할 대상을 선택한 뒤 위쪽 하중 막대에서 적용하세요.")
        self._sync_property_panel()
        self._load_target_changed()
        self.load_slide_out.set_expanded(True)

    def _selection_changed(self) -> None:
        self._sync_property_panel()

    def _toggle_member_window(self, checked: bool) -> None:
        self.member_window_button.setText("부재 ▾" if checked else "부재 ▸")
        if checked:
            button = self.member_window_button
            self.member_window.move(button.mapToGlobal(button.rect().bottomLeft()))
            self.member_window.show()
            self.member_window.raise_()
            self.member_window.activateWindow()
        else:
            self.member_window.hide()

    def _on_member_window_closed(self) -> None:
        self.member_window_button.setChecked(False)
        self.member_window_button.setText("부재 ▸")

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

        The right panel itself (좌표로 노드 추가, 이동·복사·배열) never changes
        visibility any more — both are always shown, full stop. What still
        needs refreshing on every selection change is the canvas-top bar's
        부재 슬라이드아웃 fields (only meaningful once exactly one member is
        selected), the 노드 유형/지점 icons' checked state, the create-section
        hint (its wording depends on how many nodes are selected), and the
        selection-summary text.
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
        intervening end-i/end-j boundary. Fields lay out left-to-right with
        short "qx:"/"Fx:" labels (not the full descriptive text, kept in the
        tooltip instead) because this strip now slides open sideways above the
        canvas rather than sitting as a vertical card in the right panel.
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
        if target == "node":
            components = (
                self._NODE_LOAD_COMPONENTS_3D if self.canvas.ndm == 3 else self._NODE_LOAD_COMPONENTS_2D
            )
            filter_key = "nodes"
        else:
            components = ("qx", "qx_j", "qy", "qy_j") if trapezoid else ("qx", "qy")
            filter_key = "elements"
        for component in components:
            field = self._number(0.0)
            field.setRange(-1_000_000.0, 1_000_000.0)
            field.setMaximumWidth(76)
            unit = self._unit_system.moment if component[0] == "m" else self._unit_system.force
            if target != "node":
                unit = f"{self._unit_system.force}/{self._unit_system.length}"
            self.load_fields[component] = field
            full_label = self._COMPONENT_LABELS[component]
            short_label = full_label.split(" ", 1)[0]
            if trapezoid and component in ("qx", "qy"):
                short_label += "(i)"
            elif component.endswith("_j"):
                short_label += "(j)"
            field.setToolTip(f"{full_label} ({unit})")
            self.load_form_layout.addWidget(QLabel(f"{short_label}:"))
            self.load_form_layout.addWidget(field)
        if hasattr(self, "selection_filter"):
            self.selection_filter.setCurrentIndex(self.selection_filter.findData(filter_key))

    def _apply_load(self) -> None:
        if self._current_load_target() == "node":
            components = (
                self._NODE_LOAD_COMPONENTS_3D if self.canvas.ndm == 3 else self._NODE_LOAD_COMPONENTS_2D
            )
            values = tuple(self.load_fields[component].value() for component in components)
            self.canvas.apply_nodal_load_to_selection(values)
        else:
            values = (self.load_fields["qx"].value(), self.load_fields["qy"].value())
            if "qx_j" in self.load_fields:
                values += (self.load_fields["qx_j"].value(), self.load_fields["qy_j"].value())
            self.canvas.apply_uniform_load_to_selection(values)

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
