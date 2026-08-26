"""Icon glyphs for the canvas-top bar's 지점/노드 유형/하중 icon rows.

Each paint function draws one symbol on a 32x32 logical canvas, deliberately
mirroring the shapes the canvas itself already draws for that entity (see
``features/viewport/items/support_item.py``) so a button's icon and the glyph
placed on the model read as the same symbol, just simplified for icon size.
"""

from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

#: (button label, tooltip, glyph key, restraint preset). Restraint presets are always
#: the 2D (Ux, Uy, Rz) triple, matching the combo box they replaced. Only used when
#: ``ModelingInterfacePage._start_in_3d`` is False — 3D uses ``_SUPPORT_OPTIONS_3D``
#: instead (see that tuple for why 2D's presets can't just be reused as-is for 3D).
_SUPPORT_OPTIONS: tuple[tuple[str, str, str, tuple[bool, bool, bool] | None], ...] = (
    ("자유", "자유 (지점 없음)", "free", (False, False, False)),
    ("핀", "핀 지점 (회전 자유)", "pin", (True, True, False)),
    ("수직롤러", "수직 롤러 — 수평(X) 반력만, 수직으로 구름", "roller_v", (True, False, False)),
    ("수평롤러", "수평 롤러 — 수직(Y) 반력만, 수평으로 구름", "roller_h", (False, True, False)),
    ("고정", "고정 지점", "fixed", (True, True, True)),
    ("커스텀", "커스텀 (자유도 직접 지정)", "custom", None),
)

#: 3D's own preset set (6-DOF Ux,Uy,Uz,Rx,Ry,Rz tuples) — kept as MIDAS's raw
#: per-DOF suppression grid (checking Rx/Ry/Rz individually) confuses a first
#: run, so instead of translating 2D's 3-tuples (which used to silently get
#: zero-padded into an unintended partial restraint - see
#: ``BoundaryCondition.support_kind``), every preset here is fully spelled out
#: for 6 DOF up front. 핀/고정 keep 2D's meaning extended the obvious way (핀 =
#: every translation restrained, every rotation free - a ball joint; 고정 = all
#: six restrained). A roller is named for the axis it *slides along* (frees),
#: matching 2D's own "수직/수평롤러" naming-by-rolling-direction convention -
#: everything else about it is exactly a 핀.
_SUPPORT_OPTIONS_3D: tuple[tuple[str, str, str, tuple[bool, ...] | None], ...] = (
    ("자유", "자유 (지점 없음)", "free", (False,) * 6),
    ("핀", "핀 지점 — 이동 3방향 구속, 회전은 어느 방향이든 자유", "pin", (True, True, True, False, False, False)),
    ("고정", "고정 지점 — 이동·회전 6자유도 전부 구속", "fixed", (True,) * 6),
    ("X 롤러", "핀인데 X방향으로만 미끄러짐 (Ux 자유, 나머지 핀과 동일)", "roller_x", (False, True, True, False, False, False)),
    ("Y 롤러", "핀인데 Y방향으로만 미끄러짐 (Uy 자유, 나머지 핀과 동일)", "roller_y", (True, False, True, False, False, False)),
    ("Z 롤러", "핀인데 Z방향으로만 미끄러짐 (Uz 자유, 나머지 핀과 동일)", "roller_z", (True, True, False, False, False, False)),
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
    if key in ("roller_x", "roller_y", "roller_z"):
        # Same wheeled-triangle silhouette as roller_h ("this rolls"), plus a
        # bold axis letter where roller_h leaves the triangle blank - the
        # letter is what a single shared "roller" glyph can't otherwise say,
        # and it renders correctly in both the icon pipeline's Off/On colors
        # since it uses the same single `color` pen as everything else here.
        triangle = QPainterPath()
        triangle.moveTo(16, 4)
        triangle.lineTo(7, 16)
        triangle.lineTo(25, 16)
        triangle.closeSubpath()
        painter.drawPath(triangle)
        painter.drawEllipse(QRectF(8.0, 17.0, 6.0, 6.0))
        painter.drawEllipse(QRectF(18.0, 17.0, 6.0, 6.0))
        painter.drawLine(5, 25, 27, 25)
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(9)
        painter.setFont(font)
        letter = {"roller_x": "X", "roller_y": "Y", "roller_z": "Z"}[key]
        painter.drawText(QRectF(9.0, 6.0, 14.0, 9.0), Qt.AlignmentFlag.AlignCenter, letter)
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


def _paint_ribbon_glyph(painter: QPainter, key: str, color: str) -> None:
    """The 3D 워크벤치 리본's 선택/Node/Member/Arch/복사/삭제/층·그리드/3D뷰 icons —
    plain line-art on the same 32x32 canvas as every other glyph here, so the
    ribbon needed no bundled icon font (Material Symbols et al.) for eight
    buttons."""
    if key == "select":
        pointer = QPainterPath()
        pointer.moveTo(8, 4)
        pointer.lineTo(8, 26)
        pointer.lineTo(13, 21)
        pointer.lineTo(17, 28)
        pointer.lineTo(20, 26)
        pointer.lineTo(16, 19)
        pointer.lineTo(23, 19)
        pointer.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(pointer)
        return
    if key == "node":
        painter.drawEllipse(QRectF(6.0, 9.0, 14.0, 14.0))
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(10.5, 13.5, 5.0, 5.0))
        painter.drawLine(24, 4, 24, 12)
        painter.drawLine(20, 8, 28, 8)
        return
    if key == "member":
        painter.drawLine(7, 25, 25, 7)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(4.0, 22.0, 6.0, 6.0))
        painter.drawEllipse(QRectF(22.0, 4.0, 6.0, 6.0))
        return
    if key == "arch":
        painter.drawLine(5, 26, 27, 26)
        curve = QPainterPath()
        curve.moveTo(6, 24)
        curve.cubicTo(6, 6, 26, 6, 26, 24)
        painter.drawPath(curve)
        return
    if key == "copy":
        painter.drawRect(QRectF(12.0, 4.0, 14.0, 16.0))
        painter.drawRect(QRectF(6.0, 12.0, 14.0, 16.0))
        return
    if key == "delete":
        painter.drawLine(12, 5, 20, 5)
        painter.drawLine(12, 5, 12, 9)
        painter.drawLine(20, 5, 20, 9)
        painter.drawLine(7, 9, 25, 9)
        basket = QPainterPath()
        basket.moveTo(9, 9)
        basket.lineTo(11, 27)
        basket.lineTo(21, 27)
        basket.lineTo(23, 9)
        painter.drawPath(basket)
        painter.drawLine(14, 13, 14, 23)
        painter.drawLine(18, 13, 18, 23)
        return
    if key == "levels":
        painter.drawLine(5, 7, 27, 7)
        painter.drawLine(5, 16, 27, 16)
        painter.drawLine(5, 25, 27, 25)
        return
    # view3d: an isometric cube outline, 3 spokes from centre to alternating
    # vertices giving it the usual "visible 3 faces" cube reading.
    hexagon = QPainterPath()
    vertices = ((16, 4), (28, 10), (28, 22), (16, 28), (4, 22), (4, 10))
    hexagon.moveTo(*vertices[0])
    for x, y in vertices[1:]:
        hexagon.lineTo(x, y)
    hexagon.closeSubpath()
    painter.drawPath(hexagon)
    painter.drawLine(16, 16, 16, 4)
    painter.drawLine(16, 16, 28, 22)
    painter.drawLine(16, 16, 4, 22)


