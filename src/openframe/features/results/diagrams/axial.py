"""Axial-force diagram calculations."""

from openframe.features.results.diagrams.base import DiagramKind, DiagramPoint, MemberDiagram


def from_end_forces(element_tag: int, start: float, end: float) -> MemberDiagram:
    return MemberDiagram(
        element_tag,
        DiagramKind.AXIAL,
        (DiagramPoint(0.0, start), DiagramPoint(1.0, end)),
    )

