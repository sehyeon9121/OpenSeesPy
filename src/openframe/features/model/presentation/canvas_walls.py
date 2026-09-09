"""Authoring walls (four-corner ``WallPanel``s) on StaticsDrawingCanvas.

A wall is not a two-node ``Element``. Clicking four existing nodes around a
closed ring creates one ``WallPanel``; the analysis mesh is derived later
by ``assemble_wall_meshes``. The 3D viewport draws that as a flat face —
thickness is an analysis property, never an extrusion.
"""

from openframe.core.domain import WallPanel
from openframe.features.model.presentation.canvas_property_application import (
    DEFAULT_POISSON_RATIO,
)


class _WallMixin:
    def add_wall_chain_node(self, tag: int) -> WallPanel | None:
        """Append ``tag`` to the in-progress four-corner wall, in click order.

        Duplicate / unknown tags are ignored so a stray re-click cannot
        collapse the ring. The fourth distinct corner commits a ``WallPanel``
        and clears the chain so the next click starts a new wall, matching
        how 3D beam drawing resets after each member.
        """
        if self.mode != "draw" or tag not in self.nodes or tag in self._wall_chain:
            return None
        self._wall_chain.append(tag)
        self.selected_nodes = set(self._wall_chain)
        self.selection_changed.emit()
        if len(self._wall_chain) < 4:
            self.draw_state_changed.emit()
            return None
        corners = (self._wall_chain[0], self._wall_chain[1], self._wall_chain[2], self._wall_chain[3])
        self._wall_chain.clear()
        self.selected_nodes.clear()
        self.selection_changed.emit()
        self.draw_state_changed.emit()
        return self.add_wall(corners)

    def add_wall(self, corners: tuple[int, int, int, int]) -> WallPanel | None:
        """Commit one rectangular wall from four already-placed nodes.

        ``wall_pen`` (Material + Thickness from Create Element) is the only
        source of t/E/ν/ρ. Missing or invalid pen values refuse the wall
        rather than stuffing a dummy beam section onto a surface.
        """
        pen = self.wall_pen
        if pen is None:
            return None
        if len(set(corners)) != 4 or any(tag not in self.nodes for tag in corners):
            return None
        panel = WallPanel(
            tag=max(self.walls, default=0) + 1,
            node_1=corners[0],
            node_2=corners[1],
            node_3=corners[2],
            node_4=corners[3],
            thickness=float(pen["thickness"]),
            nx=1,
            ny=1,
            elastic_modulus=float(pen["elastic"]),
            poisson_ratio=float(pen.get("poisson_ratio", DEFAULT_POISSON_RATIO)),
            density=float(pen.get("density", 0.0)),
        )
        if panel.validate():
            return None
        self._record_history()
        self.walls[panel.tag] = panel
        self._changed()
        return panel
