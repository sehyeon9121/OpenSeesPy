"""Selection methods for StaticsDrawingCanvas.

See ``canvas_work_planes.py`` for why this is a mixin rather than a
standalone class.
"""

from PySide6.QtCore import Qt


class _SelectionMixin:
    def select_all(self) -> None:
        plane_nodes = self._plane_node_tags()
        self.selected_nodes = plane_nodes
        self.selected_elements = self._plane_element_tags(plane_nodes)
        self._selection_changed()

    def clear_selection(self) -> None:
        self.selected_nodes.clear()
        self.selected_elements.clear()
        self._selected = None
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._redraw()
        self.selection_changed.emit()

    def fit_model(self) -> None:
        bounds = self.scene_model.itemsBoundingRect()
        if not bounds.isEmpty():
            self.fitInView(bounds.adjusted(-50, -50, 50, 50), Qt.AspectRatioMode.KeepAspectRatio)

    def set_selected_node_kind(self, hinge: bool) -> None:
        if not self.selected_nodes:
            return
        self._record_history()
        if hinge:
            self.hinge_nodes.update(self.selected_nodes)
        else:
            self.hinge_nodes.difference_update(self.selected_nodes)
        self._changed()
