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
from openframe.features.viewport.items.element_label_item import ElementLabelItem
from openframe.features.viewport.items.nodal_load_item import (
    LOAD_CASE_COLORS,
    NodalLoadItem,
)
from openframe.features.viewport.items.node_label_item import NodeLabelItem
from openframe.features.viewport.items.support_item import SupportItem
from openframe.features.viewport.items.uniform_element_load_item import (
    UniformElementLoadItem,
)


class StructuralScene(QGraphicsScene):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._unit_system = DEFAULT_UNIT_SYSTEM
        self._model: StructuralModel | None = None
        self._projection = "xy"
        self._yaw_degrees = 0.0
        self._elevation_degrees = -90.0

    @property
    def projection(self) -> str:
        return self._projection

    @property
    def camera_angles(self) -> tuple[float, float]:
        return self._yaw_degrees, self._elevation_degrees

    def set_projection(self, projection: str) -> None:
        if projection not in {"iso", "xy", "xz", "yz"}:
            raise ValueError(f"Unknown projection: {projection}")
        self._projection = projection
        self._yaw_degrees, self._elevation_degrees = {
            "iso": (45.0, 30.0),
            "xy": (0.0, -90.0),
            "xz": (0.0, 0.0),
            "yz": (-90.0, 0.0),
        }[projection]
        if self._model is not None:
            self.set_model(self._model)

    def orbit(self, delta_x: float, delta_y: float, *, redraw: bool = True) -> None:
        """Rotate the orthographic camera from a middle-mouse drag."""
        self._yaw_degrees = (self._yaw_degrees + delta_x * 0.45) % 360.0
        self._elevation_degrees = max(
            -89.0,
            min(89.0, self._elevation_degrees - delta_y * 0.35),
        )
        self._projection = "free"
        if redraw and self._model is not None:
            self.set_model(self._model)

    def project_coordinates(self, x: float, y: float, z: float = 0.0) -> QPointF:
        """Project a model-space point onto the existing 2D graphics scene."""
        yaw = math.radians(self._yaw_degrees)
        elevation = math.radians(self._elevation_degrees)
        cosine_yaw = math.cos(yaw)
        sine_yaw = math.sin(yaw)
        sine_elevation = math.sin(elevation)
        cosine_elevation = math.cos(elevation)
        screen_x = x * cosine_yaw - y * sine_yaw
        screen_y = (
            x * sine_yaw * sine_elevation + y * cosine_yaw * sine_elevation - z * cosine_elevation
        )
        return QPointF(screen_x, screen_y)

    def set_unit_system(self, unit_system: UnitSystem) -> None:
        self._unit_system = unit_system
        for item in self.items():
            if isinstance(item, (NodalLoadItem, UniformElementLoadItem)):
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
        self._model = model
        self.clear()
        pen = QPen(QColor("#174ea6"), 3.0)
        pen.setCosmetic(True)

        for element in model.elements.values():
            node_i = model.nodes[element.node_i]
            node_j = model.nodes[element.node_j]
            start = self.project_coordinates(node_i.x, node_i.y, node_i.z)
            end = self.project_coordinates(node_j.x, node_j.y, node_j.z)
            item = QGraphicsLineItem(start.x(), start.y(), end.x(), end.y())
            item.setPen(pen)
            item.setData(0, ("element", element.tag))
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self.addItem(item)

            element_label = ElementLabelItem(element.tag)
            element_label.setPos((start.x() + end.x()) / 2.0, (start.y() + end.y()) / 2.0)
            # Off by default everywhere this scene is used (the imported-model
            # viewer has no filter checkbox for it yet, and a frame result view
            # is already dense with diagram labels) — ResultViewport turns it on
            # itself for a truss result, where 부재 번호 is exactly what's needed.
            element_label.setVisible(False)
            self.addItem(element_label)

        for node in model.nodes.values():
            point = self.project_coordinates(node.x, node.y, node.z)
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
            support.setPos(self.project_coordinates(node.x, node.y, node.z))
            self.addItem(support)

        loads_by_node: dict[tuple[int, object, int | None], list[float]] = {}
        for load in model.nodal_loads:
            key = (load.node_tag, load.case_type, load.pattern_tag)
            accumulated = loads_by_node.setdefault(key, [0.0] * max(model.ndf, 3))
            for index, value in enumerate(load.values):
                if index < len(accumulated):
                    accumulated[index] += value

        maximum_nodal_magnitude = max(
            (
                math.sqrt(sum(value * value for value in values[:3]))
                for values in loads_by_node.values()
            ),
            default=0.0,
        )

        for (node_tag, case_type, pattern_tag), values in loads_by_node.items():
            node = model.nodes.get(node_tag)
            if node is None:
                continue
            point = self.project_coordinates(node.x, node.y, node.z)
            if model.ndm == 3:
                load_item = QGraphicsEllipseItem(-5.0, -5.0, 10.0, 10.0)
                color = QColor(LOAD_CASE_COLORS[case_type])
                load_item.setPen(QPen(color.darker(120), 2.0))
                load_item.setBrush(color)
                load_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                load_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                load_item.setData(0, ("load", node_tag))
                names = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")
                components = ", ".join(
                    f"{name}={value:g}" for name, value in zip(names, values, strict=False)
                )
                load_item.setToolTip(
                    f"{case_type.value} | Pattern {pattern_tag or '-'} | "
                    f"Node {node_tag} | {components}"
                )
            else:
                load_item = NodalLoadItem(
                    node_tag=node_tag,
                    values=tuple(values),
                    unit_system=self._unit_system,
                    load_scale=self._load_scale(
                        math.sqrt(sum(value * value for value in values[:3])),
                        maximum_nodal_magnitude,
                    ),
                    case_type=case_type,
                    pattern_tag=pattern_tag,
                )
            load_item.setData(1, case_type.value)
            load_item.setPos(point)
            self.addItem(load_item)

        maximum_element_magnitude = max(
            (
                math.sqrt(load.wx * load.wx + load.wy * load.wy + load.wz * load.wz)
                for load in model.element_loads
            ),
            default=0.0,
        )
        for load in model.element_loads:
            element = model.elements.get(load.element_tag)
            if element is None:
                continue
            node_i = model.nodes.get(element.node_i)
            node_j = model.nodes.get(element.node_j)
            if node_i is None or node_j is None:
                continue
            load_item = UniformElementLoadItem(
                load=load,
                start=self.project_coordinates(node_i.x, node_i.y, node_i.z),
                end=self.project_coordinates(node_j.x, node_j.y, node_j.z),
                unit_system=self._unit_system,
                load_scale=self._load_scale(
                    math.sqrt(load.wx * load.wx + load.wy * load.wy + load.wz * load.wz),
                    maximum_element_magnitude,
                ),
            )
            load_item.setData(1, load.case_type.value)
            self.addItem(load_item)

        if model.ndm == 3:
            self._draw_axes(model)

    @staticmethod
    def _load_scale(magnitude: float, maximum_magnitude: float) -> float:
        if magnitude <= 0.0 or maximum_magnitude <= 0.0:
            return 0.45
        return 0.45 + 0.55 * math.sqrt(min(magnitude / maximum_magnitude, 1.0))

    def _draw_axes(self, model: StructuralModel) -> None:
        if not model.nodes:
            return
        coordinates = [
            component for node in model.nodes.values() for component in (node.x, node.y, node.z)
        ]
        axis_length = max((max(coordinates) - min(coordinates)) * 0.2, 1.0)
        origin = self.project_coordinates(0.0, 0.0, 0.0)
        axes = (
            ("X", self.project_coordinates(axis_length, 0.0, 0.0), QColor("#d33f49")),
            ("Y", self.project_coordinates(0.0, axis_length, 0.0), QColor("#238636")),
            ("Z", self.project_coordinates(0.0, 0.0, axis_length), QColor("#2468b4")),
        )
        for name, endpoint, color in axes:
            pen = QPen(color, 2.0)
            pen.setCosmetic(True)
            line = self.addLine(origin.x(), origin.y(), endpoint.x(), endpoint.y(), pen)
            line.setData(0, ("axis", name))
            label = self.addText(name)
            label.setDefaultTextColor(color)
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            label.setPos(endpoint)
            label.setData(0, ("axis", name))
