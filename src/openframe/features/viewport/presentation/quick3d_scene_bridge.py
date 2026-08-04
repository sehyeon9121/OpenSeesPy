"""Convert structural-domain objects into renderer-neutral Qt Quick 3D data."""

import math

from PySide6.QtCore import Property, QObject, Signal

from openframe.core.domain import StructuralModel


class Quick3DSceneBridge(QObject):
    scene_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nodes: list[dict[str, float | int]] = []
        self._members: list[dict[str, float | int]] = []
        self._center = (0.0, 0.0, 0.0)
        self._extent = 1.0
        self._ground_y = 0.0
        self._ground_width = 1.0
        self._ground_depth = 1.0

    def set_model(self, model: StructuralModel) -> None:
        if not model.nodes:
            self._clear()
            return

        points = {
            tag: self._view_coordinates(node.x, node.y, node.z)
            for tag, node in model.nodes.items()
        }
        x_values = [point[0] for point in points.values()]
        y_values = [point[1] for point in points.values()]
        z_values = [point[2] for point in points.values()]
        spans = (
            max(x_values) - min(x_values),
            max(y_values) - min(y_values),
            max(z_values) - min(z_values),
        )
        self._extent = max(*spans, 1.0)
        default_thickness = max(self._extent * 0.012, 0.025)
        node_radius = default_thickness * 0.72

        self._center = (
            0.5 * (min(x_values) + max(x_values)),
            0.5 * (min(y_values) + max(y_values)),
            0.5 * (min(z_values) + max(z_values)),
        )
        self._ground_y = min(y_values) - self._extent * 0.025
        self._ground_width = max(spans[0] + self._extent * 0.35, self._extent * 0.5)
        self._ground_depth = max(spans[2] + self._extent * 0.35, self._extent * 0.5)

        self._nodes = [
            {
                "tag": tag,
                "x": point[0],
                "y": point[1],
                "z": point[2],
                "radius": node_radius,
            }
            for tag, point in sorted(points.items())
        ]
        self._members = []
        for element in sorted(model.elements.values(), key=lambda item: item.tag):
            start = points.get(element.node_i)
            end = points.get(element.node_j)
            if start is None or end is None:
                continue
            delta = tuple(end[index] - start[index] for index in range(3))
            length = math.sqrt(sum(value * value for value in delta))
            if length <= 1.0e-12:
                continue
            direction = tuple(value / length for value in delta)
            scalar, qx, qy, qz = self._rotation_from_y_axis(direction)
            area = self._number_property(element.properties, "A")
            section_size = math.sqrt(area) if area is not None and area > 0.0 else 0.0
            thickness = min(
                max(section_size, default_thickness),
                self._extent * 0.055,
            )
            self._members.append(
                {
                    "tag": element.tag,
                    "x": 0.5 * (start[0] + end[0]),
                    "y": 0.5 * (start[1] + end[1]),
                    "z": 0.5 * (start[2] + end[2]),
                    "length": length,
                    "thickness": thickness,
                    "qscalar": scalar,
                    "qx": qx,
                    "qy": qy,
                    "qz": qz,
                }
            )
        self.scene_changed.emit()

    @Property("QVariantList", notify=scene_changed)
    def nodes(self) -> list[dict[str, float | int]]:
        return self._nodes

    @Property("QVariantList", notify=scene_changed)
    def members(self) -> list[dict[str, float | int]]:
        return self._members

    @Property(float, notify=scene_changed)
    def center_x(self) -> float:
        return self._center[0]

    @Property(float, notify=scene_changed)
    def center_y(self) -> float:
        return self._center[1]

    @Property(float, notify=scene_changed)
    def center_z(self) -> float:
        return self._center[2]

    @Property(float, notify=scene_changed)
    def extent(self) -> float:
        return self._extent

    @Property(float, notify=scene_changed)
    def ground_y(self) -> float:
        return self._ground_y

    @Property(float, notify=scene_changed)
    def ground_width(self) -> float:
        return self._ground_width

    @Property(float, notify=scene_changed)
    def ground_depth(self) -> float:
        return self._ground_depth

    def _clear(self) -> None:
        self._nodes = []
        self._members = []
        self._center = (0.0, 0.0, 0.0)
        self._extent = 1.0
        self._ground_y = 0.0
        self._ground_width = 1.0
        self._ground_depth = 1.0
        self.scene_changed.emit()

    @staticmethod
    def _view_coordinates(x: float, y: float, z: float) -> tuple[float, float, float]:
        # Qt Quick 3D uses +Y as up. Structural +Z is therefore mapped to view +Y.
        return float(x), float(z), -float(y)

    @staticmethod
    def _rotation_from_y_axis(
        direction: tuple[float, float, float],
    ) -> tuple[float, float, float, float]:
        dx, dy, dz = direction
        dot = max(-1.0, min(1.0, dy))
        if dot < -0.999999:
            return 0.0, 1.0, 0.0, 0.0
        scale = math.sqrt(2.0 * (1.0 + dot))
        return 0.5 * scale, dz / scale, 0.0, -dx / scale

    @staticmethod
    def _number_property(
        properties: dict[str, float | str], key: str
    ) -> float | None:
        value = properties.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
