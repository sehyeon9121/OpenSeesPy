"""Scene-drawing and hit-testing methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItemGroup, QGraphicsLineItem

from openframe.core.domain import BoundaryCondition, Node, UniformElementLoad


class _RenderingMixin:
    def _changed(self) -> None:
        self._redraw()
        self.model_changed.emit()

    def _projected_node(self, node: Node) -> Node:
        """The node's position on the active plane, as a drawable (u, v, 0) node.

        Every scene-drawing helper only ever reads ``.x``/``.y``; feeding them this
        projection instead of the real node is what lets them stay plane-agnostic.
        In 2D mode the plane is the identity ground plane, so this is ``node``
        itself in every case that matters (z is always 0 already).
        """
        u, v = self._uv(node)
        return Node(node.tag, u, v, 0.0, node.ndf)

    def _redraw(self) -> None:
        self.scene_model.clear()
        scale = self._DRAW_SCALE
        plane_nodes = self._plane_node_tags()
        for tag in self._plane_element_tags(plane_nodes):
            element = self.elements[tag]
            a = self._projected_node(self.nodes[element.node_i])
            b = self._projected_node(self.nodes[element.node_j])
            selected = tag in self.selected_elements or self._selected == ("element", tag)
            item = self.scene_model.addLine(
                a.x * scale,
                -a.y * scale,
                b.x * scale,
                -b.y * scale,
                QPen(QColor("#ef4444" if selected else "#174ea6"), 4),
            )
            item.setData(0, ("element", tag))
            if element.moment_release_i:
                self._draw_end_release(a, b, scale)
            if element.moment_release_j:
                self._draw_end_release(b, a, scale)
            if tag in self.element_loads:
                self._draw_uniform_load(a, b, self.element_loads[tag], scale)
        for tag in plane_nodes:
            node = self._projected_node(self.nodes[tag])
            selected = tag in self.selected_nodes or self._selected == ("node", tag)
            if tag in self.hinge_nodes:
                # A hinge (절점) is drawn as the textbook symbol: an open ring
                # around the joint with a small pin dot at its centre, not just a
                # colour change on the same filled dot a rigid node (노드) uses —
                # the two must read as different symbols at a glance, not
                # different shades of the same one.
                accent = QColor("#ef4444" if selected else "#f97316")
                ring = QGraphicsEllipseItem(-9, -9, 18, 18)
                ring.setPos(node.x * scale, -node.y * scale)
                ring.setBrush(QColor("#fff7ed"))
                ring.setPen(QPen(accent, 3))
                ring.setData(0, ("node", tag))
                self.scene_model.addItem(ring)
                pin = QGraphicsEllipseItem(-3, -3, 6, 6)
                pin.setPos(node.x * scale, -node.y * scale)
                pin.setBrush(accent)
                pin.setPen(QPen(accent, 0))
                pin.setData(0, ("node", tag))
                self.scene_model.addItem(pin)
            else:
                item = QGraphicsEllipseItem(-6, -6, 12, 12)
                item.setPos(node.x * scale, -node.y * scale)
                item.setBrush(QColor("#dbeafe" if selected else "#174ea6"))
                item.setPen(QPen(QColor("#174ea6"), 2))
                item.setData(0, ("node", tag))
                self.scene_model.addItem(item)
            # A plain node ("N") is a rigid connection; a hinge is a "절점"
            # (joint) where rotation is released. The label says which one this
            # is at a glance, not just the marker shape/colour.
            label_text = f"절점{tag}" if tag in self.hinge_nodes else f"N{tag}"
            self.scene_model.addText(label_text).setPos(
                node.x * scale + 7, -node.y * scale - 22
            )
            if tag in self.boundaries:
                self._draw_support(node, self.boundaries[tag], scale)
            if tag in self.nodal_loads:
                self._draw_nodal_load(node, self.nodal_loads[tag].values, scale)
        if self._member_start in plane_nodes:
            node = self._projected_node(self.nodes[self._member_start])
            self.scene_model.addEllipse(
                node.x * scale - 10, -node.y * scale - 10, 20, 20, QPen(QColor("#22c55e"), 2)
            )
            if self._preview_point is not None:
                preview_pen = QPen(QColor("#22c55e"), 2, Qt.PenStyle.DashLine)
                self.scene_model.addLine(
                    node.x * scale,
                    -node.y * scale,
                    self._preview_point.x(),
                    self._preview_point.y(),
                    preview_pen,
                )
                snapped = self._node_near_scene(self._preview_point)
                if snapped is not None:
                    target = self._projected_node(self.nodes[snapped])
                    self.scene_model.addEllipse(
                        target.x * scale - 11,
                        -target.y * scale - 11,
                        22,
                        22,
                        QPen(QColor("#22c55e"), 2),
                    )
        anchor_point = self.chain_anchor
        if anchor_point is not None and self._preview_point is not None:
            anchor = self._scene_point(*anchor_point)
            self.scene_model.addLine(
                anchor.x(),
                anchor.y(),
                self._preview_point.x(),
                self._preview_point.y(),
                QPen(QColor("#22c55e"), 2, Qt.PenStyle.DashLine),
            )
            measure = self.pending_length_and_angle()
            if measure is not None:
                readout = self.scene_model.addText(f"{measure[0]:.4g} m   {measure[1]:.1f}°")
                readout.setDefaultTextColor(QColor("#16a34a"))
                readout.setPos(self._preview_point + QPointF(12, -32))
        if self.mode == "draw" and self._snap is not None and self._snap.label:
            marker = self._scene_point(self._snap.x, self._snap.y)
            self.scene_model.addRect(
                marker.x() - 6, marker.y() - 6, 12, 12, QPen(QColor("#0f766e"), 2)
            )
            hint = self.scene_model.addText(self._snap.label)
            hint.setDefaultTextColor(QColor("#0f766e"))
            hint.setPos(marker + QPointF(10, 2))
        if self._drag_start is not None and self._drag_current is not None:
            crossing = self._drag_current.x() < self._drag_start.x()
            selection_color = QColor("#16a34a" if crossing else "#2563eb")
            self.scene_model.addRect(
                QRectF(self._drag_start, self._drag_current).normalized(),
                QPen(selection_color, 1, Qt.PenStyle.DashLine),
                QColor(selection_color.red(), selection_color.green(), selection_color.blue(), 35),
            )
        if self._preview_midpoint is not None:
            _, midpoint, position = self._preview_midpoint
            self.scene_model.addEllipse(
                midpoint.x() - 10,
                midpoint.y() - 10,
                20,
                20,
                QPen(QColor("#22c55e"), 2),
                QColor(34, 197, 94, 45),
            )
            station_label = "MID" if abs(position - 0.5) < 1.0e-9 else f"{position:.3g}L"
            label = self.scene_model.addText(station_label)
            label.setDefaultTextColor(QColor("#16a34a"))
            label.setPos(midpoint + QPointF(10, -25))

    def _nearest_node_3d(self, point: tuple[float, float, float]) -> int | None:
        return next(
            (
                tag
                for tag, node in self.nodes.items()
                if abs(node.x - point[0]) < 1.0e-9
                and abs(node.y - point[1]) < 1.0e-9
                and abs(node.z - point[2]) < 1.0e-9
            ),
            None,
        )

    def _node_near_scene(self, point: QPointF, tolerance: float = 16.0) -> int | None:
        """Nearest node to a scene point, restricted to nodes on the active plane."""
        candidates = []
        for tag, node in self.nodes.items():
            if not self._on_plane(node):
                continue
            u, v = self._uv(node)
            candidates.append(
                (
                    (u * self._DRAW_SCALE - point.x()) ** 2
                    + (-v * self._DRAW_SCALE - point.y()) ** 2,
                    tag,
                )
            )
        distance, tag = min(candidates, default=(float("inf"), None))
        return tag if distance <= tolerance * tolerance else None

    def _member_near_scene(self, point: QPointF, tolerance: float = 14.0) -> int | None:
        candidates: list[tuple[float, int]] = []
        for tag in self._plane_element_tags():
            element = self.elements[tag]
            start_node = self.nodes[element.node_i]
            end_node = self.nodes[element.node_j]
            start_u, start_v = self._uv(start_node)
            end_u, end_v = self._uv(end_node)
            start = QPointF(start_u * self._DRAW_SCALE, -start_v * self._DRAW_SCALE)
            end = QPointF(end_u * self._DRAW_SCALE, -end_v * self._DRAW_SCALE)
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length_squared = dx * dx + dy * dy
            if length_squared == 0.0:
                continue
            station = max(
                0.0,
                min(1.0, ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy) / length_squared),
            )
            projected = QPointF(start.x() + station * dx, start.y() + station * dy)
            distance = (point.x() - projected.x()) ** 2 + (point.y() - projected.y()) ** 2
            candidates.append((distance, tag))
        distance, tag = min(candidates, default=(float("inf"), None))
        return tag if distance <= tolerance * tolerance else None

    def _member_station_near_scene(
        self, point: QPointF, tolerance: float = 14.0
    ) -> tuple[int, float, QPointF] | None:
        candidates: list[tuple[float, int, float, QPointF, float]] = []
        for tag in self._plane_element_tags():
            element = self.elements[tag]
            a = self.nodes[element.node_i]
            b = self.nodes[element.node_j]
            a_u, a_v = self._uv(a)
            b_u, b_v = self._uv(b)
            start = QPointF(a_u * self._DRAW_SCALE, -a_v * self._DRAW_SCALE)
            end = QPointF(b_u * self._DRAW_SCALE, -b_v * self._DRAW_SCALE)
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length_squared = dx * dx + dy * dy
            if length_squared == 0.0:
                continue
            position = max(
                0.0,
                min(
                    1.0,
                    ((point.x() - start.x()) * dx + (point.y() - start.y()) * dy)
                    / length_squared,
                ),
            )
            if abs(position - 0.5) * length_squared**0.5 <= tolerance:
                position = 0.5
            projected = QPointF(start.x() + position * dx, start.y() + position * dy)
            distance = (point.x() - projected.x()) ** 2 + (point.y() - projected.y()) ** 2
            candidates.append((distance, tag, position, projected, length_squared))
        distance, tag, position, projected, _ = min(
            candidates, default=(float("inf"), 0, 0.0, QPointF(), 0.0)
        )
        if distance > tolerance * tolerance or position in {0.0, 1.0}:
            return None
        return tag, position, projected

    def _toggle_selection(
        self, key: tuple[str, int], modifiers: Qt.KeyboardModifier
    ) -> None:
        """Clicking something the active selection filter excludes (e.g. a
        node while 등분포하중's element-only filter is narrowed) must be a
        true no-op — it used to clear whatever was already validly selected
        first and only *then* discover the click didn't qualify, so picking
        the wrong kind of item by accident silently wiped out a member
        selection you were still in the middle of applying a load to.
        """
        kind, tag = key
        if self.selection_filter == "nodes" and kind != "node":
            return
        if self.selection_filter == "elements" and kind != "element":
            return
        if not modifiers & Qt.KeyboardModifier.ControlModifier:
            self.selected_nodes.clear()
            self.selected_elements.clear()
        target = self.selected_nodes if kind == "node" else self.selected_elements
        if tag in target and modifiers & Qt.KeyboardModifier.ControlModifier:
            target.remove(tag)
        else:
            target.add(tag)
        self._selected = key
        self._selection_changed()

    def _select_in_rect(self, rectangle: QRectF, *, crossing: bool) -> None:
        """Drag-select — restricted to what the active plane actually shows.

        Selecting something invisible (a node from another storey) would be a
        trap: it looks unselected but the next delete or support click would
        silently reach it anyway.
        """
        scale = self._DRAW_SCALE
        plane_nodes = self._plane_node_tags()
        if self.selection_filter in {"all", "nodes"}:
            for tag in plane_nodes:
                u, v = self._uv(self.nodes[tag])
                if rectangle.contains(QPointF(u * scale, -v * scale)):
                    self.selected_nodes.add(tag)
        if self.selection_filter in {"all", "elements"}:
            for tag in self._plane_element_tags(plane_nodes):
                element = self.elements[tag]
                a, b = self.nodes[element.node_i], self.nodes[element.node_j]
                a_u, a_v = self._uv(a)
                b_u, b_v = self._uv(b)
                start = QPointF(a_u * scale, -a_v * scale)
                end = QPointF(b_u * scale, -b_v * scale)
                fully_inside = rectangle.contains(start) and rectangle.contains(end)
                member_line = QLineF(start, end)
                edges = (
                    QLineF(rectangle.topLeft(), rectangle.topRight()),
                    QLineF(rectangle.topRight(), rectangle.bottomRight()),
                    QLineF(rectangle.bottomRight(), rectangle.bottomLeft()),
                    QLineF(rectangle.bottomLeft(), rectangle.topLeft()),
                )
                intersects = rectangle.contains(start) or rectangle.contains(end)
                if not intersects:
                    # QLineF.intersects() reports UnboundedIntersection whenever the
                    # two *infinite* lines would cross somewhere, even if that point
                    # is nowhere near either actual segment - checking only "!=
                    # NoIntersection" therefore matched almost every non-parallel
                    # member against almost every rectangle edge, selecting the
                    # entire model on any crossing-mode drag. BoundedIntersection is
                    # the one value that means the two finite segments actually cross.
                    intersects = any(
                        member_line.intersects(edge)[0]
                        == QLineF.IntersectionType.BoundedIntersection
                        for edge in edges
                    )
                if fully_inside or (crossing and intersects):
                    self.selected_elements.add(tag)

    def _draw_support(self, node: Node, boundary: BoundaryCondition, scale: float) -> None:
        """Draw the support glyph rotated to the boundary condition's incline angle.

        The glyph is built at the origin in an unrotated local frame — the same
        shape as before this method learned about angles — then the whole group is
        positioned and rotated once. Qt rotates clockwise for a positive angle in
        its y-down scene space, which is exactly the on-screen direction a
        counter-clockwise angle in model space (y-up) needs, so ``setRotation``
        takes the boundary's angle unchanged.
        """
        pen = QPen(QColor("#334155"), 2)
        group = QGraphicsItemGroup()
        normalized = tuple(boundary.restraints[:3])
        if normalized == (True, True, True):
            group.addToGroup(self._line_item(-14, 8, 14, 8, pen))
            for offset in (-12, -6, 0, 6, 12):
                group.addToGroup(self._line_item(offset, 8, offset - 5, 16, pen))
        elif normalized == (True, False, False):
            group.addToGroup(self._line_item(8, -12, 8, 12, pen))
            group.addToGroup(self._line_item(0, 0, 8, -10, pen))
            group.addToGroup(self._line_item(0, 0, 8, 10, pen))
            group.addToGroup(self._ellipse_item(10, -7, 4, 4, pen))
            group.addToGroup(self._ellipse_item(10, 3, 4, 4, pen))
        else:
            group.addToGroup(self._line_item(0, 0, -11, 17, pen))
            group.addToGroup(self._line_item(0, 0, 11, 17, pen))
            group.addToGroup(self._line_item(-11, 17, 11, 17, pen))
            if normalized == (False, True, False):
                group.addToGroup(self._ellipse_item(-8, 18, 5, 5, pen))
                group.addToGroup(self._ellipse_item(3, 18, 5, 5, pen))
        group.setPos(node.x * scale, -node.y * scale)
        group.setRotation(boundary.angle)
        self.scene_model.addItem(group)
        if boundary.is_inclined:
            label = self.scene_model.addText(f"{boundary.angle:g}°")
            label.setDefaultTextColor(QColor("#0f766e"))
            label.setPos(node.x * scale + 16, -node.y * scale + 14)

    @staticmethod
    def _line_item(x1: float, y1: float, x2: float, y2: float, pen: QPen) -> QGraphicsLineItem:
        item = QGraphicsLineItem(x1, y1, x2, y2)
        item.setPen(pen)
        return item

    @staticmethod
    def _ellipse_item(x: float, y: float, w: float, h: float, pen: QPen) -> QGraphicsEllipseItem:
        item = QGraphicsEllipseItem(x, y, w, h)
        item.setPen(pen)
        return item

    def _draw_nodal_load(self, node: Node, values: tuple[float, ...], scale: float) -> None:
        fx, fy, mz = (*values, 0.0, 0.0, 0.0)[:3]
        origin = QPointF(node.x * scale, -node.y * scale)
        if fx:
            direction = -1.0 if fx > 0 else 1.0
            self._draw_arrow(origin + QPointF(direction * 38, 0), origin, f"Fx {fx:g}")
        if fy:
            direction = 1.0 if fy > 0 else -1.0
            self._draw_arrow(origin + QPointF(0, direction * 38), origin, f"Fy {fy:g}")
        if mz:
            # mz itself stays the standard right-hand-rule value (+ = CCW
            # about +Z) the solver actually uses - only the printed number is
            # flipped to the 시계방향(+)/반시계방향(-) convention the load
            # field is typed in (see _apply_load), so what's shown here
            # matches what the user typed. The arrow always reflects the true
            # physical rotation, tied to the unflipped mz.
            arrow = "↻" if mz < 0 else "↺"
            label = self.scene_model.addText(f"{arrow} Mz {-mz:g}")
            label.setDefaultTextColor(QColor("#dc2626"))
            label.setPos(origin + QPointF(10, -38))

    @staticmethod
    def load_arrow_segments(
        start: Node, end: Node, load: UniformElementLoad, reach: float
    ) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
        """Arrow tails and tips in model space, expressed in the member's local axes.

        A uniform load is defined along the member, so the arrows have to follow the
        member: on a sloped rafter they stand perpendicular to it, not straight down.

        A trapezoidal load (wy != wy_j, or wx != wx_j) additionally tapers each
        arrow's length to the interpolated w(x) at that arrow's own position
        (0.25..1.0 of ``reach``, never fully to zero so the light end stays
        visible), so a triangular/trapezoidal load visibly reads as one instead
        of looking exactly like a uniform load. A plain uniform load (wy == wy_j)
        reduces to the original fixed-length arrows unchanged, since every
        position then interpolates back to the same constant value.
        """
        dx = end.x - start.x
        dy = end.y - start.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0.0:
            return []
        along = (dx / length, dy / length)
        normal = (-along[1], along[0])
        peak_y = max(abs(load.wy), abs(load.wy_j))
        peak_x = max(abs(load.wx), abs(load.wx_j))
        trapezoid_x = load.wx != load.wx_j
        segments = []
        for fraction in (0.1, 0.3, 0.5, 0.7, 0.9):
            tip = (start.x + dx * fraction, start.y + dy * fraction)
            local_y = load.wy + (load.wy_j - load.wy) * fraction
            if local_y and peak_y:
                sign = -1.0 if local_y < 0 else 1.0
                local_reach = reach * (0.25 + 0.75 * abs(local_y) / peak_y)
                tail = (
                    tip[0] - normal[0] * local_reach * sign,
                    tip[1] - normal[1] * local_reach * sign,
                )
                label = (
                    f"qy {load.wy:g}~{load.wy_j:g}" if load.wy != load.wy_j else f"qy {load.wy:g}"
                )
                segments.append((tail, tip, label if fraction == 0.5 else ""))
            local_x = load.wx + (load.wx_j - load.wx) * fraction
            if local_x and peak_x and (fraction == 0.5 or trapezoid_x):
                sign = 1.0 if local_x > 0 else -1.0
                local_reach = reach * (0.25 + 0.75 * abs(local_x) / peak_x)
                tail = (
                    tip[0] - along[0] * local_reach * sign,
                    tip[1] - along[1] * local_reach * sign,
                )
                label = (
                    f"qx {load.wx:g}~{load.wx_j:g}" if trapezoid_x else f"qx {load.wx:g}"
                )
                segments.append((tail, tip, label if fraction == 0.5 else ""))
        return segments

    def _draw_end_release(self, end: Node, away_from: Node, scale: float) -> None:
        """Small open circle set back from the joint marking a pinned member end."""
        dx, dy = away_from.x - end.x, away_from.y - end.y
        length = max((dx * dx + dy * dy) ** 0.5, 1.0e-9)
        offset = 11.0
        x = end.x * scale + dx / length * offset
        y = -end.y * scale - dy / length * offset
        self.scene_model.addEllipse(
            x - 4, y - 4, 8, 8, QPen(QColor("#f97316"), 2), QColor("#fff7ed")
        )

    def _draw_uniform_load(
        self, start: Node, end: Node, load: UniformElementLoad, scale: float
    ) -> None:
        """The transverse (qy) component draws as a semi-transparent closed box -
        a trapezoid when wy != wy_j, a rectangle when uniform - instead of
        floating arrows with no connecting edge, which made it hard to tell at a
        glance whether the load actually spanned the whole member. The axial
        (qx) component, a much rarer case where a perpendicular "box" would read
        confusingly, keeps the arrow representation: ``load_arrow_segments``
        still generates both, so only the ones running along the member (not
        perpendicular to it) are drawn here.
        """
        if load.wy or load.wy_j:
            self._draw_distributed_load_box(start, end, load, scale)
        dx = end.x - start.x
        dy = end.y - start.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0.0:
            return
        normal = (-dy / length, dx / length)
        for tail, tip, text in self.load_arrow_segments(start, end, load, 32.0 / scale):
            vector = (tip[0] - tail[0], tip[1] - tail[1])
            perpendicular_component = vector[0] * normal[0] + vector[1] * normal[1]
            if abs(perpendicular_component) < 1.0e-9:  # runs along the member -> axial (qx)
                self._draw_arrow(
                    QPointF(tail[0] * scale, -tail[1] * scale),
                    QPointF(tip[0] * scale, -tip[1] * scale),
                    text,
                )

    def _draw_distributed_load_box(
        self, start: Node, end: Node, load: UniformElementLoad, scale: float
    ) -> None:
        dx = end.x - start.x
        dy = end.y - start.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0.0:
            return
        along = (dx / length, dy / length)
        normal = (-along[1], along[0])
        peak = max(abs(load.wy), abs(load.wy_j))
        if peak <= 0.0:
            return
        max_reach = 30.0 / scale

        def offset(x: float, y: float, w: float) -> tuple[float, float]:
            # Mirrors the sign convention load_arrow_segments already uses for
            # qy, so a downward load's box sits on the same side its arrows
            # used to: above the member, hatched down into it.
            if w == 0.0:
                return (x, y)
            sign = -1.0 if w < 0.0 else 1.0
            reach = max_reach * abs(w) / peak
            return (x - normal[0] * reach * sign, y - normal[1] * reach * sign)

        def to_scene(point: tuple[float, float]) -> QPointF:
            return QPointF(point[0] * scale, -point[1] * scale)

        inner_i, inner_j = (start.x, start.y), (end.x, end.y)
        outer_i = offset(start.x, start.y, load.wy)
        outer_j = offset(end.x, end.y, load.wy_j)

        color = QColor("#dc2626")
        fill = QColor(color)
        fill.setAlpha(55)
        pen = QPen(color, 1.4)
        self.scene_model.addPolygon(
            QPolygonF([to_scene(inner_i), to_scene(inner_j), to_scene(outer_j), to_scene(outer_i)]),
            pen,
            fill,
        )
        # Hatch lines from the outer edge back to the member so the load's
        # direction still reads clearly through the semi-transparent fill.
        for fraction in (0.15, 0.5, 0.85):
            member_point = (start.x + dx * fraction, start.y + dy * fraction)
            local_w = load.wy + (load.wy_j - load.wy) * fraction
            outer_point = offset(*member_point, local_w)
            scene_outer, scene_inner = to_scene(outer_point), to_scene(member_point)
            self.scene_model.addLine(
                scene_outer.x(), scene_outer.y(), scene_inner.x(), scene_inner.y(), QPen(color, 1.0)
            )

        label = f"qy {load.wy:g}~{load.wy_j:g}" if load.wy != load.wy_j else f"qy {load.wy:g}"
        midpoint = (start.x + dx * 0.5, start.y + dy * 0.5)
        midpoint_load = load.wy + (load.wy_j - load.wy) * 0.5
        label_point = to_scene(offset(*midpoint, midpoint_load))
        text_item = self.scene_model.addText(label)
        text_item.setDefaultTextColor(color)
        text_item.setPos(label_point + QPointF(4, -14))

    def _draw_arrow(self, start: QPointF, end: QPointF, text: str) -> None:
        pen = QPen(QColor("#dc2626"), 2)
        self.scene_model.addLine(start.x(), start.y(), end.x(), end.y(), pen)
        delta = start - end
        length = max((delta.x() ** 2 + delta.y() ** 2) ** 0.5, 1.0)
        unit = QPointF(delta.x() / length, delta.y() / length)
        normal = QPointF(-unit.y(), unit.x())
        wing = 7.0
        self.scene_model.addLine(
            end.x(), end.y(),
            end.x() + unit.x() * wing + normal.x() * wing / 2,
            end.y() + unit.y() * wing + normal.y() * wing / 2,
            pen,
        )
        self.scene_model.addLine(
            end.x(), end.y(),
            end.x() + unit.x() * wing - normal.x() * wing / 2,
            end.y() + unit.y() * wing - normal.y() * wing / 2,
            pen,
        )
        if text:
            label = self.scene_model.addText(text)
            label.setDefaultTextColor(QColor("#dc2626"))
            label.setPos(start + QPointF(4, -18))

    def _item_key(self, position) -> tuple[str, int] | None:
        item = self.itemAt(position)
        value = item.data(0) if item is not None else None
        return value if isinstance(value, tuple) else None

    def _node_at_view(self, position) -> int | None:
        key = self._item_key(position)
        return key[1] if key and key[0] == "node" else None

    def _member_at_view(self, position) -> int | None:
        key = self._item_key(position)
        return key[1] if key and key[0] == "element" else None
