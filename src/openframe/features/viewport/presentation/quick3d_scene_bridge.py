"""Convert structural-domain objects into renderer-neutral Qt Quick 3D data."""

import math

from PySide6.QtCore import Property, QObject, Signal

from openframe.core.domain import (
    AnalysisResult,
    Element,
    FloorLoadEntry,
    LoadCase,
    LoadCaseKind,
    LoadCombination,
    LoadEntry,
    MemberDistributedLoadEntry,
    MemberPointLoadEntry,
    NodalLoadEntry,
    SelfWeightEntry,
    StructuralModel,
    SupportKind,
    auto_reference_vector,
    local_y_z_axes,
    rotate_about_axis,
)

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
#: Categorical palette (Tableau10-derived, red dropped since it's reserved for
#: the selection highlight) used to color-code members by assigned section in
#: the default (non-results) view, so a W24x100 column and a W8x10 brace read
#: as visibly different members even where their box-extrusion sizes alone
#: are hard to tell apart at a glance. Assigned in ``_assign_section_colors``.
_SECTION_COLOR_PALETTE: tuple[str, ...] = (
    "#4c78a8",  # blue
    "#f58518",  # orange
    "#54a24b",  # green
    "#b279a2",  # purple
    "#eeca3b",  # yellow
    "#72b7b2",  # teal
    "#9d755d",  # brown
)
#: Free-form 3D draw mode's live rubber-band preview - a thin, translucent
#: cube from the open chain's last node to wherever the cursor (or a node it
#: has snapped onto) currently is, cleared the instant the segment commits.
_PREVIEW_MEMBER_COLOR = "#2563eb"
_PREVIEW_MEMBER_OPACITY = 0.55
_PREVIEW_MEMBER_THICKNESS_SCALE = 0.4
#: Floor-boundary click-picking's live outline - a yellow edge drawn from
#: each picked boundary node to the next, replacing the filled ghost face
#: this used to render (a custom mesh rebuilt on every mouse-move, which made
#: the whole viewport crawl). Yellow rather than the preview blue above so it
#: reads as "boundary being traced", distinct from both the draw-mode
#: rubber-band and the blue committed-load glyphs it is drawn on top of.
_FLOOR_OUTLINE_COLOR = "#facc15"
_GHOST_COLOR = "#c9cfd6"
_GHOST_OPACITY = 0.35
_NODAL_FORCE_COLOR = "#e5484d"
_UNIFORM_TRANSVERSE_COLOR = "#f59e0b"
_UNIFORM_AXIAL_COLOR = "#8b5cf6"
_LOAD_CASE_COLORS = {
    LoadCaseKind.DEAD: "#2563eb",
    LoadCaseKind.LIVE: "#16a34a",
    LoadCaseKind.ROOF_LIVE: "#65a30d",
    LoadCaseKind.SEISMIC: "#f97316",
    LoadCaseKind.WIND: "#8b5cf6",
    LoadCaseKind.SNOW: "#0ea5e9",
    LoadCaseKind.OTHER: "#64748b",
    LoadCaseKind.UNCLASSIFIED: "#e5484d",
}
#: Picked-node highlight. Bright cyan sits outside the blue-yellow-red displacement
#: ramp and the load-arrow reds/oranges/purples, so it reads as "selected" regardless
#: of what colour the node would otherwise have.
_SELECTED_NODE_COLOR = "#ef4444"
_SELECTED_NODE_RADIUS_SCALE = 2.0
_SELECTED_MEMBER_COLOR = "#ef4444"
_SELECTED_MEMBER_THICKNESS_SCALE = 1.35
_SUPPORT_COLORS = {
    SupportKind.FIXED: "#00856a",
    SupportKind.PINNED: "#00a6a6",
    SupportKind.ROLLER_VERTICAL: "#6366f1",
    SupportKind.ROLLER_HORIZONTAL: "#6366f1",
    # No dedicated glyph shape yet - _support_symbol_parts falls through to
    # the generic "custom_block" cube for these (same as CUSTOM), so this
    # entry only needs to exist so the color lookup below doesn't KeyError.
    # Reusing the roller indigo keeps them visually grouped with the other
    # rollers rather than reading as an arbitrary/unrecognized restraint.
    SupportKind.ROLLER_X: "#6366f1",
    SupportKind.ROLLER_Y: "#6366f1",
    SupportKind.ROLLER_Z: "#6366f1",
    SupportKind.CUSTOM: "#f59e0b",
}
#: A 3D member's local y/z axis gizmo (a preview of ``Element.local_axis_angle``'s
#: effect) - colours chosen to not collide with any load/support/result colour
#: already in this palette.
_LOCAL_Y_AXIS_COLOR = "#22c55e"
_LOCAL_Z_AXIS_COLOR = "#ec4899"
#: 3D beam-column element types only - a truss has no bending stiffness or
#: local y/z orientation at all, so it never gets a gizmo (mirrors the
#: solver's own ``system != "truss"`` gate on ``_reference_vector``).
_TRUSS_ELEMENT_TYPES = frozenset({"truss", "corottruss"})


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
    #: Emitted when time-history deformation updates node/member coordinates
    #: in place - without rebuilding the whole scene (see deformationRevision).
    deformed_positions_changed = Signal()
    #: Emitted when time-history torsion marker orientations move in place.
    torsion_markers_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._nodes: list[dict[str, float | int | str]] = []
        self._members: list[dict[str, float | int | str]] = []
        self._ghost_nodes: list[dict[str, float | int | str]] = []
        self._ghost_members: list[dict[str, float | int | str]] = []
        self._load_arrows: list[dict[str, float | int | str]] = []
        self._support_parts: list[dict[str, float | int | str]] = []
        self._local_axis_gizmos: list[dict[str, float | int | str]] = []
        self._loads_visible = True
        self._supports_visible = True
        #: Off by default: this is an authoring aid for the free-form 3D
        #: canvas, not something the imported-model or results viewers (which
        #: share this same bridge class) should ever show unasked.
        self._local_axes_visible = False
        self._load_filter = "all"
        self._load_case_filter = "all"
        self._center = (0.0, 0.0, 0.0)
        self._extent = 1.0
        self._ground_y = 0.0
        self._ground_width = 1.0
        self._ground_depth = 1.0
        self._points: dict[int, tuple[float, float, float]] = {}
        self._preview_member: dict[str, float | int | str] | None = None
        self._floor_outline_parts: list[dict[str, float | int | str]] = []
        self._default_thickness = 0.025
        self._node_radius = 0.018
        self._last_model: StructuralModel | None = None
        self._selected_node_tags: set[int] = set()
        self._selected_member_tags: set[int] = set()
        #: Per-node bulge radius (see _compute_node_radii) - a large section's
        #: box can be several times wider than the old flat, section-agnostic
        #: node radius, swallowing the node both visually and for picking.
        #: Falls back to _node_radius for any tag missing from this dict.
        self._node_radii: dict[int, float] = {}
        #: MIDAS-style "Active Only" view filter (F2 to isolate the current
        #: selection, Ctrl+A to show everything again) - see set_isolate.
        self._isolate_active = False
        self._isolate_node_tags: set[int] = set()
        self._isolate_member_tags: set[int] = set()
        #: Loads tab (case-based Load Case/Load Entry/Load Combination store) -
        #: entirely separate from the nodal_loads/element_loads-driven
        #: loadArrows above (see canvas_load_entries.py's own module
        #: docstring for why). Cached raw inputs, not just the built part
        #: list, so set_model()/clear_result() can rebuild these glyphs at
        #: the model's new node positions the same way they already rebuild
        #: _load_arrows - without the caller having to remember to call
        #: set_load_entries() again after every geometry change.
        self._load_entries: dict[int, LoadEntry] = {}
        self._load_cases: dict[str, LoadCase] = {}
        self._load_combinations: dict[str, LoadCombination] = {}
        self._load_entry_mode = "case"
        self._load_entry_active_case_id: str | None = None
        self._load_entry_active_combination_id: str | None = None
        self._load_entry_scale = 1.0
        self._load_entry_parts: list[dict[str, float | int | str]] = []
        #: Time-history animation keeps stable node/member dicts and only moves
        #: coordinates each step - see begin_time_history_deformation().
        self._time_history_deformation_active = False
        self._deformation_show_original = True
        self._deformation_show_deformed = True
        self._deformation_revision = 0
        self._deformed_node_by_tag: dict[int, dict[str, float | int | str]] = {}
        self._deformation_member_records: list[
            tuple[Element, list[dict[str, float | int | str]]]
        ] = []
        self._torsion_marker_active = False
        self._torsion_markers_visible = False
        self._torsion_marker_count = 5
        self._torsion_revision = 0
        self._torsion_markers: list[dict[str, float | int | str | bool]] = []

    def set_model(self, model: StructuralModel) -> None:
        self._end_torsion_marker_mode(notify=False)
        self._end_time_history_deformation(notify=False)
        self._last_model = model
        self._selected_node_tags.clear()
        self._selected_member_tags.clear()
        self._isolate_active = False
        self._isolate_node_tags.clear()
        self._isolate_member_tags.clear()
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
        self._node_radii = self._compute_node_radii(model, self._default_thickness)

        self._center = (
            0.5 * (min(x_values) + max(x_values)),
            0.5 * (min(y_values) + max(y_values)),
            0.5 * (min(z_values) + max(z_values)),
        )
        if model.boundaries:
            support_height = max(self._extent * 0.05, 0.055)
            support_plate = max(support_height * 0.16, 0.012)
            ground_thickness = max(self._extent * 0.012, 0.01)
            self._ground_y = (
                min(y_values)
                - self._node_radius
                - support_height
                - support_plate
                - ground_thickness / 2
            )
        else:
            self._ground_y = min(y_values) - self._extent * 0.025
        self._ground_width = max(spans[0] + self._extent * 0.35, self._extent * 0.5)
        self._ground_depth = max(spans[2] + self._extent * 0.35, self._extent * 0.5)

        self._points = points
        self._rebuild_default_geometry(model)
        self._ghost_nodes = []
        self._ghost_members = []
        self._load_arrows = self._build_all_load_arrows(model, points)
        self._support_parts = self._build_support_parts(model, points)
        self._rebuild_load_entry_parts()
        self.scene_changed.emit()

    def set_result(
        self,
        model: StructuralModel,
        result: AnalysisResult,
        scale: float,
        show_undeformed: bool,
        member_magnitudes: dict[int, float] | None = None,
    ) -> None:
        """Overlay analysis displacements: deformed + colour-mapped geometry, an
        optional translucent undeformed ghost, and arrows at loaded nodes."""
        self._end_time_history_deformation(notify=False)
        self._end_torsion_marker_mode(notify=False)
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
                "radius": self._node_radii.get(tag, self._node_radius),
                "color": _color_for_ratio(ratios.get(tag, 0.0)),
                "opacity": 1.0,
            }
            for tag, point in sorted(deformed_points.items())
        ]

        if member_magnitudes:
            member_peak = max(member_magnitudes.values(), default=0.0)
            member_ratios = {
                tag: 0.0 if member_peak <= 1.0e-12 else value / member_peak
                for tag, value in member_magnitudes.items()
            }
        else:
            member_ratios = None

        members: list[dict[str, float | int | str]] = []
        for element in sorted(model.elements.values(), key=lambda item: item.tag):
            if member_ratios is not None:
                ratio = member_ratios.get(element.tag, 0.0)
            else:
                ratio = 0.5 * (ratios.get(element.node_i, 0.0) + ratios.get(element.node_j, 0.0))
            members.extend(
                self._member_parts(
                    element,
                    deformed_points,
                    self._default_thickness,
                    color=_color_for_ratio(ratio),
                )
            )
        self._members = members

        if show_undeformed:
            self._ghost_nodes = [
                {
                    "tag": tag,
                    "x": point[0],
                    "y": point[1],
                    "z": point[2],
                    "radius": self._node_radii.get(tag, self._node_radius),
                    "color": _GHOST_COLOR,
                    "opacity": _GHOST_OPACITY,
                }
                for tag, point in sorted(self._points.items())
            ]
            ghost_members: list[dict[str, float | int | str]] = []
            for element in sorted(model.elements.values(), key=lambda item: item.tag):
                ghost_members.extend(
                    self._member_parts(
                        element,
                        self._points,
                        self._default_thickness,
                        color=_GHOST_COLOR,
                        opacity=_GHOST_OPACITY,
                    )
                )
            self._ghost_members = ghost_members
        else:
            self._ghost_nodes = []
            self._ghost_members = []

        self._load_arrows = self._build_all_load_arrows(model, deformed_points)
        self.scene_changed.emit()

    def clear_result(self) -> None:
        """Drop the result overlay and go back to the plain undeformed model."""
        self._end_time_history_deformation(notify=False)
        self._end_torsion_marker_mode(notify=False)
        self._ghost_nodes = []
        self._ghost_members = []
        if self._last_model is not None and self._points:
            self._rebuild_default_geometry(self._last_model)
            self._load_arrows = self._build_all_load_arrows(self._last_model, self._points)
            self._rebuild_load_entry_parts()
        self.scene_changed.emit()

    def begin_time_history_deformation(
        self,
        model: StructuralModel,
        *,
        show_original: bool = True,
        show_deformed: bool = True,
    ) -> None:
        """One-time setup for time-history playback: stable node/member dicts.

        Ghost (undeformed) geometry is built once from ``self._points`` and
        never moved again; each step only calls
        :meth:`update_deformed_node_positions`.
        """
        if not self._points:
            return
        self._end_time_history_deformation(notify=False)
        self._last_model = model
        self._time_history_deformation_active = True
        self._deformation_show_original = show_original
        self._deformation_show_deformed = show_deformed
        self._deformation_revision = 0
        self._build_time_history_ghost_geometry(model)

        self._deformed_node_by_tag = {}
        self._nodes = []
        for tag, point in sorted(self._points.items()):
            entry: dict[str, float | int | str] = {
                "tag": tag,
                "x": point[0],
                "y": point[1],
                "z": point[2],
                "radius": self._node_radii.get(tag, self._node_radius),
                "color": _DEFAULT_NODE_COLOR,
                "opacity": 1.0,
            }
            self._deformed_node_by_tag[tag] = entry
            self._nodes.append(entry)

        section_colors = self._assign_section_colors(model)
        self._members = []
        self._deformation_member_records = []
        for element in sorted(model.elements.values(), key=lambda item: item.tag):
            key = self._section_color_key(element.properties)
            color = _DEFAULT_MEMBER_COLOR if key is None else section_colors[key]
            parts = self._member_parts(
                element, self._points, self._default_thickness, color=color
            )
            self._deformation_member_records.append((element, parts))
            self._members.extend(parts)
        self.scene_changed.emit()

    def update_deformed_node_positions(
        self,
        deformed_points: dict[int, tuple[float, float, float]],
        *,
        show_original: bool = True,
        show_deformed: bool = True,
        node_ratios: dict[int, float] | None = None,
    ) -> None:
        """Move the deformed overlay to ``deformed_points`` without rebuilding lists."""
        if not self._time_history_deformation_active:
            return
        self._deformation_show_original = show_original
        self._deformation_show_deformed = show_deformed

        for tag, point in deformed_points.items():
            entry = self._deformed_node_by_tag.get(tag)
            if entry is None:
                continue
            entry["x"] = point[0]
            entry["y"] = point[1]
            entry["z"] = point[2]
            if node_ratios is not None and tag in node_ratios:
                entry["color"] = _color_for_ratio(node_ratios[tag])

        for element, part_dicts in self._deformation_member_records:
            if not part_dicts:
                continue
            if node_ratios is not None:
                ratio = 0.5 * (
                    node_ratios.get(element.node_i, 0.0)
                    + node_ratios.get(element.node_j, 0.0)
                )
                color = _color_for_ratio(ratio)
            else:
                color = str(part_dicts[0]["color"])
            self._update_member_parts_in_place(
                element, part_dicts, deformed_points, color=color
            )

        self._deformation_revision += 1
        self.deformed_positions_changed.emit()

    def set_deformed_node_positions(
        self,
        deformed_points: dict[int, tuple[float, float, float]],
        *,
        show_undeformed: bool = True,
        show_deformed: bool = True,
        node_ratios: dict[int, float] | None = None,
    ) -> None:
        self.update_deformed_node_positions(
            deformed_points,
            show_original=show_undeformed,
            show_deformed=show_deformed,
            node_ratios=node_ratios,
        )

    def begin_torsion_marker_mode(self, model: StructuralModel, marker_count: int = 5) -> None:
        """One-time torsion-marker shell for time-history playback."""
        if not self._points or model.ndm != 3:
            return
        self._end_torsion_marker_mode(notify=False)
        self._torsion_marker_active = True
        self._torsion_markers_visible = False
        self._torsion_marker_count = max(1, marker_count)
        self._torsion_revision = 0
        arm_length = max(self._extent * 0.06, 0.035)
        thickness = max(self._default_thickness * 0.35, 0.006)
        markers: list[dict[str, float | int | str | bool]] = []
        for element in sorted(model.elements.values(), key=lambda item: item.tag):
            if element.element_type.lower() in _TRUSS_ELEMENT_TYPES:
                continue
            for marker_index in range(self._torsion_marker_count):
                markers.append(
                    {
                        "element_tag": element.tag,
                        "marker_index": marker_index,
                        "x": 0.0,
                        "y": 0.0,
                        "z": 0.0,
                        "length": arm_length,
                        "thickness": thickness,
                        "y_qscalar": 1.0,
                        "y_qx": 0.0,
                        "y_qy": 0.0,
                        "y_qz": 0.0,
                        "z_qscalar": 1.0,
                        "z_qx": 0.0,
                        "z_qy": 0.0,
                        "z_qz": 0.0,
                        "visible": False,
                    }
                )
        self._torsion_markers = markers
        self.scene_changed.emit()

    def update_torsion_markers(
        self,
        arms: tuple[object, ...],
        *,
        visible: bool,
    ) -> None:
        """Update marker position/orientation in place - order must match begin."""
        if not self._torsion_marker_active:
            return
        self._torsion_markers_visible = visible and bool(arms)
        expected = len(self._torsion_markers) * 2
        if len(arms) != expected:
            return
        rotation_from_y = Quick3DSceneBridge._rotation_from_y_axis
        markers = self._torsion_markers
        for station_index in range(len(markers)):
            y_arm = arms[station_index * 2]
            z_arm = arms[station_index * 2 + 1]
            entry = markers[station_index]
            show = visible and getattr(y_arm, "valid", False) and getattr(z_arm, "valid", False)
            entry["visible"] = show
            if not show:
                continue
            view_pos = self._view_coordinates(
                float(getattr(y_arm, "position_x")),
                float(getattr(y_arm, "position_y")),
                float(getattr(y_arm, "position_z")),
            )
            entry["x"] = view_pos[0]
            entry["y"] = view_pos[1]
            entry["z"] = view_pos[2]
            for prefix, arm in (("y_", y_arm), ("z_", z_arm)):
                view_dir = self._view_coordinates(
                    float(getattr(arm, "direction_x")),
                    float(getattr(arm, "direction_y")),
                    float(getattr(arm, "direction_z")),
                )
                dir_length = math.sqrt(sum(value * value for value in view_dir)) or 1.0
                unit_dir = tuple(value / dir_length for value in view_dir)
                scalar, qx, qy, qz = rotation_from_y(unit_dir)
                entry[f"{prefix}qscalar"] = scalar
                entry[f"{prefix}qx"] = qx
                entry[f"{prefix}qy"] = qy
                entry[f"{prefix}qz"] = qz
        self._torsion_revision += 1
        self.torsion_markers_changed.emit()

    def end_torsion_marker_mode(self) -> None:
        self._end_torsion_marker_mode(notify=True)

    def _end_torsion_marker_mode(self, *, notify: bool) -> None:
        if not self._torsion_marker_active and not self._torsion_markers:
            return
        self._torsion_marker_active = False
        self._torsion_markers_visible = False
        self._torsion_markers = []
        self._torsion_revision = 0
        if notify:
            self.scene_changed.emit()

    def end_time_history_deformation(self) -> None:
        self._end_time_history_deformation(notify=True)

    def _end_time_history_deformation(self, *, notify: bool) -> None:
        if not self._time_history_deformation_active:
            return
        self._end_torsion_marker_mode(notify=False)
        self._time_history_deformation_active = False
        self._deformed_node_by_tag = {}
        self._deformation_member_records = []
        self._ghost_nodes = []
        self._ghost_members = []
        self._deformation_revision = 0
        if self._last_model is not None and self._points:
            self._rebuild_default_geometry(self._last_model)
        if notify:
            self.scene_changed.emit()

    def _build_time_history_ghost_geometry(self, model: StructuralModel) -> None:
        self._ghost_nodes = [
            {
                "tag": tag,
                "x": point[0],
                "y": point[1],
                "z": point[2],
                "radius": self._node_radii.get(tag, self._node_radius),
                "color": _GHOST_COLOR,
                "opacity": _GHOST_OPACITY,
            }
            for tag, point in sorted(self._points.items())
        ]
        ghost_members: list[dict[str, float | int | str]] = []
        for element in sorted(model.elements.values(), key=lambda item: item.tag):
            ghost_members.extend(
                self._member_parts(
                    element,
                    self._points,
                    self._default_thickness,
                    color=_GHOST_COLOR,
                    opacity=_GHOST_OPACITY,
                )
            )
        self._ghost_members = ghost_members

    def _update_member_parts_in_place(
        self,
        element: Element,
        part_dicts: list[dict[str, float | int | str]],
        points: dict[int, tuple[float, float, float]],
        *,
        color: str,
    ) -> None:
        fresh_parts = self._member_parts(
            element, points, self._default_thickness, color=color
        )
        if len(fresh_parts) != len(part_dicts):
            return
        for existing, updated in zip(part_dicts, fresh_parts, strict=True):
            existing.update(updated)

    def set_loads_visible(self, visible: bool) -> None:
        self._loads_visible = visible
        self.scene_changed.emit()

    def set_supports_visible(self, visible: bool) -> None:
        self._supports_visible = visible
        self.scene_changed.emit()

    def set_local_axes_visible(self, visible: bool) -> None:
        self._local_axes_visible = visible
        self.scene_changed.emit()

    def set_load_filter(self, load_filter: str) -> None:
        if load_filter not in {"all", "nodal", "element"}:
            return
        self._load_filter = load_filter
        self.scene_changed.emit()

    def set_load_case_filter(self, case_filter: str) -> None:
        self._load_case_filter = case_filter
        self.scene_changed.emit()

    def set_load_entries(
        self,
        load_entries: dict[int, LoadEntry],
        load_cases: dict[str, LoadCase],
        load_combinations: dict[str, LoadCombination],
        *,
        mode: str = "case",
        active_case_id: str | None = None,
        active_combination_id: str | None = None,
        scale: float = 1.0,
    ) -> None:
        """Push the Loads tab's own case-based store (see
        ``canvas_load_entries.py``) for rendering - entirely separate from
        ``set_model()``'s ``nodal_loads``/``element_loads`` arrows. ``mode``
        mirrors the Display combo ("case"/"combination"/"all"/"hidden");
        "combination" previews each entry scaled by its case's
        ``LoadCombination.factor_for(case.kind)`` without writing anything
        back, matching ``create_load_case_from_combination``'s own scaling.
        """
        self._load_entries = dict(load_entries)
        self._load_cases = dict(load_cases)
        self._load_combinations = dict(load_combinations)
        self._load_entry_mode = mode
        self._load_entry_active_case_id = active_case_id
        self._load_entry_active_combination_id = active_combination_id
        self._load_entry_scale = scale
        self._rebuild_load_entry_parts()
        self.scene_changed.emit()

    def set_selected_node(self, tag: int | None) -> None:
        self._selected_node_tags = set() if tag is None else {tag}
        self._selected_member_tags.clear()
        self.scene_changed.emit()

    def set_selection(self, node_tags: set[int], member_tags: set[int]) -> None:
        """Highlight the authoring canvas selection in the 3D scene.

        The result viewport still uses :meth:`set_selected_node`; modeling needs
        the full node/member sets because a box selection can contain both.
        """
        self._selected_node_tags = set(node_tags)
        self._selected_member_tags = set(member_tags)
        self.scene_changed.emit()

    def set_isolate(self, node_tags: set[int], member_tags: set[int]) -> None:
        """MIDAS-style "Active Only" view filter: hide everything except the
        given nodes/members (see the F2 shortcut in modeling_interface_page)
        so a floor load or other localized edit on one story doesn't have to
        fight the rest of the building for visibility or click-picking.
        A no-op if both sets are empty - nothing to isolate to.
        """
        if not node_tags and not member_tags:
            return
        self._isolate_active = True
        self._isolate_node_tags = set(node_tags)
        self._isolate_member_tags = set(member_tags)
        self.scene_changed.emit()

    def clear_isolate(self) -> None:
        """Show everything again (Ctrl+A) - the inverse of set_isolate."""
        if not self._isolate_active:
            return
        self._isolate_active = False
        self._isolate_node_tags.clear()
        self._isolate_member_tags.clear()
        self.scene_changed.emit()

    @Property(bool, notify=scene_changed)
    def isolateActive(self) -> bool:
        return self._isolate_active

    def set_preview_segment(
        self,
        start: tuple[float, float, float] | None,
        end: tuple[float, float, float] | None,
    ) -> None:
        """Rubber-band a thin preview member from ``start`` to ``end`` (both
        structural x/y/z), or clear it if either is ``None``.

        Used only by free-form 3D draw mode, to show where a member would
        land before the user actually clicks - see ``modeling_interface_page.
        _on_3d_draw_state_changed`` and its hover handlers for the caller side.
        """
        if start is None or end is None:
            if self._preview_member is not None:
                self._preview_member = None
                self.scene_changed.emit()
            return
        view_start = self._view_coordinates(*start)
        view_end = self._view_coordinates(*end)
        orientation = self._member_orientation(view_start, view_end)
        if orientation is None:
            if self._preview_member is not None:
                self._preview_member = None
                self.scene_changed.emit()
            return
        length, scalar, qx, qy, qz = orientation
        self._preview_member = {
            "x": 0.5 * (view_start[0] + view_end[0]),
            "y": 0.5 * (view_start[1] + view_end[1]),
            "z": 0.5 * (view_start[2] + view_end[2]),
            "length": length,
            "thickness": self._default_thickness * _PREVIEW_MEMBER_THICKNESS_SCALE,
            "qscalar": scalar,
            "qx": qx,
            "qy": qy,
            "qz": qz,
            "color": _PREVIEW_MEMBER_COLOR,
            "opacity": _PREVIEW_MEMBER_OPACITY,
        }
        self.scene_changed.emit()

    def set_floor_boundary_outline(self, points: list[tuple[float, float, float]]) -> None:
        """Trace the in-progress floor boundary as a yellow outline: one edge
        per already-picked pair of boundary nodes, in click order, plus a
        trailing edge to the cursor if it is included as the last point.

        ``points`` are structural x/y/z - the already-picked chain nodes' own
        coordinates plus, while the mouse is moving, the current cursor
        position as a trailing point (see
        ``modeling_interface_page._update_3d_floor_outline`` for the caller
        side). Closing the loop (clicking back on the boundary's first node)
        ends picking outright rather than appending a point, so this never
        needs to draw a closing edge itself - fewer than 2 points has no edge
        to draw at all, so the outline is simply emptied.

        Rebuilding these thin edge segments on every mouse-move is cheap -
        unlike the filled ghost face this replaced, a custom triangle-fan
        mesh whose GPU buffer got re-uploaded on every single move and made
        the whole viewport lag.
        """
        view_points = [self._view_coordinates(*point) for point in points]
        parts: list[dict[str, float | int | str]] = []
        if len(view_points) >= 2:
            # Thicker than the committed floor glyph's own boundary loop
            # (_floor_entry_parts uses 0.3) so the outline being traced stays
            # readable when it runs along an already-applied floor's edge.
            thickness = max(self._default_thickness * 0.45, 0.008)
            parts = self._connector_segments(
                view_points, thickness, {"color": _FLOOR_OUTLINE_COLOR}
            )
        if parts == self._floor_outline_parts:
            return
        self._floor_outline_parts = parts
        self.scene_changed.emit()

    @Property("QVariantList", notify=scene_changed)
    def nodes(self) -> list[dict[str, float | int | str]]:
        source = self._nodes
        if self._isolate_active:
            source = [node for node in source if node["tag"] in self._isolate_node_tags]
        if not self._selected_node_tags:
            return source
        # A picked node is highlighted here rather than baked into `_nodes` at build
        # time, so the highlight survives whatever set_result()/clear_result() next
        # rebuilds `_nodes` with (deformation scale changes, undeformed toggle, ...).
        highlighted = []
        for node in source:
            if node["tag"] in self._selected_node_tags:
                node = dict(node)
                node["selected"] = True
                node["color"] = _SELECTED_NODE_COLOR
                node["radius"] = node["radius"] * _SELECTED_NODE_RADIUS_SCALE
            highlighted.append(node)
        return highlighted

    @Property("QVariantList", notify=scene_changed)
    def members(self) -> list[dict[str, float | int | str]]:
        source = self._members
        if self._isolate_active:
            source = [member for member in source if member["tag"] in self._isolate_member_tags]
        if not self._selected_member_tags:
            return source
        highlighted = []
        for member in source:
            if member["tag"] in self._selected_member_tags:
                member = dict(member)
                member["selected"] = True
                member["color"] = _SELECTED_MEMBER_COLOR
                # Each part (a plain box, or one of an H-section's web/
                # flanges) is now fully self-contained - scaling its own
                # width_b/width_h is enough, no separate web/flange keys to
                # keep in sync with it any more.
                member["width_b"] = member["width_b"] * _SELECTED_MEMBER_THICKNESS_SCALE
                member["width_h"] = member["width_h"] * _SELECTED_MEMBER_THICKNESS_SCALE
            highlighted.append(member)
        return highlighted

    @Property("QVariantList", notify=scene_changed)
    def ghostNodes(self) -> list[dict[str, float | int | str]]:
        return self._ghost_nodes

    @Property("QVariantList", notify=scene_changed)
    def ghostMembers(self) -> list[dict[str, float | int | str]]:
        return self._ghost_members

    @Property("QVariantList", notify=scene_changed)
    def previewMembers(self) -> list[dict[str, float | int | str]]:
        return [] if self._preview_member is None else [self._preview_member]

    @Property("QVariantList", notify=scene_changed)
    def floorBoundaryOutline(self) -> list[dict[str, float | int | str]]:
        """Edges of the floor boundary currently being click-picked - see
        ``set_floor_boundary_outline``."""
        return self._floor_outline_parts

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

    @Property("QVariantList", notify=scene_changed)
    def loadEntryGlyphs(self) -> list[dict[str, float | int | str]]:
        """Glyphs for the Loads tab's case-based store - gated by the same
        master ``_loads_visible`` toggle as ``loadArrows`` (the Display
        combo's "Hide Loads" mode already empties ``_load_entry_parts``
        itself, in ``_build_load_entry_parts``)."""
        return self._load_entry_parts if self._loads_visible else []

    @Property("QVariantList", notify=scene_changed)
    def supportSymbols(self) -> list[dict[str, float | int | str]]:
        return self._support_parts if self._supports_visible else []

    @Property("QVariantList", notify=scene_changed)
    def localAxisGizmos(self) -> list[dict[str, float | int | str]]:
        return self._local_axis_gizmos if self._local_axes_visible else []

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

    @Property(int, notify=deformed_positions_changed)
    def deformationRevision(self) -> int:
        return self._deformation_revision

    @Property(bool, notify=deformed_positions_changed)
    def timeHistoryDeformationActive(self) -> bool:
        return self._time_history_deformation_active

    @Property(bool, notify=deformed_positions_changed)
    def timeHistoryShowDeformed(self) -> bool:
        if not self._time_history_deformation_active:
            return True
        return self._deformation_show_deformed

    @Property(bool, notify=deformed_positions_changed)
    def timeHistoryShowOriginal(self) -> bool:
        if not self._time_history_deformation_active:
            return True
        return self._deformation_show_original

    @Property("QVariantList", notify=scene_changed)
    def torsionMarkers(self) -> list[dict[str, float | int | str | bool]]:
        return self._torsion_markers

    @Property(int, notify=torsion_markers_changed)
    def torsionRevision(self) -> int:
        return self._torsion_revision

    @Property(bool, notify=torsion_markers_changed)
    def torsionMarkersVisible(self) -> bool:
        return self._torsion_marker_active and self._torsion_markers_visible

    def _compute_node_radii(
        self, model: StructuralModel, default_thickness: float
    ) -> dict[int, float]:
        """Per-node marker radius, large enough to poke out past the
        cross-section of every member framing into that node.

        The old radius was a single value derived only from
        ``default_thickness`` - a rough, section-agnostic fallback - while a
        real assigned section's box can render several times wider
        (``_section_visual_dimensions`` clamps up to ``extent * 0.055``).
        That let a big W-section's box fully swallow the node sphere, both
        visually and for click-picking, at a beam-column joint - the node
        read as buried inside the member instead of the member framing into
        the node. Radius is per-node (not a single global bump) so a
        slender brace elsewhere in the same model doesn't get an
        oversized ball for no reason.
        """
        radii: dict[int, float] = {}
        for element in model.elements.values():
            visual = self._section_visual_dimensions(element.properties, default_thickness)
            half_diagonal = 0.5 * math.hypot(visual["width_b"], visual["width_h"])
            bulge = min(half_diagonal * 1.15, self._extent * 0.03)
            for tag in (element.node_i, element.node_j):
                if bulge > radii.get(tag, 0.0):
                    radii[tag] = bulge
        return radii

    def _rebuild_default_geometry(self, model: StructuralModel) -> None:
        self._local_axis_gizmos = self._local_axis_gizmo_parts(model, self._points)
        self._nodes = [
            {
                "tag": tag,
                "x": point[0],
                "y": point[1],
                "z": point[2],
                "radius": self._node_radii.get(tag, self._node_radius),
                "color": _DEFAULT_NODE_COLOR,
                "opacity": 1.0,
            }
            for tag, point in sorted(self._points.items())
        ]
        section_colors = self._assign_section_colors(model)
        members: list[dict[str, float | int | str]] = []
        for element in sorted(model.elements.values(), key=lambda item: item.tag):
            key = self._section_color_key(element.properties)
            color = _DEFAULT_MEMBER_COLOR if key is None else section_colors[key]
            members.extend(
                self._member_parts(element, self._points, self._default_thickness, color=color)
            )
        self._members = members

    @staticmethod
    def _section_color_key(properties: dict[str, float | str]) -> str | None:
        """A hashable identity for "this member's section", for color-coding
        the default view - ``None`` for a member with no section assigned
        yet (predates the section feature, or only ever got A/Iy/Iz/J), which
        keeps the old uniform ``_DEFAULT_MEMBER_COLOR`` rather than picking up
        an arbitrary palette entry. A Database section carries a stable
        ``section_id`` (e.g. two W8x10 columns picked from the Master DB
        share one), while a Custom section has none, so its own shape plus
        every ``dim_*``/``width``/``height`` value stands in for identity -
        two members with identical dimensions still read as "the same
        section" even though neither has a ``section_id``.
        """
        shape = properties.get("section_shape")
        if not shape:
            return None
        section_id = properties.get("section_id")
        if section_id:
            return f"id:{section_id}"
        dims = sorted(
            (key, value)
            for key, value in properties.items()
            if key.startswith("dim_") or key in ("width", "height")
        )
        return f"{shape}:{dims}"

    def _assign_section_colors(self, model: StructuralModel) -> dict[str, str]:
        """Stable section-key -> palette-color mapping for one rebuild, so
        every member sharing a section gets the same color. Sorted rather
        than insertion-ordered so the mapping doesn't shuffle between
        rebuilds just because members were added/reordered - only adding or
        removing a distinct section changes anyone's color.
        """
        keys = sorted(
            {
                key
                for element in model.elements.values()
                if (key := self._section_color_key(element.properties)) is not None
            }
        )
        return {
            key: _SECTION_COLOR_PALETTE[index % len(_SECTION_COLOR_PALETTE)]
            for index, key in enumerate(keys)
        }

    def _build_support_parts(
        self,
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
    ) -> list[dict[str, float | int | str]]:
        """Build MIDAS-like 3D support glyphs beneath restrained nodes."""
        parts: list[dict[str, float | int | str]] = []
        width = max(self._extent * 0.055, 0.06)
        height = max(self._extent * 0.05, 0.055)
        plate_height = max(height * 0.16, 0.012)
        identity = {"qscalar": 1.0, "qx": 0.0, "qy": 0.0, "qz": 0.0}

        for boundary in model.boundaries:
            point = points.get(boundary.node_tag)
            if point is None:
                continue
            kind = boundary.support_kind
            color = _SUPPORT_COLORS[kind]
            common = {
                "tag": boundary.node_tag,
                "kind": kind.value,
                "color": color,
                "restraints": "".join("1" if value else "0" for value in boundary.restraints),
                **identity,
            }
            node_bottom = point[1] - self._node_radius

            if kind == SupportKind.FIXED:
                parts.append(
                    {
                        **common,
                        "role": "fixed_block",
                        "shape": "#Cube",
                        "x": point[0],
                        "y": node_bottom - height / 2,
                        "z": point[2],
                        "scale_x": width,
                        "scale_y": height,
                        "scale_z": width,
                    }
                )
                continue

            if kind in {SupportKind.PINNED, SupportKind.ROLLER_HORIZONTAL}:
                cone_base_y = node_bottom - height
                parts.append(
                    {
                        **common,
                        "role": "pin_cone",
                        "shape": "#Cone",
                        "x": point[0],
                        "y": cone_base_y,
                        "z": point[2],
                        "scale_x": width,
                        "scale_y": height,
                        "scale_z": width,
                    }
                )
                base_y = cone_base_y - plate_height / 2
                if kind == SupportKind.PINNED:
                    parts.append(
                        {
                            **common,
                            "role": "ground_plate",
                            "shape": "#Cube",
                            "x": point[0],
                            "y": base_y,
                            "z": point[2],
                            "scale_x": width * 1.35,
                            "scale_y": plate_height,
                            "scale_z": width * 1.35,
                        }
                    )
                else:
                    roller_radius = width * 0.13
                    rotation = self._rotation_from_y_axis((0.0, 0.0, 1.0))
                    roller_q = {
                        "qscalar": rotation[0],
                        "qx": rotation[1],
                        "qy": rotation[2],
                        "qz": rotation[3],
                    }
                    for offset in (-width * 0.28, width * 0.28):
                        parts.append(
                            {
                                **common,
                                **roller_q,
                                "role": "roller",
                                "shape": "#Cylinder",
                                "x": point[0] + offset,
                                "y": cone_base_y - roller_radius,
                                "z": point[2],
                                "scale_x": roller_radius * 2,
                                "scale_y": width * 0.9,
                                "scale_z": roller_radius * 2,
                            }
                        )
                continue

            # Horizontal rollers and arbitrary partial restraints are rendered as an
            # amber/indigo restraint block; the exact active DOFs remain available in
            # the model tree and inspector instead of being hidden by a generic pin.
            parts.append(
                {
                    **common,
                    "role": "custom_block",
                    "shape": "#Cube",
                    "x": point[0],
                    "y": node_bottom - height * 0.32,
                    "z": point[2],
                    "scale_x": width * 0.72,
                    "scale_y": height * 0.64,
                    "scale_z": width * 0.72,
                }
            )
        return parts

    def _local_axis_gizmo_parts(
        self,
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
    ) -> list[dict[str, float | int | str]]:
        """Two short coloured cylinders per 3D beam-column member - one along
        its local y axis, one along its local z axis - a live preview of what
        ``Element.local_axis_angle`` actually does before running an
        analysis. Only meaningful for a 3D frame member (2D and truss
        elements never get a ``geomTransf``/local axis at all), so both are
        skipped.

        The axis/reference/y-z vectors are computed in *model* space (real
        node x/y/z), using ``auto_reference_vector``/``rotate_about_axis``/
        ``local_y_z_axes`` from ``core.domain.geometric_transform`` - the
        exact same functions ``MaterialFreeStaticsSolver._reference_vector``
        uses to actually solve, so this preview can never drift from what the
        analysis will do. Only the final y/z *directions* are run through
        ``_view_coordinates`` (mirrors ``_build_load_arrows``'s
        ``direction_model`` -> ``_view_coordinates`` order) - doing that
        conversion any earlier would silently corrupt the vertical-member
        check inside ``auto_reference_vector``, which is defined in terms of
        the structural model's own up axis, not the Qt Quick 3D view's.
        """
        if model.ndm != 3:
            return []
        length = max(self._extent * 0.12, 0.05)
        thickness = max(self._default_thickness * 0.45, 0.008)
        parts: list[dict[str, float | int | str]] = []
        for element in model.elements.values():
            if element.element_type.lower() in _TRUSS_ELEMENT_TYPES:
                continue
            node_i = model.nodes.get(element.node_i)
            node_j = model.nodes.get(element.node_j)
            view_start = points.get(element.node_i)
            view_end = points.get(element.node_j)
            if node_i is None or node_j is None or view_start is None or view_end is None:
                continue
            dx = node_j.x - node_i.x
            dy = node_j.y - node_i.y
            dz = node_j.z - node_i.z
            member_length = math.sqrt(dx * dx + dy * dy + dz * dz)
            if member_length <= 1.0e-9:
                continue
            axis = (dx / member_length, dy / member_length, dz / member_length)
            reference = auto_reference_vector(axis)
            if element.local_axis_angle:
                reference = rotate_about_axis(reference, axis, math.radians(element.local_axis_angle))
            y_axis, z_axis = local_y_z_axes(axis, reference)
            mid = tuple(0.5 * (view_start[k] + view_end[k]) for k in range(3))
            for direction, color in ((y_axis, _LOCAL_Y_AXIS_COLOR), (z_axis, _LOCAL_Z_AXIS_COLOR)):
                scalar, qx, qy, qz = self._rotation_from_y_axis(self._view_coordinates(*direction))
                parts.append(
                    {
                        "tag": element.tag,
                        "x": mid[0],
                        "y": mid[1],
                        "z": mid[2],
                        "length": length,
                        "thickness": thickness,
                        "qscalar": scalar,
                        "qx": qx,
                        "qy": qy,
                        "qz": qz,
                        "color": color,
                    }
                )
        return parts

    def _section_visual_dimensions(
        self, properties: dict[str, float | str], default_thickness: float
    ) -> dict[str, float | str]:
        """Cross-section box dimensions for rendering, in the same B(width)/
        H(height) convention ``core.domain.section_properties`` uses: H is
        the extent along the member's local Z axis (its H^3 term drives Iy,
        the strong-axis inertia), B the extent along local Y (drives Iz).

        Reads only what ``apply_full_section_to_selection`` already writes -
        ``section_shape``, ``width``/``height`` (Rectangle only), and the
        shape-agnostic ``dim_<key>`` entries every shape's raw dimensions are
        stored under (``dim_H``/``dim_B``/``dim_tw``/``dim_tf`` for an H/I
        section, ``dim_D`` for Circle/Pipe, ...) - no schema change needed.
        An H/I section additionally gets web/flange sub-dimensions so the
        renderer can draw three boxes (two flanges + a web) instead of one.
        Anything else (a User Defined custom section, or a member that
        predates this feature and only ever got A/Iy/Iz/J) falls back to the
        old uniform sqrt(area) square, unchanged.
        """
        minimum = default_thickness * 0.2
        maximum = self._extent * 0.055

        def clamp(value: float) -> float:
            return min(max(value, minimum), maximum)

        def dim(key: str) -> float | None:
            return self._number_property(properties, f"dim_{key}")

        shape = properties.get("section_shape")

        if shape in {"Circle", "Pipe"}:
            diameter = dim("D")
            if diameter is not None and diameter > 0.0:
                size = clamp(diameter)
                return {"shape": shape, "width_b": size, "width_h": size}

        if shape in {"H/I Section", "Box", "Channel", "Angle"}:
            overall_h, overall_b = dim("H"), dim("B")
            if overall_h is not None and overall_b is not None and overall_h > 0.0 and overall_b > 0.0:
                result: dict[str, float | str] = {
                    "shape": shape,
                    "width_b": clamp(overall_b),
                    "width_h": clamp(overall_h),
                }
                if shape == "H/I Section":
                    web_thickness, flange_thickness = dim("tw"), dim("tf")
                    if (
                        web_thickness is not None
                        and flange_thickness is not None
                        and 0.0 < flange_thickness < overall_h / 2.0
                        and 0.0 < web_thickness < overall_b
                    ):
                        # tw/tf must shrink by the same ratio a clamped H/B
                        # just did, or the web/flange sub-boxes would still be
                        # sized for the *real* H/B and no longer fit inside
                        # the clamped outer footprint above.
                        ratio = min(result["width_h"] / overall_h, result["width_b"] / overall_b)
                        # A real steel section's web/flange (millimetres) is
                        # imperceptibly thin next to a member several metres
                        # long when drawn strictly to scale - it renders as a
                        # near-invisible hairline, not a recognisable H-shape.
                        # Floor both at a visible fraction of the section's
                        # own outer envelope instead - the same exaggeration
                        # trade-off architectural visualisation tools make
                        # for thin walls/plates - and derive web_height/
                        # flange_offset from that same floored value so the
                        # three boxes still meet exactly with no gap/overlap.
                        visible_floor = max(result["width_h"], result["width_b"]) * 0.08
                        visible_flange = max(flange_thickness * ratio, visible_floor)
                        result["web_thickness"] = max(web_thickness * ratio, visible_floor)
                        result["web_height"] = max(result["width_h"] - 2.0 * visible_flange, minimum)
                        result["flange_thickness"] = visible_flange
                        result["flange_offset"] = (result["width_h"] - visible_flange) / 2.0
                return result

        width = self._number_property(properties, "width")
        height = self._number_property(properties, "height")
        if width is not None and height is not None and width > 0.0 and height > 0.0:
            # Rectangle, or any custom section that only ever stored plain
            # width/height (e.g. an RC member via apply_section_to_selection).
            return {"shape": shape or "Rectangle", "width_b": clamp(width), "width_h": clamp(height)}

        area = self._number_property(properties, "A")
        fallback = clamp(math.sqrt(area)) if area is not None and area > 0.0 else minimum
        return {"shape": shape or "", "width_b": fallback, "width_h": fallback}

    @staticmethod
    def _structural_from_view(vector: tuple[float, float, float]) -> tuple[float, float, float]:
        """Inverse of ``_view_coordinates`` - view (x, y, z) -> structural
        (x, -z, y). Needed because ``auto_reference_vector``/``local_y_z_axes``
        are defined in terms of the structural model's own up axis (global
        Z), not the Quick 3D view's Y-up space."""
        vx, vy, vz = vector
        return vx, -vz, vy

    @staticmethod
    def _quaternion_from_columns(
        col_x: tuple[float, float, float],
        col_y: tuple[float, float, float],
        col_z: tuple[float, float, float],
    ) -> tuple[float, float, float, float]:
        """Standard trace-based rotation-matrix -> quaternion conversion for
        the proper (det = +1) rotation whose columns are the three given
        orthonormal axes - unlike ``_rotation_from_y_axis``, which only pins
        down one axis and leaves the roll around it at an arbitrary minimal-
        rotation value, this fixes the full orientation."""
        m00, m10, m20 = col_x
        m01, m11, m21 = col_y
        m02, m12, m22 = col_z
        trace = m00 + m11 + m22
        if trace > 0.0:
            s = math.sqrt(trace + 1.0) * 2.0
            return 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
        if m00 > m11 and m00 > m22:
            s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
            return (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
        if m11 > m22:
            s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
            return (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        return (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s

    def _member_frame_rotation(
        self,
        direction: tuple[float, float, float],
        local_axis_angle: float,
    ) -> tuple[float, float, float, float]:
        """Full orientation for a member's rendered box/cylinder: local +Y
        follows the member's axial ``direction`` (view space, as
        ``_rotation_from_y_axis`` already did), while the roll around that
        axis now comes from the exact same ``local_y_z_axes``/
        ``auto_reference_vector``/``local_axis_angle`` math the local-axis
        preview gizmo uses (``_build_local_axis_preview``) - so a non-square
        section's width/height (and an H-section's flanges) land on the
        member's real structural y/z axes instead of an arbitrary roll.
        """
        structural_axis = self._normalized(self._structural_from_view(direction))
        if structural_axis is None:
            structural_axis = (1.0, 0.0, 0.0)
        reference = auto_reference_vector(structural_axis)
        if local_axis_angle:
            reference = rotate_about_axis(reference, structural_axis, math.radians(local_axis_angle))
        y_axis, _z_axis = local_y_z_axes(structural_axis, reference)
        col_x = self._view_coordinates(*y_axis)
        col_y = direction
        col_z = self._cross(col_x, col_y)
        return self._quaternion_from_columns(col_x, col_y, col_z)

    @staticmethod
    def _rotate_by_quaternion(
        vector: tuple[float, float, float],
        scalar: float,
        qx: float,
        qy: float,
        qz: float,
    ) -> tuple[float, float, float]:
        """``vector`` rotated by the unit quaternion (scalar, qx, qy, qz) -
        the same operation Qt.quaternion(...) applies to a Model's local
        axes in QML, used here to bake a flange's offset from the web's
        centreline into a plain world-space position ahead of time (see
        _member_parts) instead of relying on QML parent/child nesting."""
        qvx, qvy, qvz = qx, qy, qz
        vx, vy, vz = vector
        cross1 = (qvy * vz - qvz * vy, qvz * vx - qvx * vz, qvx * vy - qvy * vx)
        cross2 = (
            qvy * cross1[2] - qvz * cross1[1],
            qvz * cross1[0] - qvx * cross1[2],
            qvx * cross1[1] - qvy * cross1[0],
        )
        return (
            vx + 2.0 * scalar * cross1[0] + 2.0 * cross2[0],
            vy + 2.0 * scalar * cross1[1] + 2.0 * cross2[1],
            vz + 2.0 * scalar * cross1[2] + 2.0 * cross2[2],
        )

    @staticmethod
    def _box_part(
        tag: int,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        position: tuple[float, float, float],
        length: float,
        width_b: float,
        width_h: float,
        scalar: float,
        qx: float,
        qy: float,
        qz: float,
        color: str,
        opacity: float,
        source: str = "#Cube",
    ) -> dict[str, float | int | str]:
        return {
            "tag": tag,
            # Screen-space box selection projects both real endpoints.  The
            # rendered part itself only needs its own midpoint/orientation,
            # but those are insufficient to tell whether a drag rectangle
            # crosses the member - start/end are always the member's own
            # true endpoints, the same on every part of a multi-part member.
            "start_x": start[0],
            "start_y": start[1],
            "start_z": start[2],
            "end_x": end[0],
            "end_y": end[1],
            "end_z": end[2],
            "x": position[0],
            "y": position[1],
            "z": position[2],
            "length": length,
            "width_b": width_b,
            "width_h": width_h,
            "source": source,
            "qscalar": scalar,
            "qx": qx,
            "qy": qy,
            "qz": qz,
            "color": color,
            "opacity": opacity,
        }

    def _member_parts(
        self,
        element: Element,
        points: dict[int, tuple[float, float, float]],
        default_thickness: float,
        *,
        color: str,
        opacity: float = 1.0,
    ) -> list[dict[str, float | int | str]]:
        """One flat box/cylinder part per member, or three (web + two
        flanges) for an H/I section - matching the flat-list-of-parts
        convention every other multi-piece visual in this file already uses
        (_build_load_arrows, _build_support_parts, _local_axis_gizmo_parts):
        each part is fully self-contained (its own resolved world position),
        computed once here in Python, rather than a QML Node group nesting
        conditionally-visible Model children under a shared parent
        transform - Qt Quick 3D's Repeater3D does not reliably keep a nested
        multi-child delegate's geometry in sync with model changes (a copied
        member intermittently rendered as a bare hairline instead of its
        real cross-section), while a flat list of independent parts is
        exactly the pattern the loadArrows/gizmo parts above already rely on
        without that problem.
        """
        start = points.get(element.node_i)
        end = points.get(element.node_j)
        if start is None or end is None:
            return []
        orientation = self._member_orientation(start, end)
        if orientation is None:
            return []
        length, old_scalar, old_qx, old_qy, old_qz = orientation
        direction = tuple((end[k] - start[k]) / length for k in range(3))
        mid = (
            0.5 * (start[0] + end[0]),
            0.5 * (start[1] + end[1]),
            0.5 * (start[2] + end[2]),
        )

        is_truss = element.element_type.lower() in _TRUSS_ELEMENT_TYPES
        if is_truss:
            # A truss carries no bending orientation at all (matches
            # _build_local_axis_preview's own truss exclusion) - render it
            # as the old uniform sqrt(area) square with the old rotation,
            # unchanged, regardless of any section_shape it happens to carry.
            area = self._number_property(element.properties, "A")
            size = min(
                max(math.sqrt(area) if area is not None and area > 0.0 else 0.0, default_thickness),
                self._extent * 0.055,
            )
            return [
                self._box_part(
                    element.tag, start, end, mid, length, size, size,
                    old_scalar, old_qx, old_qy, old_qz, color, opacity,
                )
            ]

        visual = self._section_visual_dimensions(element.properties, default_thickness)
        scalar, qx, qy, qz = self._member_frame_rotation(direction, element.local_axis_angle)

        if visual["shape"] == "H/I Section" and visual.get("web_height", 0.0) > 0.0:
            flange_offset = visual["flange_offset"]
            local_z_world = self._rotate_by_quaternion((0.0, 0.0, 1.0), scalar, qx, qy, qz)
            parts = [
                self._box_part(
                    element.tag, start, end, mid, length,
                    visual["web_thickness"], visual["web_height"],
                    scalar, qx, qy, qz, color, opacity,
                )
            ]
            for sign in (1.0, -1.0):
                flange_position = tuple(
                    mid[k] + sign * flange_offset * local_z_world[k] for k in range(3)
                )
                parts.append(
                    self._box_part(
                        element.tag, start, end, flange_position, length,
                        visual["width_b"], visual["flange_thickness"],
                        scalar, qx, qy, qz, color, opacity,
                    )
                )
            return parts

        source = "#Cylinder" if visual["shape"] in {"Circle", "Pipe"} else "#Cube"
        return [
            self._box_part(
                element.tag, start, end, mid, length,
                visual["width_b"], visual["width_h"],
                scalar, qx, qy, qz, color, opacity, source=source,
            )
        ]

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
            max(
                math.sqrt(sum(value * value for value in (*load.values[:3], 0.0, 0.0)[:3])),
                math.sqrt(
                    sum(value * value for value in (*load.values[3:6], 0.0, 0.0, 0.0)[:3])
                ),
            )
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

        # mx/my/mz used to have no glyph at all here, same gap as
        # _nodal_entry_parts above (reported: "절점 하중에서 모멘트 하중의
        # 캔버스 상의 표현 아이콘이나 화살표가 없음") - reuse the same bowtie
        # "moment_head" cone pair shape, which this Repeater3D's delegate
        # already renders identically to a force arrow's shaft/head (both
        # just read shape/position/rotation/thickness/length/color).
        for load in model.nodal_loads:
            anchor = points.get(load.node_tag)
            if anchor is None:
                continue
            padded = (*load.values, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            mx, my, mz = padded[3], padded[4], padded[5]
            moment_magnitude = math.sqrt(mx * mx + my * my + mz * mz)
            if moment_magnitude <= 1.0e-12:
                continue
            moment_direction = self._view_coordinates(
                mx / moment_magnitude, my / moment_magnitude, mz / moment_magnitude
            )
            common = {
                "tag": load.node_tag,
                "kind": "nodal",
                "load_type": "nodal_moment",
                "color": _LOAD_CASE_COLORS[load.case_type],
                "case_type": load.case_type.value,
                "pattern_tag": load.pattern_tag if load.pattern_tag is not None else -1,
            }
            parts.extend(
                self._moment_glyph_parts(
                    anchor, moment_direction, moment_magnitude, maximum_magnitude, 1.0, common
                )
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

    def _rebuild_load_entry_parts(self) -> None:
        model = self._last_model
        if model is None or not self._points:
            self._load_entry_parts = []
            return
        self._load_entry_parts = self._build_load_entry_parts(model, self._points)

    def _build_load_entry_parts(
        self,
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
    ) -> list[dict[str, float | int | str]]:
        """Case-based Loads tab glyphs - filtered by the Display combo's mode
        exactly like ``create_load_case_from_combination`` filters/scales for
        its own "materialize a combination" step, so this preview can never
        show something that step would not also produce.
        """
        mode = self._load_entry_mode
        if mode == "hidden":
            return []

        visible: list[tuple[LoadEntry, float]] = []
        if mode == "combination":
            combination = self._load_combinations.get(self._load_entry_active_combination_id or "")
            if combination is None:
                return []
            for entry in self._load_entries.values():
                if entry.hidden:
                    continue
                case = self._load_cases.get(entry.case_id)
                if case is None:
                    continue
                factor = combination.factor_for(case.kind)
                if factor == 0.0:
                    continue
                visible.append((entry, factor))
        else:
            active_case_id = self._load_entry_active_case_id
            for entry in self._load_entries.values():
                if entry.hidden:
                    continue
                if mode == "case" and entry.case_id != active_case_id:
                    continue
                visible.append((entry, 1.0))
        if not visible:
            return []

        # Self-weight's factor_x/y/z are direction cosines (typically
        # magnitude ~1), not a force in the same units as everything else -
        # mixing it into the shared auto-scale would make real force arrows
        # collapse toward the small end whenever a self-weight entry exists.
        # It gets its own fixed length in _self_weight_entry_parts instead.
        magnitudes = [
            self._load_entry_magnitude(entry) * abs(factor)
            for entry, factor in visible
            if entry.kind != "self_weight"
        ]
        maximum_magnitude = max(magnitudes, default=0.0)
        scale = max(self._load_entry_scale, 0.01)

        parts: list[dict[str, float | int | str]] = []
        for entry, factor in visible:
            case = self._load_cases.get(entry.case_id)
            color = _LOAD_CASE_COLORS[case.kind if case is not None else LoadCaseKind.UNCLASSIFIED]
            common = {
                "tag": entry.id,
                "case_id": entry.case_id,
                "entry_kind": entry.kind,
                "color": color,
            }
            parts.extend(
                self._load_entry_glyph_parts(entry, factor, common, model, points, maximum_magnitude, scale)
            )
        return parts

    @staticmethod
    def _load_entry_magnitude(entry: LoadEntry) -> float:
        payload = entry.payload
        if isinstance(payload, NodalLoadEntry):
            # Force and moment are different units, but this auto-scale pool
            # already mixes them at face value for member_point/member_moment
            # (both share MemberPointLoadEntry.value) - matching that here
            # means a moment-only nodal load (fx=fy=fz=0) still contributes
            # its own size to the shared scale instead of reading as 0 and
            # always rendering at the smallest glyph size regardless of how
            # large the moment actually is.
            force_magnitude = math.sqrt(payload.fx**2 + payload.fy**2 + payload.fz**2)
            moment_magnitude = math.sqrt(payload.mx**2 + payload.my**2 + payload.mz**2)
            return max(force_magnitude, moment_magnitude)
        if isinstance(payload, MemberPointLoadEntry):
            return abs(payload.value)
        if isinstance(payload, MemberDistributedLoadEntry):
            return max(abs(payload.start_value), abs(payload.end_value))
        if isinstance(payload, FloorLoadEntry):
            return abs(payload.magnitude)
        return 0.0  # SelfWeightEntry - excluded from auto-scale, see caller

    def _load_entry_glyph_parts(
        self,
        entry: LoadEntry,
        factor: float,
        common: dict[str, float | int | str],
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
        maximum_magnitude: float,
        scale: float,
    ) -> list[dict[str, float | int | str]]:
        payload = entry.payload
        if entry.kind == "nodal" and isinstance(payload, NodalLoadEntry):
            return self._nodal_entry_parts(entry, payload, factor, common, points, maximum_magnitude, scale)
        if entry.kind in ("member_point", "member_moment") and isinstance(payload, MemberPointLoadEntry):
            return self._member_point_entry_parts(
                entry, payload, factor, common, model, points, maximum_magnitude, scale
            )
        if entry.kind in ("member_uniform", "member_linear", "member_partial") and isinstance(
            payload, MemberDistributedLoadEntry
        ):
            return self._member_distributed_entry_parts(
                entry, payload, factor, common, model, points, maximum_magnitude, scale
            )
        if entry.kind == "floor" and isinstance(payload, FloorLoadEntry):
            return self._floor_entry_parts(entry, payload, factor, common, points, maximum_magnitude, scale)
        if entry.kind == "self_weight" and isinstance(payload, SelfWeightEntry):
            return self._self_weight_entry_parts(entry, payload, common, model, points, scale)
        return []

    def _nodal_entry_parts(
        self,
        entry: LoadEntry,
        payload: NodalLoadEntry,
        factor: float,
        common: dict[str, float | int | str],
        points: dict[int, tuple[float, float, float]],
        maximum_magnitude: float,
        scale: float,
    ) -> list[dict[str, float | int | str]]:
        """fx/fy/fz become an arrow; mx/my/mz become the same bowtie moment
        glyph a member_moment load already uses (_moment_glyph_parts) - a
        nodal moment used to have no glyph at all here (reported: "절점
        하중에서 모멘트 하중의 캔버스 상의 표현 아이콘이나 화살표가 없음")."""
        parts: list[dict[str, float | int | str]] = []
        fx, fy, fz = payload.fx * factor, payload.fy * factor, payload.fz * factor
        force_magnitude = math.sqrt(fx * fx + fy * fy + fz * fz)
        if force_magnitude > 1.0e-12:
            direction = self._view_coordinates(
                fx / force_magnitude, fy / force_magnitude, fz / force_magnitude
            )
            arrow_length = (
                max(self._extent * 0.17, 0.06)
                * self._load_scale(force_magnitude, maximum_magnitude)
                * scale
            )
            shaft_thickness = max(self._default_thickness * 0.55, 0.009)
            for node_tag in entry.target:
                anchor = points.get(node_tag)
                if anchor is None:
                    continue
                tip = tuple(anchor[index] - direction[index] * self._node_radius for index in range(3))
                parts.extend(
                    self._arrow_pair(tip, direction, arrow_length, shaft_thickness, common, force_magnitude)
                )

        mx, my, mz = payload.mx * factor, payload.my * factor, payload.mz * factor
        moment_magnitude = math.sqrt(mx * mx + my * my + mz * mz)
        if moment_magnitude > 1.0e-12:
            moment_direction = self._view_coordinates(
                mx / moment_magnitude, my / moment_magnitude, mz / moment_magnitude
            )
            for node_tag in entry.target:
                anchor = points.get(node_tag)
                if anchor is None:
                    continue
                parts.extend(
                    self._moment_glyph_parts(
                        anchor, moment_direction, moment_magnitude, maximum_magnitude, scale, common
                    )
                )
        return parts

    def _member_local_axes(
        self,
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
        element_tag: int,
    ) -> tuple[
        Element,
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] | None:
        """(element, view-space start, view-space end, structural-space
        local x/y/z) - the same construction ``_build_element_load_arrows``
        uses, factored out so every member-load entry kind shares it."""
        element = model.elements.get(element_tag)
        if element is None:
            return None
        node_i = model.nodes.get(element.node_i)
        node_j = model.nodes.get(element.node_j)
        start = points.get(element.node_i)
        end = points.get(element.node_j)
        if node_i is None or node_j is None or start is None or end is None:
            return None
        local_x = self._normalized((node_j.x - node_i.x, node_j.y - node_i.y, node_j.z - node_i.z))
        if local_x is None:
            return None
        reference = (0.0, 0.0, 1.0) if abs(local_x[2]) < 0.99 else (1.0, 0.0, 0.0)
        local_y = self._normalized(self._cross(reference, local_x))
        if local_y is None:
            return None
        local_z = self._cross(local_x, local_y)
        return element, start, end, local_x, local_y, local_z

    def _member_tip_offset(self, element: Element) -> float:
        """Pull an arrow's tip off the member's rendered surface, mirroring
        ``_build_element_load_arrows``'s own clearance math."""
        area = self._number_property(element.properties, "A")
        section_size = math.sqrt(area) if area is not None and area > 0.0 else 0.0
        member_half_thickness = min(max(section_size, self._default_thickness), self._extent * 0.055) / 2
        visual_clearance = max(self._default_thickness * 0.1, self._extent * 0.0015)
        return member_half_thickness + visual_clearance

    @staticmethod
    def _position_fraction(position: float, position_unit: str, member_length: float) -> float:
        fraction = position / member_length if position_unit == "length" and member_length > 1.0e-9 else position
        return min(max(fraction, 0.0), 1.0)

    def _member_point_entry_parts(
        self,
        entry: LoadEntry,
        payload: MemberPointLoadEntry,
        factor: float,
        common: dict[str, float | int | str],
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
        maximum_magnitude: float,
        scale: float,
    ) -> list[dict[str, float | int | str]]:
        axis_index = {"x": 0, "y": 1, "z": 2}.get(payload.direction.lower())
        value = payload.value * factor
        if axis_index is None or abs(value) <= 1.0e-12:
            return []
        parts: list[dict[str, float | int | str]] = []
        for element_tag in entry.target:
            axes = self._member_local_axes(model, points, element_tag)
            if axes is None:
                continue
            element, start, end, local_x, local_y, local_z = axes
            node_i, node_j = model.nodes[element.node_i], model.nodes[element.node_j]
            member_length = math.sqrt(
                (node_j.x - node_i.x) ** 2 + (node_j.y - node_i.y) ** 2 + (node_j.z - node_i.z) ** 2
            )
            fraction = self._position_fraction(payload.position, payload.position_unit, member_length)
            member_point = tuple(start[index] + (end[index] - start[index]) * fraction for index in range(3))
            axis_vector = (local_x, local_y, local_z)[axis_index]
            sign = 1.0 if value >= 0.0 else -1.0
            direction = self._view_coordinates(*(component * sign for component in axis_vector))
            magnitude = abs(value)
            if entry.kind == "member_moment":
                parts.extend(
                    self._moment_glyph_parts(member_point, direction, magnitude, maximum_magnitude, scale, common)
                )
            else:
                arrow_length = (
                    max(self._extent * 0.11, 0.05) * self._load_scale(magnitude, maximum_magnitude) * scale
                )
                shaft_thickness = max(self._default_thickness * 0.45, 0.008)
                tip_offset = self._member_tip_offset(element)
                tip = tuple(member_point[index] - direction[index] * tip_offset for index in range(3))
                parts.extend(self._arrow_pair(tip, direction, arrow_length, shaft_thickness, common, magnitude))
        return parts

    def _moment_glyph_parts(
        self,
        center: tuple[float, float, float],
        axis_direction: tuple[float, float, float],
        magnitude: float,
        maximum_magnitude: float,
        scale: float,
        common: dict[str, float | int | str],
    ) -> list[dict[str, float | int | str]]:
        """A moment has no natural "arrow" shape without a torus primitive -
        two cones based at the same point and pointing away from each other
        along the moment axis (a "bowtie") reads as clearly distinct from a
        translational-force arrow while reusing only shapes this scene
        already renders."""
        half_length = max(self._extent * 0.05, 0.022) * self._load_scale(magnitude, maximum_magnitude) * scale
        thickness = max(self._default_thickness * 1.1, 0.018)
        parts = []
        for direction in (axis_direction, tuple(-component for component in axis_direction)):
            scalar, qx, qy, qz = self._rotation_from_y_axis(direction)
            parts.append(
                {
                    **common,
                    "role": "moment_head",
                    "shape": "#Cone",
                    "magnitude": magnitude,
                    "x": center[0],
                    "y": center[1],
                    "z": center[2],
                    "length": half_length,
                    "thickness": thickness,
                    "qscalar": scalar,
                    "qx": qx,
                    "qy": qy,
                    "qz": qz,
                }
            )
        return parts

    def _member_distributed_entry_parts(
        self,
        entry: LoadEntry,
        payload: MemberDistributedLoadEntry,
        factor: float,
        common: dict[str, float | int | str],
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
        maximum_magnitude: float,
        scale: float,
    ) -> list[dict[str, float | int | str]]:
        """Several arrows across the loaded span (not just one representative
        arrow) with a connecting line through their tails - for a linearly-
        varying load the tails trace the classic sloped/trapezoidal outline
        because each arrow's own length already reflects its own magnitude.
        """
        axis_index = {"x": 0, "y": 1, "z": 2}.get(payload.direction.lower())
        start_value, end_value = payload.start_value * factor, payload.end_value * factor
        if axis_index is None or (abs(start_value) <= 1.0e-12 and abs(end_value) <= 1.0e-12):
            return []
        parts: list[dict[str, float | int | str]] = []
        for element_tag in entry.target:
            axes = self._member_local_axes(model, points, element_tag)
            if axes is None:
                continue
            element, start, end, local_x, local_y, local_z = axes
            node_i, node_j = model.nodes[element.node_i], model.nodes[element.node_j]
            member_length = math.sqrt(
                (node_j.x - node_i.x) ** 2 + (node_j.y - node_i.y) ** 2 + (node_j.z - node_i.z) ** 2
            )
            start_fraction = self._position_fraction(payload.start_position, payload.position_unit, member_length)
            end_fraction = self._position_fraction(payload.end_position, payload.position_unit, member_length)
            if end_fraction < start_fraction:
                start_fraction, end_fraction = end_fraction, start_fraction
            span = end_fraction - start_fraction
            axis_vector = (local_x, local_y, local_z)[axis_index]
            tip_offset = self._member_tip_offset(element)
            shaft_thickness = max(self._default_thickness * 0.32, 0.006)
            sample_count = 5 if span > 1.0e-6 else 1

            tails: list[tuple[float, float, float]] = []
            for index in range(sample_count):
                step = 0.0 if sample_count == 1 else index / (sample_count - 1)
                fraction = start_fraction + span * step
                local_value = start_value + (end_value - start_value) * step
                magnitude = abs(local_value)
                if magnitude <= 1.0e-12:
                    continue
                sign = 1.0 if local_value >= 0.0 else -1.0
                direction = self._view_coordinates(*(component * sign for component in axis_vector))
                member_point = tuple(
                    start[coord] + (end[coord] - start[coord]) * fraction for coord in range(3)
                )
                arrow_length = (
                    max(self._extent * 0.07, 0.035) * self._load_scale(magnitude, maximum_magnitude) * scale
                )
                tip = tuple(member_point[coord] - direction[coord] * tip_offset for coord in range(3))
                parts.extend(self._arrow_pair(tip, direction, arrow_length, shaft_thickness, common, magnitude))
                tails.append(tuple(tip[coord] - direction[coord] * arrow_length for coord in range(3)))
            parts.extend(self._connector_segments(tails, shaft_thickness * 0.42, common))
        return parts

    def _connector_segments(
        self,
        points_sequence: list[tuple[float, float, float]],
        thickness: float,
        common: dict[str, float | int | str],
    ) -> list[dict[str, float | int | str]]:
        parts: list[dict[str, float | int | str]] = []
        for start, end in zip(points_sequence, points_sequence[1:]):
            orientation = self._member_orientation(start, end)
            if orientation is None:
                continue
            length, scalar, qx, qy, qz = orientation
            mid = tuple(0.5 * (start[index] + end[index]) for index in range(3))
            parts.append(
                {
                    **common,
                    "role": "distribution_line",
                    "shape": "#Cylinder",
                    "magnitude": 0.0,
                    "x": mid[0],
                    "y": mid[1],
                    "z": mid[2],
                    "length": length,
                    "thickness": thickness,
                    "qscalar": scalar,
                    "qx": qx,
                    "qy": qy,
                    "qz": qz,
                }
            )
        return parts

    def _floor_entry_parts(
        self,
        entry: LoadEntry,
        payload: FloorLoadEntry,
        factor: float,
        common: dict[str, float | int | str],
        points: dict[int, tuple[float, float, float]],
        maximum_magnitude: float,
        scale: float,
    ) -> list[dict[str, float | int | str]]:
        """No beam-load distribution is computed yet (``FloorLoadEntry``'s
        own docstring) - the boundary loop plus one centroid arrow is a
        preview of *where* the floor panel is and *which way* it loads,
        not the (still unimplemented) tributary distribution itself."""
        boundary = [points[tag] for tag in entry.target if tag in points]
        if len(boundary) < 3:
            return []
        thickness = max(self._default_thickness * 0.3, 0.006)
        parts = self._connector_segments([*boundary, boundary[0]], thickness, common)
        magnitude = abs(payload.magnitude * factor)
        if magnitude <= 1.0e-12:
            return parts
        direction = self._view_coordinates(*self._floor_direction_vector(payload.direction))
        centroid = tuple(sum(point[index] for point in boundary) / len(boundary) for index in range(3))
        arrow_length = max(self._extent * 0.13, 0.06) * self._load_scale(magnitude, maximum_magnitude) * scale
        shaft_thickness = max(self._default_thickness * 0.4, 0.008)
        parts.extend(self._arrow_pair(centroid, direction, arrow_length, shaft_thickness, common, magnitude))
        return parts

    @staticmethod
    def _floor_direction_vector(direction: str) -> tuple[float, float, float]:
        return {
            "-z": (0.0, 0.0, -1.0),
            "+z": (0.0, 0.0, 1.0),
            "-x": (-1.0, 0.0, 0.0),
            "+x": (1.0, 0.0, 0.0),
            "-y": (0.0, -1.0, 0.0),
            "+y": (0.0, 1.0, 0.0),
        }.get(direction, (0.0, 0.0, -1.0))

    def _self_weight_entry_parts(
        self,
        entry: LoadEntry,
        payload: SelfWeightEntry,
        common: dict[str, float | int | str],
        model: StructuralModel,
        points: dict[int, tuple[float, float, float]],
        scale: float,
    ) -> list[dict[str, float | int | str]]:
        """A fixed-length marker, not scaled against other loads' magnitudes
        - factor_x/y/z are direction cosines (typically ~1), not a force in
        the same units as everything else (see _build_load_entry_parts)."""
        direction_model = self._normalized((payload.factor_x, payload.factor_y, payload.factor_z))
        if direction_model is None:
            return []
        direction = self._view_coordinates(*direction_model)
        length = max(self._extent * 0.12, 0.05) * scale
        thickness = max(self._default_thickness * 0.4, 0.008)
        if payload.apply_to_all or not entry.target:
            # One marker above the whole model rather than one per member -
            # "every member, always" is exactly the case where per-member
            # arrows would swamp the scene without adding information.
            top = max((point[1] for point in points.values()), default=0.0)
            anchor = (self._center[0], top + self._extent * 0.08, self._center[2])
            return self._arrow_pair(anchor, direction, length, thickness, common, 1.0)
        parts: list[dict[str, float | int | str]] = []
        for element_tag in entry.target:
            axes = self._member_local_axes(model, points, element_tag)
            if axes is None:
                continue
            _element, start, end, *_rest = axes
            mid = tuple(0.5 * (start[index] + end[index]) for index in range(3))
            parts.extend(self._arrow_pair(mid, direction, length, thickness, common, 1.0))
        return parts

    def _arrow_pair(
        self,
        tip: tuple[float, float, float],
        direction: tuple[float, float, float],
        arrow_length: float,
        shaft_thickness: float,
        common: dict[str, float | int | str],
        magnitude: float,
    ) -> list[dict[str, float | int | str]]:
        """One shaft + one head part, sharing every load-entry kind's arrow
        construction (see _build_load_arrows for why shaft/head are always
        two independent, self-positioned parts rather than a parent/child
        pair)."""
        shaft_length = arrow_length * 0.68
        head_length = arrow_length - shaft_length
        head_thickness = shaft_thickness * 2.25
        tail = tuple(tip[index] - direction[index] * arrow_length for index in range(3))
        shaft_mid = tuple(tail[index] + direction[index] * shaft_length / 2 for index in range(3))
        head_base = tuple(tail[index] + direction[index] * shaft_length for index in range(3))
        scalar, qx, qy, qz = self._rotation_from_y_axis(direction)
        rotation = {"qscalar": scalar, "qx": qx, "qy": qy, "qz": qz}
        return [
            {
                **common,
                "role": "shaft",
                "shape": "#Cylinder",
                "magnitude": magnitude,
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
                "magnitude": magnitude,
                "x": head_base[0],
                "y": head_base[1],
                "z": head_base[2],
                "length": head_length,
                "thickness": head_thickness,
                **rotation,
            },
        ]

    def _clear(self) -> None:
        self._time_history_deformation_active = False
        self._deformed_node_by_tag = {}
        self._deformation_member_records = []
        self._deformation_revision = 0
        self._torsion_marker_active = False
        self._torsion_markers = []
        self._torsion_revision = 0
        self._nodes = []
        self._members = []
        self._ghost_nodes = []
        self._ghost_members = []
        self._load_arrows = []
        self._support_parts = []
        self._local_axis_gizmos = []
        self._load_entry_parts = []
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
