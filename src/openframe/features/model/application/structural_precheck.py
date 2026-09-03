"""Domain-level topology precheck on ``StructuralModel`` — not a stability solver.

OpenSees assembly rewrites the user's model before K is formed (dummy hinge
nodes, auxiliary ground nodes, orphan-rotation pins). A later stiffness-matrix
diagnostic therefore sees a *patched* model and can miss the original modeling
mistake. This module inspects the user-facing ``StructuralModel`` only. It
reports obvious topology/geometry problems. It does **not** decide whether the
structure is a mechanism — that is the matrix diagnostic's job.

Auxiliary OpenSees nodes never live on ``StructuralModel.nodes``; they are
minted only inside ``_build`` / script export. This layer therefore does not
know, and must not encode, solver-internal tag offsets.

Deliberately does not import OpenSeesPy or ``features.analysis.statics.solver``
(that module pulls in OpenSees at import time). Truss-vs-frame detection is
duplicated from ``_element_family`` so this module stays off that import.

What the solvers currently do (so this precheck does not fight them):

- 2D canvas models always have ``ndf=3`` (UX, UY, RZ); 3D canvas always
  ``ndf=6``. A pure truss still gets those ndf values on the domain model.
- The in-process determinate solver then *overrides* ndf: 2D truss → 2,
  3D truss → 3, so unused rotations never enter that K. Mixed frame+truss
  keeps the full frame ndf and pins orphan rotations
  (``_mixed_orphan_rotation_nodes``).
- 3D frame end releases do not use ``equalDOF``. They duplicate the joint and
  tie it with an oriented zeroLength. If every end at a joint is released, the
  original joint's rotations are ``fix``ed
  (``_orphan_joint_nodes_for_rotation_pin``). Canvas node-hinges already keep
  one member rigid at an unrestrained joint, so a normal hinge frame never
  hits that pin.
- ``rigidDiaphragm`` is a 3D Story Manager object on the domain model.
  Studio does not emit ``equalDOF`` for drawn models.
- ``check_determinacy`` is a scalar m+r−j count, not a topology walk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from openframe.core.domain.model import BoundaryCondition, Element, Node, StructuralModel

# Same absolute floor ``geometric_transform.validate_orientation_vector`` uses
# for a degenerate member axis. A member shorter than this cannot define local
# axes; treating it as "zero length" here matches that existing policy rather
# than inventing a second tolerance.
_ZERO_LENGTH_ABS_TOL = 1.0e-12

_TRUSS_ROTATION_DOFS = ("RX", "RY", "RZ")


class StructuralPrecheckSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class StructuralPrecheckIssue:
    """One topology finding. Not a reuse of presentation ``PrecheckIssue``:
    that type is the Analysis Case chip (title + detail, no node/element
    tags) and lives under ``features.model.presentation``. Mapping to a chip
    happens in ``analysis_precheck`` so this layer stays GUI-free.
    """

    severity: StructuralPrecheckSeverity
    code: str
    title: str
    message: str
    node_tags: tuple[int, ...] = ()
    element_tags: tuple[int, ...] = ()
    dof: str | None = None


class StructuralPrecheckService:
    """Walk a ``StructuralModel`` and return obvious topology issues."""

    def check(self, model: StructuralModel) -> tuple[StructuralPrecheckIssue, ...]:
        nodes = dict(model.nodes)
        if not nodes:
            return ()

        issues: list[StructuralPrecheckIssue] = []
        adjacency, incident = _element_adjacency(model, nodes)

        issues.extend(_isolated_node_issues(nodes, incident))
        issues.extend(_unsupported_component_issues(model, adjacency, incident))
        issues.extend(_zero_length_element_issues(model, nodes))
        issues.extend(_truss_rotational_dof_issues(model, nodes, incident))
        issues.extend(_orphan_release_rotation_issues(model, nodes, incident))
        return tuple(issues)


def run_structural_precheck(model: StructuralModel) -> tuple[StructuralPrecheckIssue, ...]:
    return StructuralPrecheckService().check(model)


def _is_truss(element: Element) -> bool:
    # Duplicated from solver._element_family so this module never imports
    # OpenSees. "truss" in the type name also covers corotTruss / cable
    # aliases the canvas stamps as element_type "truss" plus behavior.
    return "truss" in element.element_type.lower()


def _member_length(node_i: Node, node_j: Node, ndm: int) -> float:
    dz = (node_j.z - node_i.z) if ndm == 3 else 0.0
    return math.sqrt(
        (node_j.x - node_i.x) ** 2 + (node_j.y - node_i.y) ** 2 + dz**2
    )


def _element_adjacency(
    model: StructuralModel,
    nodes: dict[int, Node],
) -> tuple[dict[int, set[int]], dict[int, list[Element]]]:
    """Element-graph neighbours plus the elements incident on each user node.

    ``rigidDiaphragm`` is *not* treated as a structural element for isolation
    (a diaphragm-only node is still 'not connected to any member'), but it
    *is* added as a graph edge when grouping floating components — two frames
    tied at a floor are one structural group for this coarse support check.
    """
    adjacency: dict[int, set[int]] = {tag: set() for tag in nodes}
    incident: dict[int, list[Element]] = {tag: [] for tag in nodes}
    for element in model.elements.values():
        i_tag, j_tag = element.node_i, element.node_j
        if i_tag in nodes:
            incident[i_tag].append(element)
        if j_tag in nodes:
            incident[j_tag].append(element)
        if i_tag in nodes and j_tag in nodes and i_tag != j_tag:
            adjacency[i_tag].add(j_tag)
            adjacency[j_tag].add(i_tag)
    for diaphragm in model.rigid_diaphragms:
        tied = [
            tag
            for tag in (diaphragm.master_tag, *diaphragm.slave_tags)
            if tag in nodes
        ]
        for left in tied:
            for right in tied:
                if left != right:
                    adjacency[left].add(right)
    return adjacency, incident


def _connected_components(
    adjacency: dict[int, set[int]],
    seeds: set[int],
) -> list[frozenset[int]]:
    remaining = set(seeds)
    components: list[frozenset[int]] = []
    while remaining:
        start = min(remaining)
        stack = [start]
        remaining.remove(start)
        seen = {start}
        while stack:
            current = stack.pop()
            for neighbour in adjacency.get(current, ()):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(frozenset(seen))
    return components


def _format_node_list(tags: tuple[int, ...] | list[int]) -> str:
    ordered = sorted(set(tags))
    if not ordered:
        return ""
    ranges: list[str] = []
    start = previous = ordered[0]
    for tag in ordered[1:]:
        if tag == previous + 1:
            previous = tag
            continue
        ranges.append(_format_span(start, previous))
        start = previous = tag
    ranges.append(_format_span(start, previous))
    return ", ".join(ranges)


def _format_span(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}–{end}"


def _isolated_node_issues(
    nodes: dict[int, Node],
    incident: dict[int, list[Element]],
) -> list[StructuralPrecheckIssue]:
    issues: list[StructuralPrecheckIssue] = []
    for tag in sorted(nodes):
        if incident[tag]:
            continue
        issues.append(
            StructuralPrecheckIssue(
                StructuralPrecheckSeverity.ERROR,
                "isolated_node",
                "고립 절점",
                f"절점 {tag}이(가) 어떤 구조 부재에도 연결되어 있지 않습니다.",
                node_tags=(tag,),
            )
        )
    return issues


def _node_has_support(model: StructuralModel, tag: int) -> bool:
    """Any rigid restraint or nonzero spring counts. This is intentionally
    coarse — a roller is a support even if the component can still fly in
    another direction. Exact mechanism DOFs are out of scope.
    """
    for condition in model.boundaries:
        if condition.node_tag != tag:
            continue
        if any(condition.restraints):
            return True
        if _has_nonzero_spring(condition):
            return True
    return False


def _has_nonzero_spring(condition: BoundaryCondition) -> bool:
    return any(
        stiffness is not None and stiffness != 0.0
        for stiffness in condition.spring_stiffnesses
    )


def _unsupported_component_issues(
    model: StructuralModel,
    adjacency: dict[int, set[int]],
    incident: dict[int, list[Element]],
) -> list[StructuralPrecheckIssue]:
    structural = {tag for tag, elements in incident.items() if elements}
    issues: list[StructuralPrecheckIssue] = []
    for component in _connected_components(adjacency, structural):
        if any(_node_has_support(model, tag) for tag in component):
            continue
        tags = tuple(sorted(component))
        listed = _format_node_list(tags)
        issues.append(
            StructuralPrecheckIssue(
                StructuralPrecheckSeverity.ERROR,
                "unsupported_component",
                "지지 없는 부재군",
                f"절점 {listed}이(가) 지지점 없는 독립 구조 그룹을 이룹니다.",
                node_tags=tags,
            )
        )
    return issues


def _zero_length_element_issues(
    model: StructuralModel,
    nodes: dict[int, Node],
) -> list[StructuralPrecheckIssue]:
    issues: list[StructuralPrecheckIssue] = []
    for element in sorted(model.elements.values(), key=lambda item: item.tag):
        node_i = nodes.get(element.node_i)
        node_j = nodes.get(element.node_j)
        if node_i is None or node_j is None:
            continue
        if element.node_i == element.node_j or math.isclose(
            _member_length(node_i, node_j, model.ndm),
            0.0,
            abs_tol=_ZERO_LENGTH_ABS_TOL,
        ):
            issues.append(
                StructuralPrecheckIssue(
                    StructuralPrecheckSeverity.ERROR,
                    "zero_length_element",
                    "영길이 부재",
                    f"부재 {element.tag}의 길이가 사실상 0입니다 "
                    f"(절점 {element.node_i}, {element.node_j}이(가) 동일 위치).",
                    node_tags=(element.node_i, element.node_j),
                    element_tags=(element.tag,),
                )
            )
    return issues


def _has_rotational_restraint(model: StructuralModel, tag: int) -> bool:
    """3D Rx/Ry/Rz — indices 3, 4, 5. A rotational spring counts too."""
    for condition in model.boundaries:
        if condition.node_tag != tag:
            continue
        restraints = condition.restraints
        if any(index < len(restraints) and restraints[index] for index in (3, 4, 5)):
            return True
        springs = condition.spring_stiffnesses
        if any(
            index < len(springs) and springs[index] is not None and springs[index] != 0.0
            for index in (3, 4, 5)
        ):
            return True
    return False


def _truss_rotational_dof_issues(
    model: StructuralModel,
    nodes: dict[int, Node],
    incident: dict[int, list[Element]],
) -> list[StructuralPrecheckIssue]:
    """Unused rotational DOFs at truss-only nodes of a *mixed* 3D model.

    A pure 3D truss is silent: production ``_build`` assembles it with ndf=3,
    so those rotations never exist in K. Emitting even INFO would look like a
    modeling problem (and PRE-CHECK treats any issue as a case '경고').

    Mixed frame+truss keeps ndf=6 and pins truss-only rotations
    (``_mixed_orphan_rotation_nodes``). That is solver policy, not an error —
    INFO here, and ``run_precheck`` keeps it off the default chips.
    """
    if model.ndm != 3 or not model.elements:
        return []
    if all(_is_truss(element) for element in model.elements.values()):
        return []
    if model.ndf < 6:
        return []
    tagged: list[int] = []
    for tag in sorted(nodes):
        elements = incident[tag]
        if not elements or not all(_is_truss(element) for element in elements):
            continue
        if _has_rotational_restraint(model, tag):
            continue
        tagged.append(tag)
    if not tagged:
        return []
    tags = tuple(tagged)
    listed = _format_node_list(tags)
    return [
        StructuralPrecheckIssue(
            StructuralPrecheckSeverity.INFO,
            "truss_rotational_dof",
            "트러스 회전 자유도",
            f"절점 {listed}은(는) 트러스 부재에만 연결되어 있습니다. "
            "혼합 모델에서 해당 회전 자유도는 해석 시 사용되지 않습니다.",
            node_tags=tags,
            dof=",".join(_TRUSS_ROTATION_DOFS),
        )
    ]


def _orphan_release_rotation_issues(
    model: StructuralModel,
    nodes: dict[int, Node],
    incident: dict[int, list[Element]],
) -> list[StructuralPrecheckIssue]:
    """Joints where every *frame* end is released and nothing anchors rotation.

    Mirrors ``_orphan_joint_nodes_for_rotation_pin``: the solver pins the
    joint-side rotations because the physical hinge lives on dummy nodes, so
    this is INFO (the pin is a designed numerical patch), not a mechanism
    verdict. Mixed frame+truss joints are skipped — that case is
    ``_mixed_orphan_rotation_nodes`` and is easy to misread as a real
    instability. Canvas node-hinges keep one member rigid, so a normal hinge
    frame does not match this predicate.
    """
    tagged: list[int] = []
    rotation_indices = (2,) if model.ndm == 2 else (4, 5)
    for tag in sorted(nodes):
        elements = incident[tag]
        if not elements:
            continue
        if any(_is_truss(element) for element in elements):
            continue
        all_released = True
        for element in elements:
            released = (
                element.moment_release_i
                if element.node_i == tag
                else element.moment_release_j
                if element.node_j == tag
                else False
            )
            if not released:
                all_released = False
                break
        if not all_released:
            continue
        if _rotation_restrained_at(model, tag, rotation_indices):
            continue
        tagged.append(tag)
    if not tagged:
        return []
    tags = tuple(tagged)
    listed = _format_node_list(tags)
    return [
        StructuralPrecheckIssue(
            StructuralPrecheckSeverity.INFO,
            "orphan_release_rotation",
            "해제된 절점 회전",
            f"절점 {listed}에서 모든 부재 단부가 모멘트 해제되어 절점 회전이 강성을 받지 "
            "않습니다. 해석 시 해당 회전은 수치 안정을 위해 구속됩니다.",
            node_tags=tags,
        )
    ]


def _rotation_restrained_at(
    model: StructuralModel,
    tag: int,
    indices: tuple[int, ...],
) -> bool:
    """Same partition ``_released_and_rigid_nodes`` uses for support-side
    rotation: 2D looks at RZ (index 2); 3D released frames keep torsion, so
    only Ry/Rz (4, 5) count as 'the support already anchors bending'.
    """
    for condition in model.boundaries:
        if condition.node_tag != tag:
            continue
        restraints = condition.restraints
        if any(index < len(restraints) and restraints[index] for index in indices):
            return True
        springs = condition.spring_stiffnesses
        if any(
            index < len(springs) and springs[index] is not None and springs[index] != 0.0
            for index in indices
        ):
            return True
    return False
