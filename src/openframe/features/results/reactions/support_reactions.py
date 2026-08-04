"""Support-reaction values paired with the geometry needed to place them.

No Qt objects are created here; drawing belongs to the presentation layer.
"""

from dataclasses import dataclass

from openframe.core.domain import AnalysisResult, StructuralModel

# Components below this fraction of the largest reaction are treated as numerical noise
# and reported as zero, so an unrestrained direction does not draw a hairline arrow.
_RELATIVE_TOLERANCE = 1.0e-9


@dataclass(frozen=True, slots=True)
class SupportReaction:
    node_tag: int
    x: float
    y: float
    fx: float
    fy: float
    mz: float

    @property
    def has_force(self) -> bool:
        return self.fx != 0.0 or self.fy != 0.0

    @property
    def has_moment(self) -> bool:
        return self.mz != 0.0


def support_reactions(
    model: StructuralModel, result: AnalysisResult
) -> tuple[SupportReaction, ...]:
    """Return the reaction at every restrained node, ordered by node tag."""
    restrained_tags = sorted(
        {
            boundary.node_tag
            for boundary in model.boundaries
            if any(boundary.restraints)
        }
    )

    raw: list[tuple[int, float, float, float]] = []
    for node_tag in restrained_tags:
        node = model.nodes.get(node_tag)
        node_result = result.node_results.get(node_tag)
        if node is None or node_result is None:
            continue
        values = (*node_result.reaction, 0.0, 0.0, 0.0)
        raw.append((node_tag, float(values[0]), float(values[1]), float(values[2])))

    force_scale = max(
        (max(abs(fx), abs(fy)) for _, fx, fy, _ in raw),
        default=0.0,
    )
    moment_scale = max((abs(mz) for _, _, _, mz in raw), default=0.0)

    reactions: list[SupportReaction] = []
    for node_tag, fx, fy, mz in raw:
        node = model.nodes[node_tag]
        reactions.append(
            SupportReaction(
                node_tag=node_tag,
                x=node.x,
                y=node.y,
                fx=_denoise(fx, force_scale),
                fy=_denoise(fy, force_scale),
                mz=_denoise(mz, moment_scale),
            )
        )
    return tuple(reactions)


def reaction_resultant(reactions: tuple[SupportReaction, ...]) -> tuple[float, float]:
    """Return the summed horizontal and vertical reactions for an equilibrium check."""
    return (
        sum(reaction.fx for reaction in reactions),
        sum(reaction.fy for reaction in reactions),
    )


def _denoise(value: float, scale: float) -> float:
    return 0.0 if abs(value) <= scale * _RELATIVE_TOLERANCE else value
