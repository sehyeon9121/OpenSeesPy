"""Structural model graphics scene and engineering grid."""

import math

from PySide6.QtCore import QObject, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
)

from openframe.core.domain import DEFAULT_UNIT_SYSTEM, StructuralModel, UnitSystem
from openframe.features.viewport.items.nodal_load_item import NodalLoadItem
from openframe.features.viewport.items.node_label_item import NodeLabelItem
from openframe.features.viewport.items.support_item import SupportItem


class StructuralScene(QGraphicsScene):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._unit_system = DEFAULT_UNIT_SYSTEM

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        for item in self.items():
            if isinstance(item, NodalLoadItem):
                item.set_unit_system(unit_system)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#fbfcfe"))
        minor_pen = QPen(QColor("#e9eef5"), 0.0)
        major_pen = QPen(QColor("#dce5f0"), 0.0)
        step = 0.5
        major_every = 5

        left = math.floor(rect.left() / step) * step
        top = math.floor(rect.top() / step) * step
        x = left
        column = round(x / step)
        while x <= rect.right():
            painter.setPen(major_pen if column % major_every == 0 else minor_pen)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
            column += 1

        y = top
        row = round(y / step)
        while y <= rect.bottom():
            painter.setPen(major_pen if row % major_every == 0 else minor_pen)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step
            row += 1

    def set_model(self, model: StructuralModel) -> None:
        self.clear()
        pen = QPen(QColor("#174ea6"), 3.0)
        pen.setCosmetic(True)

        for element in model.elements.values():
            node_i = model.nodes[element.node_i]
            node_j = model.nodes[element.node_j]
            item = QGraphicsLineItem(node_i.x, -node_i.y, node_j.x, -node_j.y)
            item.setPen(pen)
            item.setData(0, ("element", element.tag))
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self.addItem(item)

        for node in model.nodes.values():
            point = QPointF(node.x, -node.y)
            item = QGraphicsEllipseItem(-5.0, -5.0, 10.0, 10.0)
            node_pen = QPen(QColor("#174ea6"), 2.5)
            node_pen.setCosmetic(True)
            item.setPen(node_pen)
            item.setBrush(QColor("#ffffff"))
            item.setPos(point)
            item.setData(0, ("node", node.tag))
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            self.addItem(item)

            label = NodeLabelItem(node.tag)
            label.setPos(point)
            self.addItem(label)

        for boundary in model.boundaries:
            node = model.nodes.get(boundary.node_tag)
            if node is None:
                continue
            support = SupportItem(
                node_tag=boundary.node_tag,
                kind=boundary.support_kind,
                restraints=boundary.restraints,
            )
            support.setPos(node.x, -node.y)
            self.addItem(support)

        loads_by_node: dict[int, list[float]] = {}
        for load in model.nodal_loads:
            accumulated = loads_by_node.setdefault(load.node_tag, [0.0] * max(model.ndf, 3))
            for index, value in enumerate(load.values):
                if index < len(accumulated):
                    accumulated[index] += value

        for node_tag, values in loads_by_node.items():
            node = model.nodes.get(node_tag)
            if node is None:
                continue
            load_item = NodalLoadItem(
                node_tag=node_tag,
                values=tuple(values),
                unit_system=self._unit_system,
            )
            load_item.setPos(node.x, -node.y)
            self.addItem(load_item)
