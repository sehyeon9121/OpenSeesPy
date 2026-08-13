"""Post-processing result-type navigation."""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_ANIMATION_MS = 200

#: One short, standard engineering symbol per result *category* - drawn onto a
#: rounded chip instead of shipping per-category icon assets, and shown next
#: to the collapsible group's own title (e.g. the "REACTIONS" header), not on
#: every individual button inside it.
_GROUP_ICON_GLYPHS: dict[str, str] = {
    "OVERVIEW": "Σ",
    "SHAPE & NODE": "Δ",
    "DISPLACEMENT": "Δ",
    "REACTIONS": "R",
    "MEMBER FORCES": "F",
    "NONLINEAR": "P",
    "DATA": "▦",
    "MODAL RESPONSE": "φ",
    "TIME HISTORY": "t",
}
_ICON_CACHE: dict[str, QIcon] = {}


def _glyph_icon(glyph: str) -> QIcon:
    """A small rounded chip with ``glyph`` centered in it, in the app's own
    navy-on-light-blue accent colors - built once per glyph and cached, since
    every sidebar instance (main results view, the compact 2D one) needs the
    same handful of icons."""
    cached = _ICON_CACHE.get(glyph)
    if cached is not None:
        return cached
    size = 28
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor("#b7cdec"))
    painter.setBrush(QColor("#e7effb"))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 7, 7)
    painter.setPen(QColor("#174ea6"))
    font = painter.font()
    font.setPointSizeF(size * 0.42)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    icon = QIcon(pixmap)
    _ICON_CACHE[glyph] = icon
    return icon


class _CollapsibleResultGroup(QFrame):
    """One result-type category: a clickable header that slides its option
    list open/closed, so the sidebar can hold many categories without
    showing every option at once."""

    def __init__(
        self,
        title: str,
        hint: str,
        count: int,
        parent: QWidget | None = None,
        *,
        show_icon: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resultTypeGroup")
        self._expanded = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 3, 4, 3)
        outer.setSpacing(0)

        self._header = QWidget()
        self._header.setObjectName("resultTypeGroupHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._header.mousePressEvent = self._on_header_pressed  # type: ignore[method-assign]
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(2, 3, 2, 3)
        header_layout.setSpacing(3)

        _LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        self._arrow = QLabel("▸")
        self._arrow.setObjectName("resultTypeGroupArrow")
        header_layout.addWidget(self._arrow, 0, _LEFT)
        if show_icon:
            # Skipped in the compact embedded (2D-canvas) sidebar - that one is
            # barely 180-205px wide to begin with, nowhere near enough room for
            # an icon chip alongside arrow + title + count without overflowing
            # its own frame.
            icon_label = QLabel()
            icon_label.setObjectName("resultTypeGroupIcon")
            icon_label.setPixmap(_glyph_icon(_GROUP_ICON_GLYPHS.get(title, "•")).pixmap(18, 18))
            header_layout.addWidget(icon_label, 0, _LEFT)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("resultTypeGroupTitle")
        self.title_label.setAlignment(_LEFT)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        count_badge = QLabel(
            str(count) if not show_icon else f"{count} {'item' if count == 1 else 'items'}"
        )
        count_badge.setObjectName("resultTypeGroupCount")
        header_layout.addWidget(self.title_label, 1, _LEFT)
        header_layout.addWidget(count_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(self._header)

        self._body = QWidget()
        self._body.setObjectName("resultTypeGroupBody")
        self._body.setMaximumHeight(0)
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 2, 0, 1)
        body_layout.setSpacing(1)
        if hint:
            description = QLabel(hint)
            description.setObjectName("resultTypeGroupHint")
            description.setWordWrap(True)
            body_layout.addWidget(description)
        self._buttons_layout = body_layout
        outer.addWidget(self._body)

        self._animation = QPropertyAnimation(self._body, b"maximumHeight", self)
        self._animation.setDuration(_ANIMATION_MS)

    def add_button(self, button: QToolButton) -> None:
        self._buttons_layout.addWidget(button)

    def is_expanded(self) -> bool:
        return self._expanded

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool, *, animate: bool = True) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._arrow.setText("▾" if expanded else "▸")
        self._animation.stop()
        target_height = self._body.sizeHint().height() if expanded else 0
        if not animate:
            self._body.setMaximumHeight(target_height)
            return
        # A single easing curve looks decelerating in one direction and
        # accelerating in the other (same curve, opposite start/end), so
        # opening (grow toward its resting height) and closing (shrink
        # toward 0) each need their own curve to both read as smooth
        # instead of "fast jump then a long slow crawl."
        self._animation.setEasingCurve(
            QEasingCurve.Type.OutCubic if expanded else QEasingCurve.Type.InCubic
        )
        self._animation.setStartValue(self._body.maximumHeight())
        self._animation.setEndValue(target_height)
        self._animation.start()

    def _on_header_pressed(self, event) -> None:  # noqa: ANN001 - Qt event signature
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle()


