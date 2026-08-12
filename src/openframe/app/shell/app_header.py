"""Application command bar shared by modeling, analysis and results."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

ICON_DIRECTORY = Path(__file__).resolve().parents[2] / "resources" / "icons"
APP_ICON_PATH = ICON_DIRECTORY / "app_icon.png"


def _centered_png_icon(path: Path, canvas_size: int = 64, content_size: int = 54) -> QIcon:
    """Crop transparent imbalance and center a PNG's visible glyph.

    The source files are square, but their drawn pixels are not centered within
    those squares. QIcon normally preserves that uneven transparent padding.
    Cropping to the alpha bounds before placing the glyph on a fresh square
    makes all three header icons share one visual center and scale.
    """
    image = QImage(str(path))
    if image.isNull():
        return QIcon(str(path))

    min_x, min_y = image.width(), image.height()
    max_x = max_y = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 5:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        return QIcon(str(path))

    cropped = image.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
    scaled = cropped.scaled(
        content_size,
        content_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(canvas_size, canvas_size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawImage(
        (canvas_size - scaled.width()) // 2,
        (canvas_size - scaled.height()) // 2,
        scaled,
    )
    painter.end()
    return QIcon(canvas)


class AppHeader(QFrame):
    home_requested = Signal()
    direct_open_requested = Signal()
    upload_requested = Signal()
    run_requested = Signal()
    save_requested = Signal()
    settings_requested = Signal()
    help_requested = Signal()
    profile_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 10, 0)
        layout.setSpacing(6)

        # The reference header has two independent edges: brand + native menus
        # on the left and project commands on the right.  Keeping the brand in a
        # separate corner widget avoids the large blank band created when one
        # wide widget was forced into the menu bar's right corner.
        self.brand_panel = QFrame()
        self.brand_panel.setObjectName("appBrandPanel")
        brand_layout = QHBoxLayout(self.brand_panel)
        brand_layout.setContentsMargins(5, 0, 4, 0)
        brand_layout.setSpacing(7)
        self.brand_button = QPushButton("OF")
        self.brand_button.setObjectName("brandMark")
        if APP_ICON_PATH.exists():
            self.brand_button.setIcon(QIcon(str(APP_ICON_PATH)))
            self.brand_button.setIconSize(QSize(26, 26))
        else:
            self.brand_button.setText("OF")
        self.brand_button.clicked.connect(self.home_requested)
        self.brand_button.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.brand_button.setFixedSize(0, 0)
        self.brand_button.hide()
        self.brand_label = QPushButton("OpenFrame Studio")
        self.brand_label.setObjectName("brandName")
        self.brand_label.clicked.connect(self.home_requested)
        self.brand_label.setToolTip("")
        self.brand_label.setStatusTip("")
        self.brand_label.setWhatsThis("")
        self.brand_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.brand_panel.setMinimumWidth(205)
        self.brand_panel.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.home_button = QPushButton("HOME")
        self.home_button.setObjectName("homeButton")
        self.home_button.clicked.connect(self.home_requested)
        # Kept only as a compatibility attribute for older callers/tests.  It
        # must not remain in the brand layout: a hidden QPushButton can retain
        # stale geometry and leave a hover/click target beside the brand.
        self.home_button.setEnabled(False)
        self.home_button.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.home_button.setFixedSize(0, 0)
        self.home_button.hide()
        self.status_label = QLabel("●  READY")
        self.status_label.setObjectName("readyBadge")
        # Owned/exposed here for backward-compatible attribute access
        # (window.header.upload_button), but physically placed into the
        # WorkspaceNavigation row by MainWindow — the Stitch mockup puts
        # UPLOAD .PY next to the section tabs, not in this brand/actions row.
        self.upload_button = QPushButton("UPLOAD .PY")
        self.upload_button.setObjectName("uploadButton")
        self.upload_button.clicked.connect(self.upload_requested)
        self.direct_open_button = QPushButton("열기")
        self.direct_open_button.setObjectName("directModelOpenButton")
        self.direct_open_button.setToolTip(
            "저장된 OpenFrame 프로젝트(.ofsm)를 불러옵니다."
        )
        self.direct_open_button.clicked.connect(self.direct_open_requested)
        self.direct_open_button.hide()
        self.save_button = QPushButton("SAVE PROJECT")
        self.save_button.setObjectName("saveProjectButton")
        self.save_button.clicked.connect(self.save_requested)
        self.run_button = QPushButton("▶  RUN ANALYSIS")
        self.run_button.setObjectName("runButton")
        self.run_button.clicked.connect(self.run_requested)
        self.settings_button = QPushButton("⚙")
        self.settings_button.setObjectName("headerIconButton")
        self.settings_button.setText("")
        self.settings_button.setIcon(_centered_png_icon(ICON_DIRECTORY / "setting.png"))
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.setToolTip("Settings")
        self.settings_button.clicked.connect(self.settings_requested)
        self.help_button = QPushButton("?")
        self.help_button.setObjectName("headerIconButton")
        self.help_button.setText("")
        self.help_button.setIcon(_centered_png_icon(ICON_DIRECTORY / "help.png"))
        self.help_button.setIconSize(QSize(18, 18))
        self.help_button.setToolTip("Help")
        self.help_button.clicked.connect(self.help_requested)
        self.profile_button = QPushButton("\U0001f464")
        self.profile_button.setObjectName("headerIconButton")
        self.profile_button.setText("")
        self.profile_button.setIcon(_centered_png_icon(ICON_DIRECTORY / "user.png"))
        self.profile_button.setIconSize(QSize(18, 18))
        self.profile_button.setToolTip("Account")
        self.profile_button.clicked.connect(self.profile_requested)
        brand_layout.addWidget(self.brand_label)

        # Status is kept as an exposed state label for analysis progress and
        # compatibility, but the visible READY badge belongs to the project row.
        layout.addWidget(self.status_label)
        layout.addWidget(self.direct_open_button)
        layout.addWidget(self.save_button)
        layout.addWidget(self.run_button)
        divider = QFrame()
        divider.setObjectName("headerActionDivider")
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFixedHeight(22)
        layout.addWidget(divider)
        layout.addWidget(self.settings_button)
        layout.addWidget(self.help_button)
        layout.addWidget(self.profile_button)

    def set_welcome_mode(self, welcome: bool) -> None:
        """Keep the first-run screen focused on project entry choices."""
        self.direct_open_button.hide()
        self.save_button.setText("SAVE PROJECT")
        self.status_label.setText("STRUCTURAL MODELING & ANALYSIS" if welcome else "●  READY")
        self.status_label.setObjectName("welcomeHeaderLabel" if welcome else "readyBadge")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        # In project mode the breadcrumb row carries the READY/status badge
        # instead, so this label would otherwise duplicate it.
        self.status_label.setVisible(False)
        self.home_button.hide()
        self.upload_button.setVisible(not welcome)
        self.save_button.setVisible(not welcome)
        self.run_button.setVisible(not welcome)
        # Corner widgets do not automatically reclaim/release menu-bar width
        # when a child is shown or hidden.  Resize to the new natural width so
        # neither the brand nor HOME is clipped and no stale empty gap remains.
        self._fit_brand_panel()
        self.brand_panel.updateGeometry()
        self._fit_action_panel()

    def set_direct_model_mode(self, enabled: bool) -> None:
        """Show only authoring commands in the menu bar's right corner."""
        self.status_label.hide()
        self.home_button.hide()
        self.upload_button.hide()
        self.direct_open_button.setVisible(enabled)
        self.save_button.setVisible(enabled)
        self.save_button.setText("저장" if enabled else "SAVE PROJECT")
        self.run_button.setVisible(not enabled)
        self._fit_brand_panel()
        self._fit_action_panel()

    def _fit_brand_panel(self) -> None:
        """Keep the corner widget no wider than the visible brand itself."""
        self.brand_label.adjustSize()
        # Layout margins are 5 px left and 4 px right; the final pixel keeps
        # the panel's right border clear of the text button.
        self.brand_panel.setFixedWidth(self.brand_label.width() + 10)

    def _fit_action_panel(self) -> None:
        """Resize the menu-bar corner to its visible commands immediately.

        QMenuBar otherwise keeps the width it measured while SAVE PROJECT was
        hidden on Home.  When project mode shows that button, the stale narrow
        corner compresses and overlaps SAVE/RUN until a window resize happens.
        """
        self.setMinimumWidth(0)
        self.setMaximumWidth(16_777_215)
        self.layout().invalidate()
        self.layout().activate()
        self.setFixedWidth(self.layout().sizeHint().width())
        self.updateGeometry()
        menu_bar = self.parentWidget()
        if isinstance(menu_bar, QMenuBar):
            # Re-registering makes QMenuBar reposition the right corner now,
            # rather than waiting for the next maximize/restore resize event.
            menu_bar.setCornerWidget(self, Qt.Corner.TopRightCorner)

    def set_busy(self, busy: bool, label: str | None = "READING MODEL") -> None:
        self.status_label.setText(f"●  {label}" if busy and label else "●  READY")
        self.upload_button.setDisabled(busy)
        self.run_button.setDisabled(busy)