#: (DOF name, "translation"/"rotation", axis color) for the custom 지점
#: checkbox grid's legend row - reuses the same X/Y/Z color triad as the
#: canvas's own axis lines (drawBackground: X red, Y green) and the 3D local-
#: axis gizmo (z pink), so "which color means which axis" is one language
#: across the whole app instead of a new mapping to learn here.
DOF_LEGEND: tuple[tuple[str, str, str], ...] = (
    ("Ux", "translation", "#dc2626"),
    ("Uy", "translation", "#16a34a"),
    ("Uz", "translation", "#ec4899"),
    ("Rx", "rotation", "#dc2626"),
    ("Ry", "rotation", "#16a34a"),
    ("Rz", "rotation", "#ec4899"),
)


def _paint_dof_icon(painter: QPainter, kind: str, color: str) -> None:
    """20x20 icon: a double-headed arrow for a translation DOF (moves back
    and forth along a line), a looping arrow for a rotation DOF (spins about
    an axis) - the same distinction checking that box actually makes."""
    pen = QPen(QColor(color), 2.0)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    if kind == "translation":
        painter.drawLine(2, 10, 18, 10)
        painter.drawLine(2, 10, 6, 6)
        painter.drawLine(2, 10, 6, 14)
        painter.drawLine(18, 10, 14, 6)
        painter.drawLine(18, 10, 14, 14)
        return
    painter.drawArc(QRectF(2.0, 2.0, 16.0, 16.0), 20 * 16, 300 * 16)
    painter.drawLine(16, 4, 19, 7)
    painter.drawLine(16, 4, 13, 6)


