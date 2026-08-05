"""Convert structural-domain objects into renderer-neutral Qt Quick 3D data."""

import math

from PySide6.QtCore import Property, QObject, Signal

from openframe.core.domain import AnalysisResult, Element, LoadCaseKind, StructuralModel

#: Blue -> yellow -> red stops, matching
#: features/results/presentation/result_color_scale.py's palette so the 2D result
#: legend and this 3D view read as the same scale.
_COLOR_STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (37, 99, 235)),  # #2563eb
    (0.5, (247, 209, 84)),  # #f7d154
    (1.0, (229, 72, 77)),  # #e5484d
)

_DEFAULT_NODE_COLOR = "#2877b7"
_DEFAULT_MEMBER_COLOR = "#647789"
_GHOST_COLOR = "#c9cfd6"
_GHOST_OPACITY = 0.35
_NODAL_FORCE_COLOR = "#e5484d"
_UNIFORM_TRANSVERSE_COLOR = "#f59e0b"
_UNIFORM_AXIAL_COLOR = "#8b5cf6"
_LOAD_CASE_COLORS = {
    LoadCaseKind.DEAD: "#2563eb",
    LoadCaseKind.LIVE: "#16a34a",
    LoadCaseKind.SEISMIC: "#f97316",
    LoadCaseKind.WIND: "#8b5cf6",
    LoadCaseKind.OTHER: "#64748b",
    LoadCaseKind.UNCLASSIFIED: "#e5484d",
}
#: Picked-node highlight. Bright cyan sits outside the blue-yellow-red displacement
#: ramp and the load-arrow reds/oranges/purples, so it reads as "selected" regardless
#: of what colour the node would otherwise have.
_SELECTED_NODE_COLOR = "#00e5ff"
_SELECTED_NODE_RADIUS_SCALE = 1.6


def _color_for_ratio(ratio: float) -> str:
    """Hex colour at ``ratio`` (0..1) along the shared blue-to-red scale.

    Reimplemented locally instead of importing result_color_scale.color_for_ratio
    because features.results already imports features.viewport (for the shared 2D
    scene widgets); importing back would create a features<->features cycle.
    """
    position = min(1.0, max(0.0, ratio))
    for index in range(len(_COLOR_STOPS) - 1):
        low_position, low_color = _COLOR_STOPS[index]
        high_position, high_color = _COLOR_STOPS[index + 1]
        if position > high_position:
            continue
        span = high_position - low_position
        blend = 0.0 if span <= 0.0 else (position - low_position) / span
        red, green, blue = (
            round(low + (high - low) * blend)
            for low, high in zip(low_color, high_color, strict=True)
        )
        return f"#{red:02x}{green:02x}{blue:02x}"
    red, green, blue = _COLOR_STOPS[-1][1]
    return f"#{red:02x}{green:02x}{blue:02x}"


