"""3D viewport picking, hover preview and authoring refresh.

Mixin on ModelingInterfacePage: click/hover signals from Quick3DViewport
are translated into canvas mutations here, then ``authoring_model()`` (not
``build_model()``) is sent back to the viewport. Split out so a 3D-input
change cannot silently edit Loads-tab or Work Tree code.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QComboBox, QWidget

from openframe.features.model.drawing import PlaneKind


class _Modeling3DInputMixin:

    def eventFilter(self, watched, event) -> bool:
        if (
            self._start_in_3d
            and self.canvas.mode == "draw"
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and watched in {self.preview_3d.quick_widget, self.draw_entry}
        ):
            self._activate_select_tool()
            event.accept()
            return True
        return super().eventFilter(watched, event)


    def _apply_3d_camera_preset(self) -> None:
        preset = self.preview_3d_camera.currentData()
        if preset:
            self.preview_3d.set_camera_preset(str(preset))


    def _fit_3d_preview(self) -> None:
        preset = self.preview_3d_camera.currentData() or "iso"
        self.preview_3d.set_camera_preset(str(preset))


    def _enable_3d_mode(self) -> None:
        """Switch this page's canvas from a flat 2D sheet to a freely-orbited
        3D view, once, at construction time.

        2D and 3D are separate work areas (separate ``ModelingInterfacePage``
        instances — see ``start_in_3d``), each with its own canvas, so there is
        no live toggle here and no way back to 2D for a page built this way.
        """
        self.canvas.enter_3d_mode()
        self.canvas.model_changed.connect(self._refresh_3d_preview)
        self._refresh_plane_selectors()
        # Not relied on to happen via the plane-selector's own signal: Qt may
        # auto-select a combo box's first item while population is still
        # signal-blocked, in which case the later setCurrentIndex(0) is a
        # no-op and currentIndexChanged never fires.
        self.preview_3d.set_active_plane(
            str(self.canvas.work_plane.kind), self.canvas.work_plane.offset
        )
        self._refresh_3d_preview()
        self._load_target_changed()
        self._refresh_support_custom_row()
        self.level_bar.setVisible(True)
        self.canvas_stack.setCurrentWidget(self.preview_3d_panel)
        # Whichever surface is now on screen needs its picking mode to match
        # whatever tool is already active, not just whatever it was left at.
        self._sync_picking_mode()


    def _refresh_plane_selectors(self) -> None:
        length = self._unit_system.length
        for combo in (self.plane_selector, self.column_target):
            combo.blockSignals(True)
            combo.clear()
            for plane in self.canvas.levels:
                combo.addItem(
                    f"{plane.label} ({plane.kind} @ {plane.offset:g} {length})",
                    plane,
                )
            combo.blockSignals(False)
        # QComboBox.findData() compares composite Python objects (a WorkPlane, here)
        # by identity under the hood, not by value — a freshly-built-but-equal
        # WorkPlane would silently fail to match. Iterating and comparing with
        # Python's own `==` is the reliable way to do this lookup.
        for index in range(self.plane_selector.count()):
            if self.plane_selector.itemData(index) == self.canvas.work_plane:
                self.plane_selector.setCurrentIndex(index)
                break


    def _change_active_plane(self) -> None:
        plane = self.plane_selector.currentData()
        if plane is not None:
            self.canvas.set_active_plane(plane)
            self.preview_3d.set_active_plane(str(plane.kind), plane.offset)
            self._refresh_status()


    def _add_plane(self) -> None:
        label = self.new_plane_label.text().strip() or f"평면 {len(self.canvas.levels) + 1}"
        plane = self.canvas.add_level(
            self.new_plane_offset.value(), label, self.new_plane_kind.currentData()
        )
        self._refresh_plane_selectors()
        self.canvas.set_active_plane(plane)
        self.preview_3d.set_active_plane(str(plane.kind), plane.offset)
        self._refresh_plane_selectors()
        self.new_plane_label.clear()


    def _extrude_to_target_plane(self) -> None:
        if self._start_in_3d and self._active_element_kwargs is None:
            self._activate_draw_tool()
            return
        target = self.column_target.currentData()
        if target is not None:
            before = set(self.canvas.elements)
            self.canvas.extrude_selection_to_plane(target)
            self._apply_active_element_to_new_members(set(self.canvas.elements) - before)


    def _on_3d_plane_picked(self, x: float, y: float, z: float) -> None:
        """A click on empty space on the active plane in the 3D view.

        Deliberately a no-op: this used to drop a new node wherever the
        plane was clicked, but an orbit drag in 3D routinely ends in a
        stray click on empty space - every accidental release created a
        node nobody meant to place. Node creation is exact-coordinate-only
        now (the Node tab's Create Node form / ``_add_nodes_from_
        coordinates``); a click here does nothing. Clicking an *existing*
        node still works (``_on_3d_node_picked``) since that can never be
        a stray click on nothing.
        """
        return


    def _on_3d_node_picked(self, tag: int, _screen_x: int, _screen_y: int) -> None:
        """Use pairs of node clicks to draw independent members in 3D.

        The draw tool stays active after a member is completed, but its start
        node is cleared.  The next click therefore starts a new member instead
        of silently continuing from the previous member's end node.
        """
        if self.canvas.mode == "draw":
            if self._active_element_kwargs is None:
                self.canvas.end_chain()
                self._activate_draw_tool()
                return
            start_tag = self.canvas.chain_last_node
            before = set(self.canvas.elements)
            self.canvas.continue_chain_to_node(tag)
            self._apply_active_element_to_new_members(set(self.canvas.elements) - before)
            if start_tag is not None and start_tag != tag:
                self.canvas.end_chain()
        elif self.canvas.mode == "floor_pick":
            # Clicking back on the boundary's own first node closes the loop
            # (MIDAS-style) - requested: "다시 시작점 노드로 오면 자동으로
            # 종료 및 하중 적용으로 이어지게" - so that click finishes and
            # applies the load immediately, the same as pressing 완료, rather
            # than being swallowed as an ordinary already-in-chain no-op.
            chain = self.canvas._floor_chain
            if chain and tag == chain[0] and len(chain) >= 3:
                self._finish_floor_boundary_picking()
            else:
                self.canvas.add_floor_boundary_node(tag)
        else:
            self.canvas.selected_nodes = {tag}
            self.canvas.selected_elements.clear()
            self.canvas.selection_changed.emit()


    def _on_3d_member_picked(self, tag: int, _screen_x: int, _screen_y: int) -> None:
        """Select a member with a plain click in the 3D authoring view."""
        if self.canvas.mode != "select" or tag not in self.canvas.elements:
            return
        if self.canvas.selection_filter == "nodes":
            return
        self.canvas.selected_nodes.clear()
        self.canvas.selected_elements = {tag}
        self.canvas.selection_changed.emit()


    def _on_3d_box_selected(
        self, node_tags: set[int], member_tags: set[int], additive: bool
    ) -> None:
        """Apply the QML viewport's projected rectangle selection to the
        shared modeling canvas state.

        Deliberately ignores ``selection_filter``: transform tabs (부재
        이동/복사, 노드 이동/복사 등) auto-narrow the filter to "elements" or
        "nodes" so a plain click picks only the kind being transformed, but
        a drag box must still take everything the QML view enclosed — half
        the box result used to be dropped with no visible reason why.

        A no-op while picking a floor boundary - a box has no click order,
        so honoring it here would silently overwrite selected_nodes out from
        under the ordered _floor_chain it is supposed to mirror. Only single
        node clicks (_on_3d_node_picked) build a floor boundary.
        """
        if self.canvas.mode == "floor_pick":
            return
        if not additive:
            self.canvas.selected_nodes.clear()
            self.canvas.selected_elements.clear()
        self.canvas.selected_nodes.update(node_tags)
        self.canvas.selected_elements.update(member_tags)
        self.canvas.selection_changed.emit()


    def _on_3d_node_hovered(self, tag: int) -> None:
        """Cursor is over an existing node while drawing or floor-picking —
        snap whichever live preview is active onto its exact coordinates."""
        node = self.canvas.nodes.get(tag)
        point = None if node is None else (node.x, node.y, node.z)
        self._update_3d_draw_preview(point)
        self._update_3d_floor_outline(point)


    def _on_3d_plane_hovered(self, x: float, y: float, z: float) -> None:
        """Cursor is over the active plane (not snapped to a node) while
        drawing or floor-picking — follow it with whichever live preview is
        active."""
        self._update_3d_draw_preview((x, y, z))
        self._update_3d_floor_outline((x, y, z))


    def _on_3d_hover_cleared(self) -> None:
        self.preview_3d.set_preview_segment(None, None)
        self._update_3d_floor_outline(None)


    def _update_3d_draw_preview(self, end: tuple[float, float, float] | None) -> None:
        tag = self.canvas.chain_last_node
        start_node = self.canvas.nodes.get(tag) if tag is not None else None
        if self.canvas.mode != "draw" or start_node is None or end is None:
            self.preview_3d.set_preview_segment(None, None)
            return
        self.preview_3d.set_preview_segment((start_node.x, start_node.y, start_node.z), end)


    def _update_3d_floor_outline(self, hover_point: tuple[float, float, float] | None) -> None:
        """Trace the in-progress floor boundary's yellow outline - an edge
        between each already-clicked chain node plus a trailing edge to the
        cursor, so the outline visibly grows and follows the mouse with each
        click (MIDAS-style), replacing the opaque ghost face this used to
        render. A no-op outside floor_pick mode; _sync_picking_mode clears
        the outline itself once floor_pick is left, covering 완료/취소/Esc in
        one place."""
        if self.canvas.mode != "floor_pick":
            return
        chain_points = [
            (node.x, node.y, node.z)
            for tag in self.canvas._floor_chain
            if (node := self.canvas.nodes.get(tag)) is not None
        ]
        if hover_point is not None and chain_points:
            # Floor-picking never points set_active_plane at the boundary's
            # own elevation (unlike draw mode), so a raw plane-hover point can
            # sit at a stale leftover height. Pin it to the chain's own
            # height instead, so the trailing vertex looks like it's moving
            # across the same flat floor as the nodes already picked, rather
            # than warping toward whatever plane happens to be active.
            hover_x, hover_y, _ = hover_point
            hover_point = (hover_x, hover_y, chain_points[0][2])
        points = chain_points + ([hover_point] if hover_point is not None else [])
        self.preview_3d.set_floor_boundary_outline(points)


    def _on_3d_draw_state_changed(self) -> None:
        """Drop the rubber-band preview whenever the chain itself changes -
        a point committed, the chain broken, the tool switched - so it never
        lingers pointing at a segment that no longer applies. The next hover
        redraws it fresh if a chain is still open."""
        if self.canvas.ndm == 3:
            self.preview_3d.set_preview_segment(None, None)


    def _refresh_3d_preview(self) -> None:
        if self.canvas.ndm == 3:
            # Authoring mesh only - build_model() is the analysis split and
            # must not run on every click (see StaticsDrawingCanvas.authoring_model).
            self.preview_3d.set_model(self.canvas.authoring_model(), reset_camera=False)
            self._sync_3d_selection_highlight()


    def _sync_picking_mode(self) -> None:
        """Match the 3D view's click behaviour to whatever tool is active.

        Kept as its own step (not inlined into ``_set_mode``) because the 3D
        panel's picking mode also has to be refreshed on its own when the view
        is swapped in by the 3D toggle, without the tool itself changing.
        """
        if self.canvas.ndm != 3:
            return
        if self.canvas.mode != "floor_pick":
            self.preview_3d.set_floor_boundary_outline([])
        if self.canvas.mode == "floor_pick":
            # Wants node-picking (existing nodes only - a plane click stays a
            # no-op, see _on_3d_plane_picked) WITH the crosshair cursor as a
            # clear "you are placing a floor boundary" signal (requested: "적용
            # 버튼을 누르면 마우스 포인터가 바뀌고"). Both setters plant
            # CrossCursor when enabled, so the order between them doesn't
            # matter here (unlike the drawing branch below).
            #
            # set_plane_picking_mode(True) - not False, despite picking only
            # ever landing on nodes - because it's also what drives the
            # continuous nodeHovered/planeHovered/hoverCleared signals (see
            # structural_view.qml's onPositionChanged), which
            # _update_3d_floor_outline needs to trace the in-progress
            # boundary's outline as the cursor moves. A stray click on empty
            # space now reaches _on_3d_plane_picked instead of
            # empty_space_clicked - also fixing a latent bug where that used
            # to clear_selection() the visual highlight without clearing the
            # underlying _floor_chain, desyncing the two until the next click.
            self.preview_3d.set_plane_picking_mode(True)
            self.preview_3d.set_picking_mode(True)
            return
        drawing = self.canvas.mode == "draw"
        # Both setters plant a cursor on the same QQuickWidget, so whichever
        # runs last wins - call the one that should *not* end up owning the
        # cursor first, or entering draw mode silently leaves the arrow
        # cursor in place (set_picking_mode(False) unsetting it right after
        # set_plane_picking_mode(True) had just set the crosshair).
        self.preview_3d.set_picking_mode(not drawing)
        self.preview_3d.set_plane_picking_mode(drawing)


    def _handle_escape_shortcut_3d(self) -> None:
        """Second copy of the canvas's own Escape handling (see
        canvas_input_events.py's keyPressEvent) scoped to the whole 3D page -
        self.canvas stays hidden in 3D mode and can never hold keyboard
        focus, so its own keyPressEvent never fires while the user is
        actually in preview_3d or the length/angle entry (same reason
        draw_space_shortcut_3d exists as a second copy of the Space
        shortcut). Escape exits draw mode without touching selection, same
        as the 2D canvas; once already in select mode it clears the current
        selection instead - the usual CAD Esc-to-deselect convention.
        """
        if self.canvas.mode == "draw":
            self._activate_select_tool()
            return
        if self.canvas.mode == "floor_pick":
            self._cancel_floor_boundary_picking()
            return
        self.canvas.end_chain()
        self.canvas.clear_selection()


    def _isolate_selection_3d(self) -> None:
        """F2: MIDAS-style "Active Only" - hide everything except the
        current selection, so e.g. one story's nodes/members stay easy to
        see and click while giving it a floor load without the rest of the
        building in the way. A no-op with nothing selected. Ctrl+A
        (preview_3d.clear_isolate, wired alongside this shortcut) shows the
        whole model again.
        """
        self.preview_3d.set_isolate(
            set(self.canvas.selected_nodes), set(self.canvas.selected_elements)
        )


    def _sync_3d_selection_highlight(self) -> None:
        if self.canvas.ndm == 3:
            self.preview_3d.set_selection(
                set(self.canvas.selected_nodes), set(self.canvas.selected_elements)
            )

