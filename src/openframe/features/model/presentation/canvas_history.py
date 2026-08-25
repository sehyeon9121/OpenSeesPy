"""Undo/redo history methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""


class _HistoryMixin:
    def begin_history_group(self) -> None:
        if self._history_group_depth == 0:
            self._history_group_snapshot = self._snapshot()
        self._history_group_depth += 1

    def end_history_group(self) -> None:
        if self._history_group_depth == 0:
            return
        self._history_group_depth -= 1
        if self._history_group_depth != 0:
            return
        if self._history_group_snapshot is not None:
            if self._history_group_snapshot != self._snapshot():
                self._undo_stack.append(self._history_group_snapshot)
                self._redo_stack.clear()
            self._history_group_snapshot = None
        # One clean model_changed for the whole group, instead of the one
        # _changed() swallowed per intermediate node/member it created along
        # the way - see _changed()'s own docstring (canvas_rendering.py).
        if self._pending_change_notification:
            self._pending_change_notification = False
            self.model_changed.emit()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())

    def _record_history(self) -> None:
        if self._history_group_depth:
            return
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()

    def _snapshot(self) -> dict[str, object]:
        return {
            "nodes": dict(self.nodes),
            "elements": dict(self.elements),
            "boundaries": dict(self.boundaries),
            "nodal_loads": dict(self.nodal_loads),
            "element_loads": dict(self.element_loads),
            "hinge_nodes": set(self.hinge_nodes),
            "embedded_nodes": dict(self.embedded_nodes),
            "load_cases": dict(self.load_cases),
            "active_load_case_id": self.active_load_case_id,
            "load_entries": dict(self.load_entries),
            "load_combinations": dict(self.load_combinations),
            "active_combination_id": self.active_combination_id,
            "floor_load_types": dict(self.floor_load_types),
            "stories": dict(self.stories),
        }

    def _restore(self, snapshot: dict[str, object]) -> None:
        self.nodes = dict(snapshot["nodes"])
        self.elements = dict(snapshot["elements"])
        self.boundaries = dict(snapshot["boundaries"])
        self.nodal_loads = dict(snapshot["nodal_loads"])
        self.element_loads = dict(snapshot["element_loads"])
        self.hinge_nodes = set(snapshot["hinge_nodes"])
        self.embedded_nodes = dict(snapshot["embedded_nodes"])
        self.load_cases = dict(snapshot["load_cases"])
        self.active_load_case_id = snapshot["active_load_case_id"]
        self.load_entries = dict(snapshot["load_entries"])
        self.load_combinations = dict(snapshot["load_combinations"])
        self.active_combination_id = snapshot["active_combination_id"]
        self.floor_load_types = dict(snapshot.get("floor_load_types", {}))
        self.stories = dict(snapshot.get("stories", {}))
        self.selected_nodes.clear()
        self.selected_elements.clear()
        self._selected = None
        self._member_start = None
        self._preview_point = None
        self._chain.clear()
        self._snap = None
        self._changed()
        self.draw_state_changed.emit()
        self.selection_changed.emit()
        self.load_state_changed.emit()
        self.story_state_changed.emit()
