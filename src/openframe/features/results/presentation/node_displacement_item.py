"""Marker and value shown at a node's displaced position.

The connector back to the undeformed node is a plain scene-space line drawn by the
viewport, so it lines up with the deformed shape at any zoom. Only this marker keeps a
fixed pixel size, the way node labels elsewhere in the application do.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, UnitSystem
from openframe.features.results.deformation import NodalDisplacement

VECTOR_COLOR = "#b4530a"
PEAK_COLOR = "#e5484d"


class NodeDisplacementItem(QGraphicsItem):
    def __init__(
        self,
        displacement: NodalDisplacement,
        *,
        is_peak: bool = False,
        show_label: bool = True,
        unit_system: UnitSystem = DEFAULT_UNIT_SYSTEM,
    ) -> None:
        super().__init__()
        self.displacement = displacement
        self._is_peak = is_peak
        self._show_label = show_label
        self._font = QFont("Malgun Gothic", 8)
        self._font.setBold(is_peak)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setZValue(9.0)
        self.setData(0, ("result_node_displacement", displacement.node_tag))
        self.set_unit_system(unit_system)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self.unit_system = unit_system
        item = self.displacement
        self.setToolTip(
            f"Node {item.node_tag} | UX={item.ux:.6g} {unit_system.length} | "
            f"UY={item.uy:.6g} {unit_system.length} | "
            f"|U|={item.magnitude:.6g} {unit_system.length}"
        )
        self._label = f"{item.magnitude:.4g} {unit_system.length}"
        self.update()

    def boundingRect(self) -> QRectF:
        width = QFontMetricsF(self._font).horizontalAdvance(self._label) + 20.0
        return QRectF(-8.0, -20.0, width, 32.0)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(PEAK_COLOR if self._is_peak else VECTOR_COLOR)

        radius = 4.0 if self._is_peak else 3.0
        painter.setPen(QPen(color, 1.4))
        painter.setBrush(color)
        painter.drawEllipse(QPointF(0.0, 0.0), radius, radius)

        if not self._show_label:
            return
        painter.setPen(color)
        painter.setFont(self._font)
        painter.drawText(QPointF(radius + 4.0, -radius - 2.0), self._label)