class ResultTypeSidebar(QFrame):
    result_type_changed = Signal(str)

    def __init__(
        self, parent: QWidget | None = None, *, compact_2d: bool = False
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resultTypeSidebar")
        self._compact_2d = compact_2d
        self.setProperty("compact2d", compact_2d)
        self.setMinimumWidth(180 if compact_2d else 260)
        self.setMaximumWidth(205 if compact_2d else 520)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(6 if compact_2d else 7, 8, 6 if compact_2d else 7, 8)
        outer_layout.setSpacing(5 if compact_2d else 6)

        title = QLabel("RESULT NAVIGATOR" if compact_2d else "Results")
        title.setObjectName("resultSectionTitle")
        outer_layout.addWidget(title)
        if not compact_2d:
            description = QLabel("Choose the engineering quantity to display in the viewport.")
            description.setObjectName("resultTypeDescription")
            description.setWordWrap(True)
            outer_layout.addWidget(description)

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("resultTypeScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Keep the vertical scrollbar's width reserved at all times (instead
        # of the default "as needed"): an expand/collapse animation crossing
        # the show/hide threshold mid-motion would otherwise change the
        # viewport width, forcing every group to rewrap and relayout on that
        # one frame - the stutter this was reported as.
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        outer_layout.addWidget(self._scroll_area, 1)

        scroll_content = QWidget()
        scroll_content.setObjectName("resultTypeScrollContent")
        self._scroll_area.setWidget(scroll_content)
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        self._groups_by_key: dict[str, _CollapsibleResultGroup] = {}

        self._add_group(layout, "OVERVIEW", "", (("overview", "Summary" if compact_2d else "Overall model response"),))
        self._add_group(
            layout,
            "DISPLACEMENT" if compact_2d else "SHAPE & NODE",
            "",
            (
                ("deformation", "Deformed Shape"),
                # Not "Nodal Displacements" - the category header above already
                # says SHAPE & NODE, so repeating "Nodal" here only widened the
                # widest button in the whole sidebar for no extra clarity.
                ("displacement", "Displacements"),
            ),
        )
        self._add_group(
            layout,
            "REACTIONS",
            "",
            # Same trim as above - "Support" is already the category itself.
            (("reaction", "Reactions"),),
        )
        self._add_group(
            layout,
            "MEMBER FORCES",
            "",
            # "Force"/"Moment" dropped - MEMBER FORCES above already says so;
            # this was the widest button in the whole sidebar.
            (
                ("axial", "N Axial"),
                ("shear", "V Shear"),
                ("moment", "M Bending"),
            ),
        )
        if not compact_2d:
            self._add_group(
                layout,
                "NONLINEAR",
                "",
                (("pushover", "Pushover Curve"),),
            )
        self._add_group(
            layout,
            "DATA",
            "",
            (("tables", "Result Tables"),),
        )
        if not compact_2d:
            self._add_group(
                layout,
                "MODAL RESPONSE",
                "",
                (("mode_shapes", "Mode Shapes"),),
            )
            self._add_group(
                layout,
                "TIME HISTORY",
                "",
                # Not "Response History" - "History" already duplicates the
                # category name above.
                (("time_history", "Response"),),
            )
        layout.addStretch(1)

        # Every category starts collapsed - select_result_type("overview") below
        # opens only the active one, via _make_button's toggled -> set_expanded
        # wiring, so RESULTS opens as a short list of category headers rather
        # than a page already full of every option.
        self.select_result_type("overview")

    def select_result_type(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)
            self.result_type_changed.emit(key)

    def _add_group(
        self,
        layout: QVBoxLayout,
        title: str,
        hint: str,
        entries: tuple[tuple[str, str], ...],
    ) -> None:
        group = _CollapsibleResultGroup(title, hint, len(entries), show_icon=not self._compact_2d)
        for key, text in entries:
            button = self._make_button(key, text, group)
            group.add_button(button)
            self.buttons[key] = button
            self._groups_by_key[key] = group
        layout.addWidget(group)

    def _make_button(self, key: str, text: str, group: _CollapsibleResultGroup) -> QToolButton:
        button = QToolButton()
        button.setObjectName("resultTypeButton")
        button.setText(text)
        button.setCheckable(True)
        button.setProperty("forceDiagram", key in {"axial", "shear", "moment"})
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.clicked.connect(
            lambda checked=False, result_key=key: self.result_type_changed.emit(result_key)
        )
        # A selection can arrive from outside the sidebar (e.g. another panel
        # calling ResultsWorkspace.set_result_type), which checks the button
        # directly without going through select_result_type - reveal that
        # button's category either way so the highlighted choice is visible.
        button.toggled.connect(
            lambda checked, owner=group: owner.set_expanded(True) if checked else None
        )
        self._group.addButton(button)
        return button
