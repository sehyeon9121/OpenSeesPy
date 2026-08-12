"""Accordion-style slide-out sections for the canvas-top command bar."""

from PySide6.QtCore import QPropertyAnimation, Qt
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget


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
