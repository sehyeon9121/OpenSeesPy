"""Icon glyphs for the canvas-top bar's 지점/노드 유형/하중 icon rows.

Each paint function draws one symbol on a 32x32 logical canvas, deliberately
mirroring the shapes the canvas itself already draws for that entity (see
``features/viewport/items/support_item.py``) so a button's icon and the glyph
placed on the model read as the same symbol, just simplified for icon size.
"""

from typing import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

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