class Quick3DSceneBridge(QObject):
    scene_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nodes: list[dict[str, float | int | str]] = []
        self._members: list[dict[str, float | int | str]] = []
        self._ghost_nodes: list[dict[str, float | int | str]] = []
        self._ghost_members: list[dict[str, float | int | str]] = []
        self._load_arrows: list[dict[str, float | int | str]] = []
        self._loads_visible = True
        self._load_filter = "all"
        self._load_case_filter = "all"
        self._center = (0.0, 0.0, 0.0)
        self._extent = 1.0
        self._ground_y = 0.0
        self._ground_width = 1.0
        self._ground_depth = 1.0
        self._points: dict[int, tuple[float, float, float]] = {}
        self._default_thickness = 0.025
        self._node_radius = 0.018
        self._last_model: StructuralModel | None = None
        self._selected_node_tag: int | None = None

    def set_model(self, model: StructuralModel) -> None:
        self._last_model = model
        self._selected_node_tag = None
        if not model.nodes:
            self._clear()
            return

        points = {
            tag: self._view_coordinates(node.x, node.y, node.z) for tag, node in model.nodes.items()
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
        self._default_thickness = max(self._extent * 0.012, 0.025)
        self._node_radius = self._default_thickness * 0.72

        self._center = (
            0.5 * (min(x_values) + max(x_values)),
            0.5 * (min(y_values) + max(y_values)),
            0.5 * (min(z_values) + max(z_values)),
        )
        self._ground_y = min(y_values) - self._extent * 0.025
        self._ground_width = max(spans[0] + self._extent * 0.35, self._extent * 0.5)
        self._ground_depth = max(spans[2] + self._extent * 0.35, self._extent * 0.5)

        self._points = points
        self._rebuild_default_geometry(model)
        self._ghost_nodes = []
        self._ghost_members = []
        self._load_arrows = self._build_all_load_arrows(model, points)
        self.scene_changed.emit()

    def set_result(
        self,
        model: StructuralModel,
        result: AnalysisResult,
        scale: float,
        show_undeformed: bool,
    ) -> None:
        """Overlay analysis displacements: deformed + colour-mapped geometry, an
        optional translucent undeformed ghost, and arrows at loaded nodes."""
        if not self._points:
            return
        self._last_model = model

        magnitudes: dict[int, float] = {}
        deformed_points: dict[int, tuple[float, float, float]] = {}
        for tag, base_point in self._points.items():
            node_result = result.node_results.get(tag)
            displacement = node_result.displacement if node_result is not None else ()
            padded = (*displacement, 0.0, 0.0, 0.0)
            ux, uy, uz = padded[0], padded[1], padded[2]
            magnitudes[tag] = math.sqrt(ux * ux + uy * uy + uz * uz)
            offset = self._view_coordinates(ux, uy, uz)
            deformed_points[tag] = tuple(
                base_point[index] + offset[index] * scale for index in range(3)
            )

        peak = max(magnitudes.values(), default=0.0)
        ratios = {
            tag: 0.0 if peak <= 1.0e-12 else magnitude / peak
            for tag, magnitude in magnitudes.items()
        }

        self._nodes = [
            {
                "tag": tag,
                "x": point[0],
                "y": point[1],
                "z": point[2],
                "radius": self._node_radius,
                "color": _color_for_ratio(ratios.get(tag, 0.0)),
                "opacity": 1.0,
            }
            for tag, point in sorted(deformed_points.items())
        ]

        members: list[dict[str, float | int | str]] = []
        for element in sorted(model.elements.values(), key=lambda item: item.tag):
            ratio = 0.5 * (ratios.get(element.node_i, 0.0) + ratios.get(element.node_j, 0.0))
            entry = self._member_entry(
                element,
                deformed_points,
                self._default_thickness,
                color=_color_for_ratio(ratio),
            )
            if entry is not None:
                members.append(entry)
        self._members = members

        if show_undeformed:
            self._ghost_nodes = [
                {
                    "tag": tag,
                    "x": point[0],
                    "y": point[1],
                    "z": point[2],
                    "radius": self._node_radius,
                    "color": _GHOST_COLOR,
                    "opacity": _GHOST_OPACITY,
                }
                for tag, point in sorted(self._points.items())
            ]
            ghost_members: list[dict[str, float | int | str]] = []
            for element in sorted(model.elements.values(), key=lambda item: item.tag):
                entry = self._member_entry(
                    element,
                    self._points,
                    self._default_thickness,
                    color=_GHOST_COLOR,
                    opacity=_GHOST_OPACITY,
                )
                if entry is not None:
                    ghost_members.append(entry)
            self._ghost_members = ghost_members
        else:
            self._ghost_nodes = []
            self._ghost_members = []

        self._load_arrows = self._build_all_load_arrows(model, deformed_points)
        self.scene_changed.emit()

    def clear_result(self) -> None:
        """Drop the result overlay and go back to the plain undeformed model."""
        self._ghost_nodes = []
        self._ghost_members = []
        if self._last_model is not None and self._points:
            self._rebuild_default_geometry(self._last_model)
            self._load_arrows = self._build_all_load_arrows(self._last_model, self._points)
        self.scene_changed.emit()

    def set_loads_visible(self, visible: bool) -> None:
        self._loads_visible = visible
        self.scene_changed.emit()

    def set_load_filter(self, load_filter: str) -> None:
        if load_filter not in {"all", "nodal", "element"}:
            return
        self._load_filter = load_filter
        self.scene_changed.emit()

    def set_load_case_filter(self, case_filter: str) -> None:
        self._load_case_filter = case_filter
        self.scene_changed.emit()

    def set_selected_node(self, tag: int | None) -> None:
        self._selected_node_tag = tag
        self.scene_changed.emit()

    @Property("QVariantList", notify=scene_changed)
    def nodes(self) -> list[dict[str, float | int | str]]:
        if self._selected_node_tag is None:
            return self._nodes
        # A picked node is highlighted here rather than baked into `_nodes` at build
        # time, so the highlight survives whatever set_result()/clear_result() next
        # rebuilds `_nodes` with (deformation scale changes, undeformed toggle, ...).
        highlighted = []
        for node in self._nodes:
            if node["tag"] == self._selected_node_tag:
                node = dict(node)
                node["color"] = _SELECTED_NODE_COLOR
                node["radius"] = node["radius"] * _SELECTED_NODE_RADIUS_SCALE
            highlighted.append(node)
        return highlighted

    @Property("QVariantList", notify=scene_changed)
    def members(self) -> list[dict[str, float | int | str]]:
        return self._members

    @Property("QVariantList", notify=scene_changed)
    def ghostNodes(self) -> list[dict[str, float | int | str]]:
        return self._ghost_nodes

    @Property("QVariantList", notify=scene_changed)
    def ghostMembers(self) -> list[dict[str, float | int | str]]:
        return self._ghost_members

    @Property("QVariantList", notify=scene_changed)
    def loadArrows(self) -> list[dict[str, float | int | str]]:
        if not self._loads_visible:
            return []
        return [
            part
            for part in self._load_arrows
            if (self._load_filter == "all" or part["kind"] == self._load_filter)
            and (self._load_case_filter == "all" or part["case_type"] == self._load_case_filter)
        ]

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

    def _rebuild_default_geometry(self, model: StructuralModel) -> None:
        self._nodes = [
            {
                "tag": tag,
                "x": point[0],
                "y": point[1],
                "z": point[2],
                "radius": self._node_radius,
                "color": _DEFAULT_NODE_COLOR,
                "opacity": 1.0,
            }
            for tag, point in sorted(self._points.items())
        ]
        members: list[dict[str, float | int | str]] = []
        for element in sorted(model.elements.values(), key=lambda item: item.tag):
            entry = self._member_entry(
                element,
                self._points,
                self._default_thickness,
                color=_DEFAULT_MEMBER_COLOR,
            )
            if entry is not None:
                members.append(entry)
        self._members = members

    def _member_entry(
        self,
        element: Element,
        points: dict[int, tuple[float, float, float]],
        default_thickness: float,
        *,
        color: str,
        opacity: float = 1.0,
    ) -> dict[str, float | int | str] | None:
        start = points.get(element.node_i)
        end = points.get(element.node_j)
        if start is None or end is None:
            return None
        orientation = self._member_orientation(start, end)
        if orientation is None:
            return None
        length, scalar, qx, qy, qz = orientation
        area = self._number_property(element.properties, "A")
        section_size = math.sqrt(area) if area is not None and area > 0.0 else 0.0
        thickness = min(
            max(section_size, default_thickness),
            self._extent * 0.055,
        )
        return {
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
            "color": color,
            "opacity": opacity,
        }

    def _build_load_arrows(
        self,
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
    ) -> list[dict[str, float | int | str]]:
        """One shaft part + one head part per non-zero nodal load, each placed and
        rotated independently at its own midpoint (the scheme _member_entry already
        uses), so shaft and head always meet exactly with no parent/child offset math.
        """
        magnitudes = [
            math.sqrt(sum(value * value for value in (*load.values[:3], 0.0, 0.0)[:3]))
            for load in model.nodal_loads
        ]
        maximum_magnitude = max(magnitudes, default=0.0)

        parts: list[dict[str, float | int | str]] = []
        for load in model.nodal_loads:
            anchor = points.get(load.node_tag)
            if anchor is None:
                continue
            padded = (*load.values, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            fx, fy, fz = padded[0], padded[1], padded[2]
            magnitude = math.sqrt(fx * fx + fy * fy + fz * fz)
            if magnitude <= 1.0e-12:
                continue
            scale = self._load_scale(magnitude, maximum_magnitude)
            arrow_length = max(self._extent * 0.17, 0.06) * scale
            shaft_length = arrow_length * 0.68
            head_length = arrow_length - shaft_length
            shaft_thickness = max(self._default_thickness * 0.55, 0.009)
            head_thickness = shaft_thickness * 2.25
            direction_model = (fx / magnitude, fy / magnitude, fz / magnitude)
            direction = self._view_coordinates(*direction_model)
            scalar, qx, qy, qz = self._rotation_from_y_axis(direction)

            # Pull the tip back to the node's surface so the head doesn't bury
            # itself inside the sphere/member it is pointing at.
            tip = tuple(anchor[index] - direction[index] * self._node_radius for index in range(3))
            tail = tuple(tip[index] - direction[index] * arrow_length for index in range(3))
            shaft_mid = tuple(
                tail[index] + direction[index] * shaft_length / 2 for index in range(3)
            )
            # Unlike '#Cylinder'/'#Cube' (centred on their local origin), the built-in
            # '#Cone' primitive is pivoted at its BASE (local Y spans [0, 100], not
            # [-50, 50] - confirmed from the shipped mesh's own bounds). So its
            # position must be the base point, not a centred midpoint, or the head
            # both leaves a gap after the shaft and overshoots its tip past `tip`.
            head_base = tuple(tail[index] + direction[index] * shaft_length for index in range(3))
            rotation = {"qscalar": scalar, "qx": qx, "qy": qy, "qz": qz}
            case_color = _LOAD_CASE_COLORS[load.case_type]
            case_data = {
                "case_type": load.case_type.value,
                "pattern_tag": load.pattern_tag if load.pattern_tag is not None else -1,
            }
            parts.append(
                {
                    "tag": load.node_tag,
                    "kind": "nodal",
                    "role": "shaft",
                    "arrow_index": 0,
                    "shape": "#Cylinder",
                    "color": case_color,
                    "magnitude": magnitude,
                    "load_type": "nodal_force",
                    "x": shaft_mid[0],
                    "y": shaft_mid[1],
                    "z": shaft_mid[2],
                    "length": shaft_length,
                    "thickness": shaft_thickness,
                    **rotation,
                    **case_data,
                }
            )
            parts.append(
                {
                    "tag": load.node_tag,
                    "kind": "nodal",
                    "role": "head",
                    "arrow_index": 0,
                    "shape": "#Cone",
                    "color": case_color,
                    "magnitude": magnitude,
                    "load_type": "nodal_force",
                    "x": head_base[0],
                    "y": head_base[1],
                    "z": head_base[2],
                    "length": head_length,
                    "thickness": head_thickness,
                    **rotation,
                    **case_data,
                }
            )
        return parts

    def _build_all_load_arrows(
        self,
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
    ) -> list[dict[str, float | int | str]]:
        return [
            *self._build_load_arrows(model, points),
            *self._build_element_load_arrows(model, points),
        ]

    def _build_element_load_arrows(
        self,
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
    ) -> list[dict[str, float | int | str]]:
        """Draw one representative arrow at the midpoint of each loaded member.

        Horizontal 3D members use global Z as their local-z reference, matching the
        conventional OpenSees transformation used by the bundled frame examples.
        """
        maximum_magnitude = max(
            (
                math.sqrt(load.wx * load.wx + load.wy * load.wy + load.wz * load.wz)
                for load in model.element_loads
            ),
            default=0.0,
        )
        parts: list[dict[str, float | int | str]] = []

        for load in model.element_loads:
            element = model.elements.get(load.element_tag)
            if element is None:
                continue
            node_i = model.nodes.get(element.node_i)
            node_j = model.nodes.get(element.node_j)
            start = points.get(element.node_i)
            end = points.get(element.node_j)
            if node_i is None or node_j is None or start is None or end is None:
                continue

            local_x = self._normalized(
                (node_j.x - node_i.x, node_j.y - node_i.y, node_j.z - node_i.z)
            )
            if local_x is None:
                continue
            reference = (0.0, 0.0, 1.0) if abs(local_x[2]) < 0.99 else (1.0, 0.0, 0.0)
            local_y = self._normalized(self._cross(reference, local_x))
            if local_y is None:
                continue
            local_z = self._cross(local_x, local_y)
            vector = tuple(
                load.wx * local_x[index] + load.wy * local_y[index] + load.wz * local_z[index]
                for index in range(3)
            )
            direction_model = self._normalized(vector)
            if direction_model is None:
                continue
            magnitude = math.sqrt(load.wx * load.wx + load.wy * load.wy + load.wz * load.wz)
            scale = self._load_scale(magnitude, maximum_magnitude)
            arrow_length = max(self._extent * 0.085, 0.05) * scale
            shaft_length = arrow_length * 0.68
            head_length = arrow_length - shaft_length
            shaft_thickness = max(self._default_thickness * 0.36, 0.007)
            head_thickness = shaft_thickness * 2.15
            transverse_magnitude = math.hypot(load.wy, load.wz)
            is_axial = abs(load.wx) > transverse_magnitude
            color = (
                (_UNIFORM_AXIAL_COLOR if is_axial else _UNIFORM_TRANSVERSE_COLOR)
                if load.case_type == LoadCaseKind.UNCLASSIFIED
                else _LOAD_CASE_COLORS[load.case_type]
            )
            load_type = "uniform_axial" if is_axial else "uniform_transverse"
            direction = self._view_coordinates(*direction_model)
            scalar, qx, qy, qz = self._rotation_from_y_axis(direction)

            # Pull the tip away from the member centreline past the rendered surface.
            # A small extra clearance keeps the wide cone from looking embedded when
            # the view is oblique or the member and arrow overlap in screen space.
            area = self._number_property(element.properties, "A")
            section_size = math.sqrt(area) if area is not None and area > 0.0 else 0.0
            member_half_thickness = (
                min(max(section_size, self._default_thickness), self._extent * 0.055) / 2
            )
            visual_clearance = max(head_thickness * 0.18, self._extent * 0.0015)
            tip_offset = member_half_thickness + visual_clearance
            rotation = {"qscalar": scalar, "qx": qx, "qy": qy, "qz": qz}
            for arrow_index, fraction in enumerate((0.5,)):
                member_point = tuple(
                    start[index] + (end[index] - start[index]) * fraction for index in range(3)
                )
                tip = tuple(
                    member_point[index] - direction[index] * tip_offset for index in range(3)
                )
                tail = tuple(tip[index] - direction[index] * arrow_length for index in range(3))
                shaft_mid = tuple(
                    tail[index] + direction[index] * shaft_length / 2 for index in range(3)
                )
                # '#Cone' is pivoted at its base (see the matching comment in
                # _build_load_arrows), so its anchor is the base point, not a centre.
                head_base = tuple(
                    tail[index] + direction[index] * shaft_length for index in range(3)
                )
                common = {
                    "tag": load.element_tag,
                    "kind": "element",
                    "arrow_index": arrow_index,
                    "color": color,
                    "magnitude": magnitude,
                    "load_type": load_type,
                    "case_type": load.case_type.value,
                    "pattern_tag": load.pattern_tag if load.pattern_tag is not None else -1,
                    **rotation,
                }
                parts.extend(
                    (
                        {
                            **common,
                            "role": "shaft",
                            "shape": "#Cylinder",
                            "x": shaft_mid[0],
                            "y": shaft_mid[1],
                            "z": shaft_mid[2],
                            "length": shaft_length,
                            "thickness": shaft_thickness,
                            **rotation,
                        },
                        {
                            **common,
                            "role": "head",
                            "shape": "#Cone",
                            "x": head_base[0],
                            "y": head_base[1],
                            "z": head_base[2],
                            "length": head_length,
                            "thickness": head_thickness,
                        },
                    )
                )

            connector_points = []
            for fraction in (0.12, 0.88):
                member_point = tuple(
                    start[index] + (end[index] - start[index]) * fraction for index in range(3)
                )
                connector_points.append(
                    tuple(
                        member_point[index] - direction[index] * (tip_offset + arrow_length)
                        for index in range(3)
                    )
                )
            connector_orientation = self._member_orientation(
                connector_points[0], connector_points[1]
            )
            if connector_orientation is not None:
                connector_length, cscalar, cqx, cqy, cqz = connector_orientation
                parts.append(
                    {
                        "tag": load.element_tag,
                        "kind": "element",
                        "role": "distribution_line",
                        "arrow_index": -1,
                        "shape": "#Cylinder",
                        "color": color,
                        "magnitude": magnitude,
                        "load_type": load_type,
                        "case_type": load.case_type.value,
                        "pattern_tag": load.pattern_tag if load.pattern_tag is not None else -1,
                        "x": 0.5 * (connector_points[0][0] + connector_points[1][0]),
                        "y": 0.5 * (connector_points[0][1] + connector_points[1][1]),
                        "z": 0.5 * (connector_points[0][2] + connector_points[1][2]),
                        "length": connector_length,
                        "thickness": shaft_thickness * 0.42,
                        "qscalar": cscalar,
                        "qx": cqx,
                        "qy": cqy,
                        "qz": cqz,
                    }
                )
        return parts

    @staticmethod
    def _load_scale(magnitude: float, maximum_magnitude: float) -> float:
        """Readable relative glyph scale without letting small loads disappear."""
        if magnitude <= 0.0 or maximum_magnitude <= 0.0:
            return 0.45
        return 0.45 + 0.55 * math.sqrt(min(magnitude / maximum_magnitude, 1.0))

    def _clear(self) -> None:
        self._nodes = []
        self._members = []
        self._ghost_nodes = []
        self._ghost_members = []
        self._load_arrows = []
        self._center = (0.0, 0.0, 0.0)
        self._extent = 1.0
        self._ground_y = 0.0
        self._ground_width = 1.0
        self._ground_depth = 1.0
        self._points = {}
        self.scene_changed.emit()

    @staticmethod
    def _view_coordinates(x: float, y: float, z: float) -> tuple[float, float, float]:
        # Qt Quick 3D uses +Y as up. Structural +Z is therefore mapped to view +Y.
        return float(x), float(z), -float(y)

    @staticmethod
    def _member_orientation(
        start: tuple[float, float, float], end: tuple[float, float, float]
    ) -> tuple[float, float, float, float, float] | None:
        delta = tuple(end[index] - start[index] for index in range(3))
        length = math.sqrt(sum(value * value for value in delta))
        if length <= 1.0e-12:
            return None
        direction = tuple(value / length for value in delta)
        scalar, qx, qy, qz = Quick3DSceneBridge._rotation_from_y_axis(direction)
        return length, scalar, qx, qy, qz

    @staticmethod
    def _cross(
        first: tuple[float, float, float], second: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )

    @staticmethod
    def _normalized(
        vector: tuple[float, float, float],
    ) -> tuple[float, float, float] | None:
        length = math.sqrt(sum(value * value for value in vector))
        if length <= 1.0e-12:
            return None
        return tuple(value / length for value in vector)

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
    def _number_property(properties: dict[str, float | str], key: str) -> float | None:
        value = properties.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
