"""Full-screen gallery for the home screen's Templates card.

Each card shows a live-rendered preview (grabbed from a throwaway
``StaticsDrawingCanvas`` loaded with the template's own ``.ofsm`` data), not
a static image file - a template's geometry can never drift out of sync with
its own thumbnail this way, since the preview *is* the model.
"""

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from openframe.app.shell.page_header import PageHeader
from openframe.features.model.presentation.statics_modeling_page import StaticsDrawingCanvas
from openframe.features.templates.catalog import TemplateEntry, load_template_catalog

_PREVIEW_SIZE = (300, 170)
_COLUMNS = 3


class TemplateGalleryPage(QFrame):
    """Browses the bundled templates and hands a chosen one's parsed
    project dict back to whoever owns the actual workspace - this page never
    touches the workspace stack or session bookkeeping itself, matching how
    little StartWorkspace knows about the pages it opens into."""

    template_opened = Signal(dict, object)  # (project data, TemplateEntry) - MainWindow loads it
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("templateGalleryPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.page_header = PageHeader(
            "템플릿",
            "완성된 예제 모델로 바로 시작해보세요 - 지점·하중까지 미리 설정돼 있어 "
            "'정정성 검사 및 해석'을 바로 눌러볼 수 있습니다.",
            "← 홈으로",
        )
        self.page_header.action_requested.connect(self.back_requested)
        root.addWidget(self.page_header)

        scroll = QScrollArea()
        scroll.setObjectName("templateGalleryScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("templateGalleryContent")
        self._grid = QGridLayout(content)
        self._grid.setContentsMargins(24, 24, 24, 24)
        self._grid.setSpacing(20)
        for column in range(_COLUMNS):
            self._grid.setColumnStretch(column, 1)

        self._entries = load_template_catalog()
        if not self._entries:
            empty = QLabel(
                "템플릿을 불러오지 못했습니다 - resources/templates/manifest.json을 확인하세요."
            )
            empty.setObjectName("setupSectionHint")
            self._grid.addWidget(empty, 0, 0, 1, _COLUMNS)
        for index, entry in enumerate(self._entries):
            self._grid.addWidget(self._build_card(entry), index // _COLUMNS, index % _COLUMNS)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_card(self, entry: TemplateEntry) -> QFrame:
        card = QFrame()
        card.setObjectName("templateCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        preview = QLabel()
        preview.setObjectName("templateCardPreview")
        preview.setFixedSize(*_PREVIEW_SIZE)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setPixmap(self._render_preview(entry))
        layout.addWidget(preview)

        title = QLabel(entry.title)
        title.setObjectName("templateCardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        subtitle = QLabel(entry.subtitle)
        subtitle.setObjectName("templateCardSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        if entry.tags:
            tag_row = QHBoxLayout()
            tag_row.setSpacing(6)
            for tag in entry.tags:
                chip = QLabel(tag)
                chip.setObjectName("templateTagChip")
                tag_row.addWidget(chip)
            tag_row.addStretch(1)
            layout.addLayout(tag_row)

        description = QLabel(entry.description)
        description.setObjectName("setupSectionHint")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addStretch(1)

        # A precision template lands on SETUP (via the script-export/import
        # pipeline), not the canvas - the button text says so up front
        # instead of surprising the user with a different screen than every
        # other card leads to.
        open_button = QPushButton(
            "정밀해석으로 열기" if entry.analysis_kind else "이 템플릿 열기"
        )
        open_button.setObjectName("templateOpenButton")
        open_button.clicked.connect(lambda checked=False, e=entry: self._open(e))
        layout.addWidget(open_button)

        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        return card

    def _open(self, entry: TemplateEntry) -> None:
        try:
            data = json.loads(entry.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.template_opened.emit(data, entry)

    @staticmethod
    def _render_preview(entry: TemplateEntry) -> QPixmap:
        """Loads the template into a throwaway, never-shown canvas and grabs
        it as a picture - ``QWidget.grab()`` renders correctly even for a
        widget that was never shown (the same trick the offscreen Qt test
        platform relies on), so this needs no visible window at all."""
        blank = QPixmap(*_PREVIEW_SIZE)
        blank.fill(Qt.GlobalColor.transparent)
        try:
            data = json.loads(entry.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return blank
        canvas = StaticsDrawingCanvas()
        try:
            canvas.resize(*_PREVIEW_SIZE)
            # A never-shown QGraphicsView doesn't resize its viewport child
            # synchronously with resize() above - without pumping the resize
            # event through, fit_model() below fits against the *old* default
            # viewport size (Qt's stub ~638x478) while grab() still only
            # captures the real 300x170 area, so the fitted transform and the
            # captured pixels disagree and the preview shows little more than
            # the axis lines drifting through an otherwise-empty corner.
            QApplication.processEvents()
            canvas.load_dict(data)
            canvas.fit_model()
            pixmap = canvas.grab()
        finally:
            canvas.deleteLater()
        return pixmap if not pixmap.isNull() else blank