def _render_dof_icon(kind: str, color: str, size: int = 20) -> QPixmap:
    """A standalone (not Off/On-paired) pixmap for ``_paint_dof_icon`` -
    the DOF legend needs a distinct color per axis, which the checkable-
    button icon pipeline below (``_render_glyph_icon``, exactly two fixed
    colors) was never built to carry."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _paint_dof_icon(painter, kind, color)
    painter.end()
    return pixmap


#: Direct Loads' MIDAS-style static reference diagrams (see
#: _build_load_bar_content's "command_driven" 3D path) - unlike every other
#: glyph in this file these are not tied to the actual model geometry or
#: typed-in values, only to which load *kind* is currently selected. Purely
#: illustrative, same as MIDAS' own Nodal Loads/Element Beam Loads dialogs.
_LOAD_DIAGRAM_SIZE = (160, 120)


def _paint_arrowhead(painter: QPainter, tip, back1, back2) -> None:
    painter.drawLine(tip, back1)
    painter.drawLine(tip, back2)


def _paint_nodal_load_diagram(painter: QPainter, color: str) -> None:
    """Origin node + FX/FY/FZ straight arrows and MX/MY/MZ curved arrows on
    a simple 3-axis triad (Z up, Y right, X toward lower-left) - the same
    layout MIDAS' own "Nodal Loads" dialog draws."""
    origin = QPointF(55.0, 85.0)
    pen = QPen(QColor(color), 1.6)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    font = QFont()
    font.setPointSizeF(7.5)
    painter.setFont(font)

    painter.setBrush(QColor("#f59e0b"))
    painter.drawEllipse(origin, 3.5, 3.5)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # Straight force arrows: FZ up, FY right, FX toward lower-left.
    fz_tip = QPointF(55.0, 15.0)
    painter.drawLine(origin, fz_tip)
    _paint_arrowhead(painter, fz_tip, QPointF(51.0, 22.0), QPointF(59.0, 22.0))
    painter.drawText(QPointF(60.0, 18.0), "FZ")

    fy_tip = QPointF(120.0, 85.0)
    painter.drawLine(origin, fy_tip)
    _paint_arrowhead(painter, fy_tip, QPointF(112.0, 81.0), QPointF(112.0, 89.0))
    painter.drawText(QPointF(122.0, 89.0), "FY")

    fx_tip = QPointF(15.0, 108.0)
    painter.drawLine(origin, fx_tip)
    _paint_arrowhead(painter, fx_tip, QPointF(23.0, 103.0), QPointF(19.0, 111.0))
    painter.drawText(QPointF(2.0, 112.0), "FX")

    # Curved moment arrows: a short arc plus arrowhead near each axis.
    painter.drawArc(QRectF(35.0, 30.0, 24.0, 24.0), 30 * 16, 220 * 16)
    _paint_arrowhead(painter, QPointF(37.0, 42.0), QPointF(41.0, 37.0), QPointF(43.0, 46.0))
    painter.drawText(QPointF(10.0, 40.0), "MX")

    painter.drawArc(QRectF(65.0, 45.0, 24.0, 24.0), 60 * 16, 220 * 16)
    _paint_arrowhead(painter, QPointF(75.0, 68.0), QPointF(70.0, 65.0), QPointF(76.0, 60.0))
    painter.drawText(QPointF(95.0, 68.0), "MY")

    painter.drawArc(QRectF(20.0, 60.0, 24.0, 24.0), 300 * 16, 220 * 16)
    _paint_arrowhead(painter, QPointF(37.0, 79.0), QPointF(29.0, 79.0), QPointF(35.0, 72.0))
    painter.drawText(QPointF(15.0, 62.0), "MZ")


def _paint_uniform_load_diagram(painter: QPainter, color: str) -> None:
    """N1-N2 member line with evenly spaced downward arrows (w) and x1/x2
    span markers - the same layout MIDAS' own "Element/Line Beam Loads"
    dialog draws for a Uniform Loads type."""
    pen = QPen(QColor(color), 1.6)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    font = QFont()
    font.setPointSizeF(7.5)
    painter.setFont(font)

    n1 = QPointF(20.0, 75.0)
    n2 = QPointF(140.0, 75.0)
    painter.drawLine(n1, n2)
    painter.setBrush(QColor("#f59e0b"))
    painter.drawEllipse(n1, 3.5, 3.5)
    painter.drawEllipse(n2, 3.5, 3.5)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawText(QPointF(10.0, 92.0), "N1")
    painter.drawText(QPointF(132.0, 92.0), "N2")

    top = 30.0
    for x in range(30, 131, 20):
        tip = QPointF(float(x), 75.0)
        painter.drawLine(QPointF(float(x), top), tip)
        _paint_arrowhead(painter, tip, QPointF(x - 3.0, 68.0), QPointF(x + 3.0, 68.0))
    painter.drawLine(QPointF(20.0, top), QPointF(140.0, top))
    painter.drawText(QPointF(142.0, top + 4.0), "w")

    painter.drawText(QPointF(15.0, 108.0), "x1")
    painter.drawText(QPointF(130.0, 108.0), "x2")


def _render_load_diagram(kind: str, color: str = "#415269") -> QPixmap:
    """``kind`` is ``"node"`` or ``"element"`` - matches
    ``ModelingInterfacePage._current_load_target()``'s own values for the
    two commands this currently covers (Nodal Load, Mem Uniform)."""
    width, height = _LOAD_DIAGRAM_SIZE
    pixmap = QPixmap(width * 2, height * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if kind == "node":
        _paint_nodal_load_diagram(painter, color)
    else:
        _paint_uniform_load_diagram(painter, color)
    painter.end()
    return pixmap


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
