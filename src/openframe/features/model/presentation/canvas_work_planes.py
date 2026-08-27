"""Work-plane (3D authoring) methods for StaticsDrawingCanvas.

A mixin, not a standalone class: every method here reads/writes attributes
(``self.nodes``, ``self.work_plane``, ``self.levels``, ...) that
``StaticsDrawingCanvas.__init__`` sets up, and calls sibling methods
(``self._changed()``, ``self.add_member()``, ...) defined in the other
mixins that make up the full canvas class. Splitting the class this way -
same method bodies, just grouped into files by concern - keeps the
1900-line God class readable without changing any behaviour: Python
resolves ``self.foo()`` the same way regardless of which class in the MRO
defines ``foo``.
"""

from openframe.core.domain import Node
from openframe.features.model.drawing import PlaneKind, WorkPlane


class _WorkPlaneMixin:
    # --- work planes (3D authoring) -----------------------------------------

    def enter_3d_mode(self) -> None:
        """Switch the canvas from a flat 2D sheet to a stack of work planes."""
        self.ndm = 3

    def add_level(self, offset: float, label: str, kind: PlaneKind = PlaneKind.XY) -> WorkPlane:
        plane = WorkPlane(kind, offset, label)
        self.levels.append(plane)
        return plane

    def set_active_plane(self, plane: WorkPlane) -> None:
        self.work_plane = plane
        self.clear_selection()
        self._changed()

    def extrude_selection_to_plane(self, target: WorkPlane) -> int:
        """Connect the selected nodes straight up (or across) to another plane.

        This is how a column between two storeys gets drawn: pick the base nodes
        on the current plan, extrude to the next level's plane, and a member
        appears between each node and its counterpart there. Clicking a point in
        empty 3D space has no single right answer, so free-form 3D authoring
        never asks for that — every point is placed on a plane, including this one.
        """
        if not self.selected_nodes:
            return 0
        self.begin_history_group()
        created_members = 0
        try:
            for tag in sorted(self.selected_nodes):
                u, v = self._uv(self.nodes[tag])
                target_tag = self._add_node_at(target.to_3d(u, v))
                if self.add_member(tag, target_tag) is not None:
                    created_members += 1
        finally:
            self.end_history_group()
        return created_members

    def _uv(self, node: Node) -> tuple[float, float]:
        """Project a node onto the active work plane's local 2D coordinates."""
        return self.work_plane.to_2d((node.x, node.y, node.z))

    def _replace_uv(self, node: Node, u: float, v: float) -> tuple[float, float, float]:
        """``node``'s true 3D point with its in-plane (u, v) coordinates
        replaced by the given values, but its actual out-of-plane coordinate
        preserved exactly.

        ``WorkPlane.to_3d(u, v)`` always snaps the third coordinate to the
        plane's own offset - correct for placing a brand-new drawn point
        exactly on the active plane (``add_node``), but wrong for moving,
        copying, mirroring or array/rotate-copying an *existing* node that
        is not already sitting exactly on that plane (e.g. a column's top
        node on a different storey's plane than the one currently active) -
        that node would otherwise silently jump onto the active plane's
        height/offset instead of staying at its own.
        """
        if self.work_plane.kind == PlaneKind.XY:
            return (u, v, node.z)
        if self.work_plane.kind == PlaneKind.XZ:
            return (u, node.y, v)
        return (node.x, u, v)

    def _replace_uvw(self, node: Node, u: float, v: float, dw: float) -> tuple[float, float, float]:
        """Same as ``_replace_uv``, but also shifts the out-of-plane
        coordinate by ``dw`` instead of preserving it unchanged - this is
        what lets move/copy/array/rotate step *across* work planes (e.g.
        copying a whole storey's frame straight up in Z) instead of being
        confined to translating within the single active plane, which had
        no way to reach the third axis at all (reported: "복사 기능에서
        z축으로 복사하는 기능이 없음")."""
        if self.work_plane.kind == PlaneKind.XY:
            return (u, v, node.z + dw)
        if self.work_plane.kind == PlaneKind.XZ:
            return (u, node.y + dw, v)
        return (node.x + dw, u, v)

    def _on_plane(self, node: Node) -> bool:
        return self.work_plane.contains((node.x, node.y, node.z))

    def _plane_node_tags(self) -> set[int]:
        return {tag for tag, node in self.nodes.items() if self._on_plane(node)}

    def _plane_element_tags(self, plane_nodes: set[int] | None = None) -> set[int]:
        """Members fully on the active plane — both ends, not just one."""
        on_plane = self._plane_node_tags() if plane_nodes is None else plane_nodes
        return {
            tag
            for tag, element in self.elements.items()
            if element.node_i in on_plane and element.node_j in on_plane
        }
