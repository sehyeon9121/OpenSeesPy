"""Nodal displacement values paired with the geometry needed to place them.

No Qt objects are created here; drawing belongs to the presentation layer.
"""

import math
from dataclasses import dataclass

from openframe.core.domain import AnalysisResult, StructuralModel


@dataclass(frozen=True, slots=True)
class NodalDisplacement:
    node_tag: int
    x: float
    y: float
    ux: float
    uy: float
    rz: float

    @property
    def magnitude(self) -> float:
        return math.hypot(self.ux, self.uy)

    @property
    def moves(self) -> bool:
        return self.magnitude > 0.0


def nodal_displacements(
    model: StructuralModel, result: AnalysisResult
) -> tuple[NodalDisplacement, ...]:
    """Return the displacement of every node that has one, ordered by node tag."""
    displacements: list[NodalDisplacement] = []
    for node_tag in sorted(model.nodes):
        node_result = result.node_results.get(node_tag)
        if node_result is None:
            continue
        node = model.nodes[node_tag]
        values = (*node_result.displacement, 0.0, 0.0, 0.0)
        displacements.append(
            NodalDisplacement(
                node_tag=node_tag,
                x=node.x,
                y=node.y,
                ux=float(values[0]),
                uy=float(values[1]),
                rz=float(values[2]),
            )
        )
    return tuple(displacements)


def largest_displacement(
    displacements: tuple[NodalDisplacement, ...],
) -> NodalDisplacement | None:
    """Return the node that moved furthest, or None when nothing moved."""
    moving = [item for item in displacements if item.moves]
    if not moving:
        return None
    return max(moving, key=lambda item: item.magnitude)
