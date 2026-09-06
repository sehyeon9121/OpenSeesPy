"""OpenSees commands for surface members, shared by the in-process solver
and the script exporter.

Shear walls and slabs are not a new ``AnalysisModule``. Linear / nonlinear
static and time-history keep their packages; those runners call into this
module the same way they already call ``_build_one_truss_element`` for
trusses. ``_element_family`` today returns only ``"truss"`` or ``"frame"`` —
a third family stays out of ``Element`` and lives on ``StructuralModel.shell_quads``.

``features.analysis.statics.solver`` and ``opensees_script_export`` are the
callers. The GUI must not import this to talk to OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass

import openseespy.opensees as ops

from openframe.core.domain.model import StructuralModel
from openframe.core.domain.surfaces import WallPanel
from openframe.features.model.surfaces.rectangular_mesh import wall_local_x

#: Distinct from uniaxialMaterial / dummy-node offsets in solver.py
#: (7e6–9.7e6). OpenSees section tags are a separate namespace from nodes
#: but sharing those ranges would make a collision undiagnosable. Wall
#: identity is ``WallPanel.tag``; this offset is only the live OpenSees
#: section tag.
_SHELL_SECTION_TAG_OFFSET = 9_800_000


@dataclass(frozen=True, slots=True)
class ShellSectionCommand:
    tag: int
    elastic_modulus: float
    poisson_ratio: float
    thickness: float
    density: float


@dataclass(frozen=True, slots=True)
class ShellElementCommand:
    tag: int
    node_1: int
    node_2: int
    node_3: int
    node_4: int
    section_tag: int
    local_x: tuple[float, float, float]


def shell_section_tag(wall_tag: int) -> int:
    return _SHELL_SECTION_TAG_OFFSET + wall_tag


def wall_section_errors(model: StructuralModel) -> list[str]:
    errors: list[str] = []
    for wall in model.walls.values():
        errors.extend(wall.validate())
    return errors


def shell_build_plan(model: StructuralModel) -> tuple[list[ShellSectionCommand], list[ShellElementCommand]]:
    """OpenSees-free command list so the in-process solver and the script
    exporter emit the same section/element calls.
    """
    if not model.shell_quads:
        return [], []
    sections: list[ShellSectionCommand] = []
    seen_walls: set[int] = set()
    for wall in sorted(model.walls.values(), key=lambda item: item.tag):
        if wall.tag in seen_walls:
            continue
        seen_walls.add(wall.tag)
        sections.append(_section_command(wall))

    local_x_by_wall = {
        wall.tag: wall_local_x(wall, model.nodes) for wall in model.walls.values()
    }
    elements: list[ShellElementCommand] = []
    for quad in sorted(model.shell_quads.values(), key=lambda item: item.tag):
        local_x = local_x_by_wall.get(quad.wall_tag)
        if local_x is None:
            continue
        elements.append(
            ShellElementCommand(
                tag=quad.tag,
                node_1=quad.node_1,
                node_2=quad.node_2,
                node_3=quad.node_3,
                node_4=quad.node_4,
                section_tag=shell_section_tag(quad.wall_tag),
                local_x=local_x,
            )
        )
    return sections, elements


def build_shell_elements(model: StructuralModel) -> None:
    """Emit ``ElasticMembranePlateSection`` + ``ASDShellQ4`` into the live domain.

    No-op when the model has no generated quads, so every existing beam/truss
    solve path is byte-identical besides this extra call.
    """
    sections, elements = shell_build_plan(model)
    for section in sections:
        ops.section(
            "ElasticMembranePlateSection",
            section.tag,
            section.elastic_modulus,
            section.poisson_ratio,
            section.thickness,
            section.density,
        )
    for element in elements:
        lx, ly, lz = element.local_x
        ops.element(
            "ASDShellQ4",
            element.tag,
            element.node_1,
            element.node_2,
            element.node_3,
            element.node_4,
            element.section_tag,
            "-local",
            lx,
            ly,
            lz,
        )


def _section_command(wall: WallPanel) -> ShellSectionCommand:
    return ShellSectionCommand(
        tag=shell_section_tag(wall.tag),
        elastic_modulus=wall.elastic_modulus,
        poisson_ratio=wall.poisson_ratio,
        thickness=wall.thickness,
        density=wall.density,
    )
