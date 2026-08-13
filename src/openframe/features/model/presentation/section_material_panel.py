"""SECTION + MATERIAL property panel for one selected member.

Bridges three things that stay deliberately independent elsewhere in the
codebase, exactly the way the Master DB itself keeps geometry and material
apart:

- ``core.domain.section_properties`` - pure Area/Iy/Iz/J formulas for a
  hand-typed ("Custom") section.
- ``core.domain.material_section_db`` - the read-only Master DB
  (``SectionRecord``/``MaterialRecord``), queried but never modified here.
- ``StaticsDrawingCanvas.apply_full_section_to_selection`` - where a chosen
  section+material combination actually lands on the selected member(s).

A section is either "Custom" (dimensions typed by hand, properties computed
locally) or "Database" (dimensions and properties read from a Master DB
``SectionRecord``). Editing any dimension of a Database section demotes it to
CUSTOM immediately - the Master DB's own numbers are only trustworthy for the
exact designation they describe, not for whatever the user has since typed
over them with. "Reset to DB" restores the original Database record's values.

All geometry/property arithmetic happens in millimeters internally (the
Master DB's own unit), converted to the model's current unit system only at
the display boundary and when handing values to the canvas - see
``core.domain.units``.
"""

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import (
    DEFAULT_UNIT_SYSTEM,
    SUPPORTED_SHAPES,
    Element,
    MaterialDatabase,
    MaterialRecord,
    SectionDimensionError,
    SectionProperties,
    SectionRecord,
    UnitSystem,
    compute_section_properties,
    kN_m3_to_volumetric_force_unit,
    length_unit_to_mm,
    mm2_to_length_unit,
    mm4_to_length_unit,
    mm_to_length_unit,
    mpa_to_stress_unit,
)
from openframe.features.model.presentation.safe_spinbox import SafeDoubleSpinBox

#: Master DB ``Sections`` sheet dimension-column names, per shape, mapped to
#: the canonical dimension keys ``core.domain.section_properties`` expects.
#: The Master DB's own column names are quirky (``b_mm2``/``h_mm3`` are
#: Excel-column-collision-disambiguated, not meaningful suffixes) - this
#: mapping is the one place that quirk is translated, so nothing downstream
#: needs to know about it.
_DB_DIMENSION_KEY_MAP: dict[str, dict[str, str]] = {
    "Rectangle": {"b_mm2": "b", "h_mm3": "h"},
    "Circle": {"D_mm": "D"},
    "H/I Section": {"H_mm": "H", "B_mm": "B", "tw_mm": "tw", "tf_mm": "tf"},
    "Channel": {"H_mm": "H", "B_mm": "B", "tw_mm": "tw", "tf_mm": "tf"},
    "Angle": {"h_mm3": "H", "b_mm2": "B", "t_mm": "t"},
    "Box": {"h_mm3": "H", "b_mm2": "B", "t_mm": "t"},
    "Pipe": {"D_mm": "D", "t_mm": "t"},
}

#: Which dimension (already in mm) is the "governing thickness" a CONDITIONAL
#: material property (currently only fy_MPa, by plate thickness range) should
#: be resolved against - the Master DB has no notion of this for a Rectangle/
#: Circle/User Defined concrete-shaped section, so those simply resolve
#: without thickness context (concrete's fy is never CONDITIONAL anyway).
_GOVERNING_THICKNESS_KEY: dict[str, str] = {
    "H/I Section": "tf",
    "Channel": "tf",
    "Box": "t",
    "Pipe": "t",
    "Angle": "t",
}

#: This panel lives inside the existing 우측 워크트리's fixed-width (320px)
#: scroll area (see modeling_interface_page.py's ``modelingInspectorScroll``)
#: - every combo/spinbox gets an explicit max width so a long Database
#: designation or a default-sized QDoubleSpinBox can never force a horizontal
#: scrollbar onto the whole panel. Also satisfies this feature's own "작은
#: 입력창" (small input boxes) design requirement.
#:
#: Width regressions here must be checked on the *real* Qt platform, not
#: ``QT_QPA_PLATFORM=offscreen`` - the offscreen platform's fallback font has
#: measurably worse (wider) metrics than any real font, which once produced
#: a phantom ~340px ``minimumSizeHint()`` for this exact panel that the real
#: platform rendered at 232px with zero overflow. ``setMaximumWidth()`` also
#: caps how wide a widget may *grow*, never how small ``minimumSizeHint()``
#: says it may *shrink* - it does not, by itself, prevent a horizontal
#: scrollbar the way the comment below once assumed.
_COMBO_WIDTH = 168
_NUMBER_WIDTH = 92


class _CollapsibleSection(QFrame):
    """A foldable ``propertySectionCard`` - title header (click to toggle) +
    body. Deliberately a fresh, minimal, file-local implementation rather
    than reusing ``features.results.presentation.result_type_sidebar``'s
    ``_CollapsibleResultGroup``: that class bakes in result-only concerns
    (per-category icon glyphs, an item-count badge) that don't apply here,
    and this panel doesn't need the animated expand/collapse either - a
    plain instant show/hide keeps this small and self-contained instead of
    pulling in a cross-feature dependency for the sake of it."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("propertySectionCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(6)

        header = QWidget()
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self._arrow = QLabel("▾")
        title_label = QLabel(title)
        title_label.setObjectName("setupSectionTitle")
        header_layout.addWidget(self._arrow)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        header.mousePressEvent = self._header_clicked  # type: ignore[method-assign]
        outer.addWidget(header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        outer.addWidget(self.body)

        self._expanded = True

    def _header_clicked(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._arrow.setText("▾" if expanded else "▸")
        self.body.setVisible(expanded)

    def add_widget(self, widget: QWidget) -> None:
        self.body_layout.addWidget(widget)

    def add_layout(self, layout: QLayout) -> None:
        self.body_layout.addLayout(layout)


@dataclass(frozen=True, slots=True)
class _PreviewExtent:
    """A full dimension line between two points ON the shape's own boundary
    (local/unscaled coordinates, same space as the shape path) - e.g. the
    overall "H" or "B". Ticks are drawn at both ends and ``label`` is pushed
    a fixed *device*-pixel distance further out, away from the shape's
    center, so long/short members get the same legible label offset instead
    of one that grows or shrinks with the member's own size."""

    p1: tuple[float, float]
    p2: tuple[float, float]
    label: str


@dataclass(frozen=True, slots=True)
class _PreviewLeader:
    """A short pointer from a thin feature (tw/tf/t) out to its label -
    ``anchor`` is a point on that feature in local coordinates, ``direction``
    is the outward push in the same local convention as the shape path
    (+y = up); the actual on-screen leader length is a fixed device-pixel
    constant, not scaled by the member's physical size, for the same reason
    as ``_PreviewExtent``."""

    anchor: tuple[float, float]
    direction: tuple[float, float]
    label: str


_PreviewAnnotation = _PreviewExtent | _PreviewLeader


class SectionPreview(QWidget):
    """A small live-updating outline of the currently configured section,
    annotated with which typed dimension (H/B/D/tw/tf/t/...) corresponds to
    which part of the shape - Midas-style visual confirmation that typed
    dimensions look like what the user intended, generalized across all 7
    supported shapes via per-shape ``QPainterPath``/annotation builders.
    "User Defined" has no geometry to draw, so it just shows nothing.

    Every annotation's screen-space reach (leader length, label push, label
    box size) is a fixed device-pixel constant rather than a fraction of the
    shape's own (local-unit) dimensions - a member described in mm has
    numbers 1000x larger than the same member in m, so any local-space
    offset would blow up unpredictably once multiplied by the fit-to-widget
    ``scale`` factor. Fixed device-pixel constants make the required outer
    margin computable up front instead of guessed per shape."""

    _DIM_PEN_COLOR = QColor("#8b96a6")
    _TEXT_COLOR = QColor("#3a4a5e")
    _TICK_PX = 3.0
    _LEADER_PX = 18.0
    _LABEL_PUSH_PX = 13.0
    _LABEL_W = 24.0
    _LABEL_H = 12.0
    #: Uniform on every side: whichever direction a leader happens to point,
    #: it must clear _LEADER_PX + _LABEL_PUSH_PX + half a label box.
    _MARGIN = 40.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(184, 164)
        self.setToolTip("입력한 치수가 단면의 어느 부분에 대응하는지 보여주는 미리보기")
        self._shape = ""
        self._dimensions: dict[str, float] = {}

    def set_section(self, shape: str, dimensions: dict[str, float]) -> None:
        self._shape = shape
        self._dimensions = dict(dimensions)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        built = self._build_preview()
        if built is None:
            return
        path, annotations = built
        bounds = path.boundingRect()
        if bounds.width() <= 0 or bounds.height() <= 0:
            return

        inner = QRectF(self.rect()).adjusted(
            self._MARGIN, self._MARGIN, -self._MARGIN, -self._MARGIN
        )
        scale = min(inner.width() / bounds.width(), inner.height() / bounds.height())
        center = inner.center()
        shape_center = bounds.center()

        def to_device(point: tuple[float, float]) -> QPointF:
            return QPointF(
                center.x() + (point[0] - shape_center.x()) * scale,
                center.y() - (point[1] - shape_center.y()) * scale,
            )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        painter.save()
        painter.translate(center)
        painter.scale(scale, -scale)
        painter.translate(-shape_center.x(), -shape_center.y())
        pen = QPen(QColor("#2f6fd1"), 1.6)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(47, 111, 209, 45))
        painter.drawPath(path)
        painter.restore()

        font = painter.font()
        font.setPointSizeF(6.6)
        painter.setFont(font)
        shape_center_device = to_device((shape_center.x(), shape_center.y()))
        for annotation in annotations:
            if isinstance(annotation, _PreviewExtent):
                self._draw_extent(painter, annotation, to_device, shape_center_device)
            else:
                self._draw_leader(painter, annotation, to_device)

    def _draw_extent(
        self,
        painter: QPainter,
        extent: _PreviewExtent,
        to_device,
        shape_center_device: QPointF,
    ) -> None:
        p1 = to_device(extent.p1)
        p2 = to_device(extent.p2)
        self._stroke_with_ticks(painter, p1, p2)
        mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
        away = QPointF(mid.x() - shape_center_device.x(), mid.y() - shape_center_device.y())
        away_length = math.hypot(away.x(), away.y()) or 1.0
        label_anchor = QPointF(
            mid.x() + away.x() / away_length * self._LABEL_PUSH_PX,
            mid.y() + away.y() / away_length * self._LABEL_PUSH_PX,
        )
        self._draw_label(painter, label_anchor, extent.label)

    def _draw_leader(self, painter: QPainter, leader: _PreviewLeader, to_device) -> None:
        p1 = to_device(leader.anchor)
        dx, dy = leader.direction
        norm = math.hypot(dx, dy) or 1.0
        # direction is local (+y = up); device space is +y = down.
        ddx, ddy = dx / norm, -dy / norm
        p2 = QPointF(p1.x() + ddx * self._LEADER_PX, p1.y() + ddy * self._LEADER_PX)
        self._stroke_with_ticks(painter, p1, p2, tick_at_start_only=True)
        self._draw_label(painter, p2, leader.label)

    def _stroke_with_ticks(
        self, painter: QPainter, p1: QPointF, p2: QPointF, *, tick_at_start_only: bool = False
    ) -> None:
        pen = QPen(self._DIM_PEN_COLOR, 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        points = (p1,) if tick_at_start_only else (p1, p2)
        for point in points:
            painter.drawLine(
                QPointF(point.x() - nx * self._TICK_PX, point.y() - ny * self._TICK_PX),
                QPointF(point.x() + nx * self._TICK_PX, point.y() + ny * self._TICK_PX),
            )

    def _draw_label(self, painter: QPainter, anchor: QPointF, text: str) -> None:
        painter.setPen(self._TEXT_COLOR)
        rect = QRectF(
            anchor.x() - self._LABEL_W / 2,
            anchor.y() - self._LABEL_H / 2,
            self._LABEL_W,
            self._LABEL_H,
        )
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _build_preview(self) -> tuple[QPainterPath, list[_PreviewAnnotation]] | None:
        dims = self._dimensions
        try:
            if self._shape == "Rectangle":
                b, h = dims["b"], dims["h"]
                return _rectangle_preview_path(b, h), _rectangle_annotations(b, h)
            if self._shape == "Circle":
                d = dims["D"]
                return _circle_preview_path(d), _circle_annotations(d)
            if self._shape == "H/I Section":
                h, b, tw, tf = dims["H"], dims["B"], dims["tw"], dims["tf"]
                return _h_section_preview_path(h, b, tw, tf), _h_section_annotations(h, b, tw, tf)
            if self._shape == "Box":
                h, b, t = dims["H"], dims["B"], dims["t"]
                return _box_preview_path(h, b, t), _box_annotations(h, b, t)
            if self._shape == "Pipe":
                d, t = dims["D"], dims["t"]
                return _pipe_preview_path(d, t), _pipe_annotations(d, t)
            if self._shape == "Channel":
                h, b, tw, tf = dims["H"], dims["B"], dims["tw"], dims["tf"]
                return _channel_preview_path(h, b, tw, tf), _channel_annotations(h, b, tw, tf)
            if self._shape == "Angle":
                h, b, t = dims["H"], dims["B"], dims["t"]
                return _angle_preview_path(h, b, t), _angle_annotations(h, b, t)
        except (KeyError, ValueError, ZeroDivisionError):
            return None
        return None


def _rectangle_preview_path(b: float, h: float) -> QPainterPath:
    path = QPainterPath()
    path.addRect(-b / 2, -h / 2, b, h)
    return path


def _rectangle_annotations(b: float, h: float) -> list[_PreviewAnnotation]:
    gx, gy = b * 0.08, h * 0.08
    return [
        _PreviewExtent((-b / 2 - gx, -h / 2), (-b / 2 - gx, h / 2), "h"),
        _PreviewExtent((-b / 2, -h / 2 - gy), (b / 2, -h / 2 - gy), "b"),
    ]


def _circle_preview_path(d: float) -> QPainterPath:
    r = d / 2
    path = QPainterPath()
    path.addEllipse(QRectF(-r, -r, d, d))
    return path


def _circle_annotations(d: float) -> list[_PreviewAnnotation]:
    k = d / 2 * 0.70710678
    return [_PreviewExtent((-k, -k), (k, k), "D")]


def _h_section_preview_path(height: float, width: float, tw: float, tf: float) -> QPainterPath:
    x1, x2 = -width / 2, width / 2
    y1, y2, y3, y4 = -height / 2, -height / 2 + tf, height / 2 - tf, height / 2
    xw1, xw2 = -tw / 2, tw / 2
    points = [
        (x1, y1), (x2, y1), (x2, y2), (xw2, y2), (xw2, y3), (x2, y3),
        (x2, y4), (x1, y4), (x1, y3), (xw1, y3), (xw1, y2), (x1, y2),
    ]
    return _polygon_path(points)


def _h_section_annotations(height: float, width: float, tw: float, tf: float) -> list[_PreviewAnnotation]:
    gx, gy = width * 0.08, height * 0.08
    flange_y = height / 2 - tf / 2
    return [
        _PreviewExtent((-width / 2 - gx, -height / 2), (-width / 2 - gx, height / 2), "H"),
        _PreviewExtent((-width / 2, -height / 2 - gy), (width / 2, -height / 2 - gy), "B"),
        # tw/tf both sit on the shape's right side, close together when the
        # flange is thick relative to the height - pointing them at opposite
        # diagonal corners (down-right vs up-right) keeps them apart by
        # construction instead of relying on however much vertical room
        # ``flange_y`` happens to leave for this particular H/B/tf ratio.
        _PreviewLeader((tw / 2, 0.0), (1.0, -1.0), "tw"),
        _PreviewLeader((width / 2, flange_y), (1.0, 1.0), "tf"),
    ]


def _box_preview_path(height: float, width: float, t: float) -> QPainterPath:
    path = QPainterPath()
    path.addRect(-width / 2, -height / 2, width, height)
    inner_w, inner_h = width - 2 * t, height - 2 * t
    if inner_w > 0 and inner_h > 0:
        path.addRect(-inner_w / 2, -inner_h / 2, inner_w, inner_h)
    path.setFillRule(Qt.FillRule.OddEvenFill)
    return path


def _box_annotations(height: float, width: float, t: float) -> list[_PreviewAnnotation]:
    gx, gy = width * 0.08, height * 0.08
    return [
        _PreviewExtent((-width / 2 - gx, -height / 2), (-width / 2 - gx, height / 2), "H"),
        _PreviewExtent((-width / 2, -height / 2 - gy), (width / 2, -height / 2 - gy), "B"),
        _PreviewLeader((width / 2 - t / 2, height / 2 - t / 2), (1.0, 1.0), "t"),
    ]


def _pipe_preview_path(d: float, t: float) -> QPainterPath:
    r = d / 2
    path = QPainterPath()
    path.addEllipse(QRectF(-r, -r, d, d))
    inner_r = r - t
    if inner_r > 0:
        path.addEllipse(QRectF(-inner_r, -inner_r, inner_r * 2, inner_r * 2))
    path.setFillRule(Qt.FillRule.OddEvenFill)
    return path


def _pipe_annotations(d: float, t: float) -> list[_PreviewAnnotation]:
    r = d / 2
    k = r * 0.70710678
    return [
        _PreviewExtent((-k, -k), (k, k), "D"),
        _PreviewLeader((r - t / 2, 0.0), (1.0, 0.0), "t"),
    ]


def _channel_preview_path(height: float, width: float, tw: float, tf: float) -> QPainterPath:
    x0, x1 = 0.0, width
    y1, y2, y3, y4 = -height / 2, -height / 2 + tf, height / 2 - tf, height / 2
    points = [
        (x0, y1), (x1, y1), (x1, y2), (tw, y2), (tw, y3), (x1, y3), (x1, y4), (x0, y4),
    ]
    return _polygon_path(points)


def _channel_annotations(height: float, width: float, tw: float, tf: float) -> list[_PreviewAnnotation]:
    gx, gy = width * 0.10, height * 0.08
    flange_y = height / 2 - tf / 2
    return [
        _PreviewExtent((-gx, -height / 2), (-gx, height / 2), "H"),
        _PreviewExtent((0.0, -height / 2 - gy), (width, -height / 2 - gy), "B"),
        _PreviewLeader((tw / 2, 0.0), (1.0, -1.0), "tw"),
        _PreviewLeader((width, flange_y), (1.0, 1.0), "tf"),
    ]


def _angle_preview_path(height: float, width: float, t: float) -> QPainterPath:
    points = [(0.0, 0.0), (width, 0.0), (width, t), (t, t), (t, height), (0.0, height)]
    return _polygon_path(points)


def _angle_annotations(height: float, width: float, t: float) -> list[_PreviewAnnotation]:
    gx, gy = width * 0.10, height * 0.08
    return [
        _PreviewExtent((-gx, 0.0), (-gx, height), "H"),
        _PreviewExtent((0.0, -gy), (width, -gy), "B"),
        _PreviewLeader((t / 2, t * 1.5), (0.5, 0.5), "t"),
    ]


def _polygon_path(points: list[tuple[float, float]]) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    path.closeSubpath()
    return path


def _load_database_safely() -> MaterialDatabase | None:
    """The Excel/cache-backed Master DB is bundled data, not something a
    canvas session can recover from if it is missing or malformed - Database
    section/material selection just degrades to unavailable (Custom keeps
    working) rather than crashing the whole modeling page over it."""
    try:
        from openframe.infrastructure.material_section_db import load_material_database

        return load_material_database()
    except Exception:  # noqa: BLE001 - any load failure degrades gracefully.
        return None


class SectionMaterialPanel(QWidget):
    apply_requested = Signal()
    #: Fires whenever any field that feeds ``current_application_kwargs()``
    #: changes *by the user's own typing* - never while ``load_from_element``
    #: is repopulating the panel from a freshly (re)selected member. The
    #: Selection Status inspector listens for this to re-evaluate its
    #: Applied/Pending Changes badge live, without touching any of its own
    #: displayed values (those only ever come from the model itself, on a
    #: full refresh - see ``modeling_interface_page.py``'s
    #: ``_sync_selection_status``/``_selection_status_edited``).
    edited = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit_system: UnitSystem = DEFAULT_UNIT_SYSTEM
        self._database: MaterialDatabase | None = _load_database_safely()
        self._db_section: SectionRecord | None = None
        self._is_custom_override = False
        self._dimensions_mm: dict[str, float] = {}
        self._properties: SectionProperties | None = None
        self._dimension_spinboxes: dict[str, SafeDoubleSpinBox] = {}
        self._dimension_labels: dict[str, QLabel] = {}
        self._selected_material: MaterialRecord | None = None
        self._updating = False  # guards against feedback loops while repopulating fields
        self._loading_element = False  # True only while load_from_element() runs

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # -- SECTION ----------------------------------------------------------
        section_group = _CollapsibleSection("SECTION")

        type_row = QFormLayout()
        type_row.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(SUPPORTED_SHAPES)
        self.shape_combo.setMaximumWidth(_COMBO_WIDTH)
        self.shape_combo.currentTextChanged.connect(self._shape_changed)
        type_row.addRow("Section Type", self.shape_combo)
        section_group.add_layout(type_row)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source"))
        self.source_custom = QRadioButton("Custom")
        self.source_database = QRadioButton("Database")
        self.source_custom.setChecked(True)
        self._source_group = QButtonGroup(self)
        self._source_group.addButton(self.source_custom)
        self._source_group.addButton(self.source_database)
        self.source_custom.toggled.connect(self._source_changed)
        source_row.addWidget(self.source_custom)
        source_row.addWidget(self.source_database)
        source_row.addStretch(1)
        section_group.add_layout(source_row)

        self.designation_row = QWidget()
        designation_layout = QFormLayout(self.designation_row)
        designation_layout.setContentsMargins(0, 0, 0, 0)
        designation_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.designation_combo = QComboBox()
        self.designation_combo.setMaximumWidth(_COMBO_WIDTH)
        self.designation_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.designation_combo.setMinimumContentsLength(10)
        self.designation_combo.currentIndexChanged.connect(self._designation_changed)
        designation_layout.addRow("Designation", self.designation_combo)
        section_group.add_widget(self.designation_row)

        self.section_preview = SectionPreview()
        preview_row = QHBoxLayout()
        preview_row.addStretch(1)
        preview_row.addWidget(self.section_preview)
        preview_row.addStretch(1)
        section_group.add_layout(preview_row)

        section_group.add_widget(QLabel("Geometry"))
        self.geometry_form = QFormLayout()
        self.geometry_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        section_group.add_layout(self.geometry_form)

        self.reset_to_db_button = QPushButton("Reset to DB")
        self.reset_to_db_button.clicked.connect(self._reset_to_db)
        self.reset_to_db_button.setVisible(False)
        section_group.add_widget(self.reset_to_db_button)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("setupSectionHint")
        self.validation_label.setWordWrap(True)
        section_group.add_widget(self.validation_label)

        root.addWidget(section_group)

        # -- SECTION PROPERTIES -------------------------------------------
        properties_group = _CollapsibleSection("SECTION PROPERTIES")
        self.property_form = QFormLayout()
        self.property_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._property_spinboxes: dict[str, SafeDoubleSpinBox] = {}
        self._property_badges: dict[str, QLabel] = {}
        self._property_labels: dict[str, QLabel] = {}
        for key, label_text in (("area", "Area"), ("Iy", "Iy"), ("Iz", "Iz"), ("J", "J")):
            spin = SafeDoubleSpinBox()
            spin.setDecimals(9)
            spin.setRange(0.0, 1.0e15)
            spin.setMaximumWidth(_NUMBER_WIDTH)
            spin.valueChanged.connect(lambda _value, k=key: self._user_defined_property_changed(k))
            badge = QLabel("CUSTOM")
            badge.setObjectName("setupSectionHint")
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(spin)
            row_layout.addWidget(badge)
            row_layout.addStretch(1)
            row_label = QLabel(label_text)
            self.property_form.addRow(row_label, row)
            self._property_spinboxes[key] = spin
            self._property_badges[key] = badge
            self._property_labels[key] = row_label
        properties_group.add_layout(self.property_form)
        root.addWidget(properties_group)

        # -- MATERIAL -----------------------------------------------------
        material_group = _CollapsibleSection("MATERIAL")
        material_form = QFormLayout()
        material_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.material_category_combo = QComboBox()
        self.material_category_combo.setMaximumWidth(_COMBO_WIDTH)
        self.material_category_combo.currentTextChanged.connect(self._material_category_changed)
        material_form.addRow("Category", self.material_category_combo)
        self.material_grade_combo = QComboBox()
        self.material_grade_combo.setMaximumWidth(_COMBO_WIDTH)
        self.material_grade_combo.currentIndexChanged.connect(self._material_grade_changed)
        material_form.addRow("Grade", self.material_grade_combo)
        self.material_e = SafeDoubleSpinBox()
        self.material_e.setRange(0.0, 1.0e12)
        self.material_e.setDecimals(3)
        self.material_e.setMaximumWidth(_NUMBER_WIDTH)
        self.material_e.valueChanged.connect(self._notify_edited)
        self._material_e_label = QLabel("E")
        material_form.addRow(self._material_e_label, self.material_e)
        self.material_unit_weight = SafeDoubleSpinBox()
        self.material_unit_weight.setRange(0.0, 1.0e9)
        self.material_unit_weight.setDecimals(6)
        self.material_unit_weight.setMaximumWidth(_NUMBER_WIDTH)
        self.material_unit_weight.setToolTip(
            "자중(自重) 계산에 쓰이는 단위중량 - 0이면 이 부재는 자중 계산에서 빠집니다."
        )
        self.material_unit_weight.valueChanged.connect(self._notify_edited)
        self._material_unit_weight_label = QLabel("Unit Weight")
        material_form.addRow(self._material_unit_weight_label, self.material_unit_weight)
        self.material_fy = SafeDoubleSpinBox()
        self.material_fy.setRange(0.0, 1.0e9)
        self.material_fy.setDecimals(3)
        self.material_fy.setMaximumWidth(_NUMBER_WIDTH)
        self.material_fy.setToolTip(
            "참고용 항복강도 표시입니다 - 이번 단계의 해석은 탄성 재료만 다루므로 "
            "이 값 자체는 해석에 쓰이지 않습니다."
        )
        self._material_fy_label = QLabel("fy")
        material_form.addRow(self._material_fy_label, self.material_fy)
        material_group.add_layout(material_form)
        root.addWidget(material_group)

        self.apply_button = QPushButton("선택 부재에 적용")
        self.apply_button.clicked.connect(self._apply_clicked)
        root.addWidget(self.apply_button)

        self._populate_material_categories()
        self._shape_changed(self.shape_combo.currentText())
        self._refresh_unit_suffixes()

    # -- unit system ------------------------------------------------------
    def set_unit_system(self, unit_system: UnitSystem) -> None:
        """Labels only change what a given internal (mm-canonical for
        geometry, model-unit for material) number is *shown* as - exactly
        this app's existing "change the label, never silently rescale a
        typed value" unit-system convention. Values are re-derived from the
        already-stored mm/DB state, not reinterpreted."""
        self._unit_system = unit_system
        self._refresh_dimension_field_labels()
        self._refresh_property_display()
        self._refresh_material_display()
        self._refresh_unit_suffixes()

    def _refresh_unit_suffixes(self) -> None:
        """Field captions show the current unit system right next to the
        value they belong to (e.g. "H (m)", "E (kN/m²)") - Database-sourced
        values already convert their *number* on a unit-system change (see
        ``set_unit_system``'s docstring); this only ever touches label text,
        never a stored value."""
        length = self._unit_system.length
        for key, label in self._dimension_labels.items():
            label.setText(f"{key} ({length})")
        if "area" in self._property_labels:
            self._property_labels["area"].setText(f"Area ({length}²)")
        if "Iy" in self._property_labels:
            self._property_labels["Iy"].setText(f"Iy ({length}⁴)")
        if "Iz" in self._property_labels:
            self._property_labels["Iz"].setText(f"Iz ({length}⁴)")
        if "J" in self._property_labels:
            self._property_labels["J"].setText(f"J ({length}⁴)")
        stress = self._unit_system.stress
        self._material_e_label.setText(f"E ({stress})")
        self._material_fy_label.setText(f"fy ({stress})")
        self._material_unit_weight_label.setText(
            f"Unit Weight ({self._unit_system.volumetric_force})"
        )

    # -- shape / source ----------------------------------------------------
    def _shape_changed(self, shape: str) -> None:
        if self._updating:
            return
        self._db_section = None
        self._is_custom_override = False
        self._dimensions_mm = {}
        self._properties = None
        self._rebuild_geometry_form(shape)
        self._refresh_database_availability()
        self._recompute_from_dimensions()

    def _rebuild_geometry_form(self, shape: str) -> None:
        while self.geometry_form.rowCount():
            self.geometry_form.removeRow(0)
        self._dimension_spinboxes = {}
        self._dimension_labels = {}
        if shape == "User Defined":
            self._set_properties_editable(True)
            self.section_preview.setVisible(False)
            return
        self._set_properties_editable(False)
        self.section_preview.setVisible(True)
        from openframe.core.domain import dimension_fields

        length = self._unit_system.length
        for field in dimension_fields(shape):
            spin = SafeDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(0.000001, 1.0e9)
            spin.setValue(1.0)
            spin.setMaximumWidth(_NUMBER_WIDTH)
            spin.valueChanged.connect(lambda _value, key=field.key: self._dimension_changed(key))
            row_label = QLabel(f"{field.label} ({length})")
            self.geometry_form.addRow(row_label, spin)
            self._dimension_spinboxes[field.key] = spin
            self._dimension_labels[field.key] = row_label
            # setValue(1.0) above fires before valueChanged is connected, so
            # _dimension_changed never runs for it - fill _dimensions_mm with
            # that same default here, otherwise a freshly switched shape
            # shows a blank preview/zeroed properties until the user
            # actually edits something.
            self._dimensions_mm[field.key] = length_unit_to_mm(1.0, length)

    def _set_properties_editable(self, editable: bool) -> None:
        for spin in self._property_spinboxes.values():
            spin.setReadOnly(not editable)
            spin.setButtonSymbols(
                SafeDoubleSpinBox.ButtonSymbols.NoButtons
                if not editable
                else SafeDoubleSpinBox.ButtonSymbols.UpDownArrows
            )

    def _refresh_database_availability(self) -> None:
        shape = self.shape_combo.currentText()
        sections = self._sections_for_shape(shape)
        available = bool(sections)
        self.source_database.setEnabled(available)
        self.source_database.setToolTip(
            "" if available else "이 단면 종류는 DB에 등록된 규격이 없습니다."
        )
        if not available and self.source_database.isChecked():
            self.source_custom.setChecked(True)
        self.designation_combo.blockSignals(True)
        self.designation_combo.clear()
        for section in sections:
            self.designation_combo.addItem(section.designation, section.section_id)
        self.designation_combo.blockSignals(False)
        self._source_changed()

    def _sections_for_shape(self, shape: str) -> tuple[SectionRecord, ...]:
        if self._database is None or shape == "User Defined":
            return ()
        return tuple(
            section for section in self._database.all_sections() if section.shape == shape
        )

    def _source_changed(self) -> None:
        is_database = self.source_database.isChecked()
        self.designation_row.setVisible(is_database)
        for spin in self._dimension_spinboxes.values():
            spin.setReadOnly(is_database and not self._is_custom_override)
        if is_database and self.designation_combo.count():
            self._designation_changed(self.designation_combo.currentIndex())
        elif not is_database:
            self._db_section = None
            self._is_custom_override = False
            self.reset_to_db_button.setVisible(False)
            self._recompute_from_dimensions()

    # -- Database section selection ---------------------------------------
    def _designation_changed(self, index: int) -> None:
        if index < 0 or self._database is None:
            return
        section_id = self.designation_combo.itemData(index)
        if section_id is None:
            return
        section = self._database.get_section(section_id)
        self._load_db_section(section)

    def _load_db_section(self, section: SectionRecord) -> None:
        self._db_section = section
        self._is_custom_override = False
        shape = section.shape
        key_map = _DB_DIMENSION_KEY_MAP.get(shape, {})
        self._dimensions_mm = {
            canonical: section.dimensions[raw]
            for raw, canonical in key_map.items()
            if raw in section.dimensions
        }
        self._apply_dimensions_to_spinboxes()
        if None not in (section.area_mm2, section.Iy_mm4, section.Iz_mm4, section.J_mm4):
            self._properties = SectionProperties(
                section.area_mm2, section.Iy_mm4, section.Iz_mm4, section.J_mm4
            )
        else:
            # A handful of Master DB seed records (Channel/Angle) have no
            # stored Iy/Iz yet - fall back to computing from the DB's own
            # dimensions rather than showing a blank property the member
            # cannot actually be analyzed with.
            self._properties = self._safe_compute(shape, self._dimensions_mm)
        for spin in self._dimension_spinboxes.values():
            spin.setReadOnly(True)
        self.reset_to_db_button.setVisible(True)
        self.validation_label.setText("")
        self._refresh_property_display()
        self._refresh_preview()

    def _reset_to_db(self) -> None:
        if self._db_section is not None:
            self._load_db_section(self._db_section)

    def _apply_dimensions_to_spinboxes(self) -> None:
        self._updating = True
        try:
            for key, spin in self._dimension_spinboxes.items():
                value_mm = self._dimensions_mm.get(key)
                if value_mm is None:
                    continue
                spin.blockSignals(True)
                spin.setValue(mm_to_length_unit(value_mm, self._unit_system.length))
                spin.blockSignals(False)
        finally:
            self._updating = False

    def _refresh_dimension_field_labels(self) -> None:
        self._apply_dimensions_to_spinboxes()

    # -- dimension editing (Custom, or a Database section being overridden) --
    def _dimension_changed(self, key: str) -> None:
        if self._updating:
            return
        spin = self._dimension_spinboxes.get(key)
        if spin is None:
            return
        self._dimensions_mm[key] = length_unit_to_mm(spin.value(), self._unit_system.length)
        if self._db_section is not None and not self._is_custom_override:
            self._is_custom_override = True
            for other in self._dimension_spinboxes.values():
                other.setReadOnly(False)
        self._recompute_from_dimensions()

    def _recompute_from_dimensions(self) -> None:
        shape = self.shape_combo.currentText()
        self._refresh_preview()
        self._notify_edited()
        if shape == "User Defined":
            self._refresh_property_display()
            return
        if not self._dimension_spinboxes:
            return
        self._properties = self._safe_compute(shape, self._dimensions_mm)
        self._refresh_property_display()

    def _notify_edited(self) -> None:
        if not self._loading_element:
            self.edited.emit()

    def _refresh_preview(self) -> None:
        shape = self.shape_combo.currentText()
        self.section_preview.setVisible(shape != "User Defined")
        self.section_preview.set_section(shape, self._dimensions_mm)

    def _safe_compute(self, shape: str, dimensions_mm: dict[str, float]) -> SectionProperties | None:
        try:
            properties = compute_section_properties(shape, dimensions_mm)
        except SectionDimensionError as error:
            self.validation_label.setText(f"⚠ {error}")
            self.apply_button.setEnabled(False)
            return None
        self.validation_label.setText("")
        self.apply_button.setEnabled(True)
        return properties

    # -- properties display -------------------------------------------------
    def _user_defined_property_changed(self, key: str) -> None:
        if self._updating or self.shape_combo.currentText() != "User Defined":
            return
        self._sync_user_defined_properties()

    def _sync_user_defined_properties(self) -> None:
        self._notify_edited()
        length = self._unit_system.length
        area = self._property_spinboxes["area"].value()
        iy = self._property_spinboxes["Iy"].value()
        iz = self._property_spinboxes["Iz"].value()
        j = self._property_spinboxes["J"].value()
        if area <= 0.0 or iy <= 0.0 or iz <= 0.0 or j <= 0.0:
            self.validation_label.setText("⚠ Area/Iy/Iz/J은(는) 0보다 커야 합니다.")
            self.apply_button.setEnabled(False)
            self._properties = None
            return
        self.validation_label.setText("")
        self.apply_button.setEnabled(True)
        # User Defined values are typed directly in the model's own unit
        # system (there is no real-world mm dimension backing them), so they
        # are converted *into* the mm-canonical form the rest of this panel
        # (and current_application_kwargs) uses uniformly.
        self._properties = SectionProperties(
            area_mm2=area * _mm2_per_unit(length),
            Iy_mm4=iy * _mm4_per_unit(length),
            Iz_mm4=iz * _mm4_per_unit(length),
            J_mm4=j * _mm4_per_unit(length),
        )

    def _refresh_property_display(self) -> None:
        shape = self.shape_combo.currentText()
        length = self._unit_system.length
        status = "DB" if (self._db_section is not None and not self._is_custom_override) else "CUSTOM"
        for badge in self._property_badges.values():
            badge.setText(status)
        if shape == "User Defined":
            return
        if self._properties is None:
            for spin in self._property_spinboxes.values():
                spin.blockSignals(True)
                spin.setValue(0.0)
                spin.blockSignals(False)
            return
        self._updating = True
        try:
            self._property_spinboxes["area"].setValue(
                mm2_to_length_unit(self._properties.area_mm2, length)
            )
            self._property_spinboxes["Iy"].setValue(
                mm4_to_length_unit(self._properties.Iy_mm4, length)
            )
            self._property_spinboxes["Iz"].setValue(
                mm4_to_length_unit(self._properties.Iz_mm4, length)
            )
            self._property_spinboxes["J"].setValue(
                mm4_to_length_unit(self._properties.J_mm4, length)
            )
        finally:
            self._updating = False

    # -- material -----------------------------------------------------------
    def _populate_material_categories(self) -> None:
        if self._database is None:
            self.material_category_combo.setEnabled(False)
            self.material_grade_combo.setEnabled(False)
            return
        self.material_category_combo.addItems(self._database.get_material_categories())

    def _material_category_changed(self, category: str) -> None:
        if self._database is None:
            return
        self.material_grade_combo.blockSignals(True)
        self.material_grade_combo.clear()
        for material in self._database.get_materials_by_category(category):
            self.material_grade_combo.addItem(material.grade, material.material_id)
        self.material_grade_combo.blockSignals(False)
        if self.material_grade_combo.count():
            self._material_grade_changed(0)

    def _material_grade_changed(self, index: int) -> None:
        if self._database is None or index < 0:
            self._selected_material = None
            return
        material_id = self.material_grade_combo.itemData(index)
        if material_id is None:
            self._selected_material = None
            return
        self._selected_material = self._database.get_material(material_id)
        self._refresh_material_display()
        self._notify_edited()

    def _refresh_material_display(self) -> None:
        if self._database is None or self._selected_material is None:
            return
        material_id = self._selected_material.material_id
        thickness_key = _GOVERNING_THICKNESS_KEY.get(self.shape_combo.currentText())
        context = None
        if thickness_key is not None and thickness_key in self._dimensions_mm:
            context = {"thickness_mm": self._dimensions_mm[thickness_key]}

        force = self._unit_system.force
        length = self._unit_system.length
        e_resolution = self._database.resolve_property(material_id, "E_MPa")
        if e_resolution.value is not None:
            self.material_e.setValue(mpa_to_stress_unit(e_resolution.value, force, length))
        unit_weight_resolution = self._database.resolve_property(material_id, "unit_weight_kN_m3")
        if unit_weight_resolution.value is not None:
            self.material_unit_weight.setValue(
                kN_m3_to_volumetric_force_unit(unit_weight_resolution.value, force, length)
            )
        fy_resolution = self._database.resolve_property(material_id, "fy_MPa", context=context)
        if fy_resolution.value is not None:
            self.material_fy.setValue(mpa_to_stress_unit(fy_resolution.value, force, length))

    # -- element <-> panel -----------------------------------------------
    def load_from_element(self, element: Element) -> None:
        """Repopulate every field from a re-selected member's stored
        properties - a member saved before this feature existed (or set
        through the legacy ``apply_section_to_selection``) has no
        ``section_shape`` key at all, so it falls back to Rectangle/Custom
        using the old width/height/E/density keys, exactly what it used to
        show.

        The whole body runs under ``_loading_element`` - repopulating every
        field here is not a user edit, so none of it should fire ``edited``
        (that would make the Selection Status inspector misreport a
        freshly-(re)selected, untouched member as "Pending Changes")."""
        self._loading_element = True
        try:
            self._load_from_element(element)
        finally:
            self._loading_element = False

    def _load_from_element(self, element: Element) -> None:
        self._updating = True
        try:
            shape = str(element.properties.get("section_shape", "Rectangle"))
            if shape not in SUPPORTED_SHAPES:
                shape = "Rectangle"
            index = self.shape_combo.findText(shape)
            if index >= 0:
                self.shape_combo.setCurrentIndex(index)
        finally:
            self._updating = False
        self._rebuild_geometry_form(shape)
        self._refresh_database_availability()

        source = str(element.properties.get("section_source", "custom"))
        self.source_database.blockSignals(True)
        self.source_custom.blockSignals(True)
        if source == "database" and self.source_database.isEnabled():
            self.source_database.setChecked(True)
        else:
            self.source_custom.setChecked(True)
        self.source_database.blockSignals(False)
        self.source_custom.blockSignals(False)
        self.designation_row.setVisible(self.source_database.isChecked())

        dimensions_mm: dict[str, float] = {}
        for key in self._dimension_spinboxes:
            raw = element.properties.get(f"dim_{key}")
            if raw is not None:
                dimensions_mm[key] = length_unit_to_mm(float(raw), self._unit_system.length)
        if shape == "Rectangle" and not dimensions_mm:
            width = element.properties.get("width")
            height = element.properties.get("height")
            if width is not None:
                dimensions_mm["b"] = length_unit_to_mm(float(width), self._unit_system.length)
            if height is not None:
                dimensions_mm["h"] = length_unit_to_mm(float(height), self._unit_system.length)
        self._dimensions_mm = dimensions_mm

        section_id = element.properties.get("section_id")
        if section_id and self._database is not None:
            try:
                self._db_section = self._database.get_section(str(section_id))
            except KeyError:
                self._db_section = None
        else:
            self._db_section = None
        self._is_custom_override = source == "database" and self._db_section is None

        if shape == "User Defined":
            area = element.properties.get("A")
            iy = element.properties.get("I")
            iz = element.properties.get("Iz")
            j = element.properties.get("J")
            length = self._unit_system.length
            if None not in (area, iy, iz, j):
                self._properties = SectionProperties(
                    area_mm2=float(area) * _mm2_per_unit(length),
                    Iy_mm4=float(iy) * _mm4_per_unit(length),
                    Iz_mm4=float(iz) * _mm4_per_unit(length),
                    J_mm4=float(j) * _mm4_per_unit(length),
                )
                self._updating = True
                try:
                    self._property_spinboxes["area"].setValue(float(area))
                    self._property_spinboxes["Iy"].setValue(float(iy))
                    self._property_spinboxes["Iz"].setValue(float(iz))
                    self._property_spinboxes["J"].setValue(float(j))
                finally:
                    self._updating = False
        else:
            self._apply_dimensions_to_spinboxes()
            self._properties = self._safe_compute(shape, dimensions_mm) if dimensions_mm else None
            self._refresh_property_display()

        material_id = element.properties.get("material_id")
        if material_id and self._database is not None:
            category_index = self.material_category_combo.findText(
                str(element.properties.get("material_category", ""))
            )
            if category_index >= 0:
                self.material_category_combo.setCurrentIndex(category_index)
            grade_index = self.material_grade_combo.findData(str(material_id))
            if grade_index >= 0:
                self.material_grade_combo.setCurrentIndex(grade_index)
        elastic = element.properties.get("E")
        density = element.properties.get("density")
        if elastic is not None:
            self.material_e.setValue(float(elastic))
        self.material_unit_weight.setValue(float(density) if density is not None else 0.0)
        self._refresh_preview()

    def clear(self) -> None:
        self.designation_combo.clear()
        self._db_section = None
        self._is_custom_override = False
        self._dimensions_mm = {}
        self._properties = None
        self._refresh_preview()

    # -- apply --------------------------------------------------------------
    def _apply_clicked(self) -> None:
        if self._properties is None:
            return
        self.apply_requested.emit()

    def current_application_kwargs(self) -> dict[str, object]:
        """Everything ``StaticsDrawingCanvas.apply_full_section_to_selection``
        needs, converted from this panel's mm-canonical state into the
        model's own unit system - the canvas mixin itself stays unit-agnostic,
        exactly like the legacy ``apply_section_to_selection``."""
        length = self._unit_system.length
        shape = self.shape_combo.currentText()
        assert self._properties is not None
        dimensions = {
            key: mm_to_length_unit(value, length) for key, value in self._dimensions_mm.items()
        }
        is_database = self.source_database.isChecked() and not self._is_custom_override
        return {
            "shape": shape,
            "source": "database" if is_database else "custom",
            "dimensions": dimensions,
            "area": mm2_to_length_unit(self._properties.area_mm2, length),
            "iy": mm4_to_length_unit(self._properties.Iy_mm4, length),
            "iz": mm4_to_length_unit(self._properties.Iz_mm4, length),
            "j": mm4_to_length_unit(self._properties.J_mm4, length),
            "elastic": self.material_e.value(),
            "density": self.material_unit_weight.value(),
            "section_id": self._db_section.section_id if is_database and self._db_section else None,
            "material_id": self._selected_material.material_id if self._selected_material else None,
            "material_category": self.material_category_combo.currentText() or None,
            "material_grade": self.material_grade_combo.currentText() or None,
        }

    def current_edit_kwargs(self) -> dict[str, object] | None:
        """Same payload as ``current_application_kwargs()``, but ``None``
        instead of asserting when there is nothing valid to apply yet (e.g.
        invalid Custom dimensions, or a freshly selected member that never
        had any section applied at all) - for read-only comparison against a
        selection's actually-stored properties (the Selection Status
        inspector's Applied/Pending Changes check), never for applying
        anything. Checks ``self._properties`` directly (the exact condition
        ``current_application_kwargs()`` asserts) rather than
        ``apply_button.isEnabled()`` - the button's enabled state is not
        always kept in sync for a case that never disabled it to begin with
        (``load_from_element`` on an element with no dimensions at all
        leaves ``_properties`` as ``None`` without touching the button - see
        ``_apply_clicked``, which guards the same way for exactly this
        reason)."""
        if self._properties is None:
            return None
        return self.current_application_kwargs()


def _pow_mm(length_unit: str, power: int) -> float:
    """(1 length_unit)^power expressed in mm^power - the inverse direction of
    ``mm2_to_length_unit``/``mm4_to_length_unit``, needed once for User
    Defined properties (typed directly in the model's own unit, then
    converted into this panel's mm-canonical internal form)."""
    return length_unit_to_mm(1.0, length_unit) ** power


def _mm2_per_unit(length_unit: str) -> float:
    return _pow_mm(length_unit, 2)


def _mm4_per_unit(length_unit: str) -> float:
    return _pow_mm(length_unit, 4)
