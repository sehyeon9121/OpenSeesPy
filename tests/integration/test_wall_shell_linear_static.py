"""WallPanel → structured quad → ASDShellQ4 through Linear Static."""

from __future__ import annotations

import math

import pytest

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
    WallPanel,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy
from openframe.features.model.surfaces import assemble_wall_meshes, wall_quad_payloads

# Same cantilever as tests/integration/test_asdshellq4_wall_spike.py.
_LW = 2.0
_H = 3.0
_THICKNESS = 0.2
_E = 30_000_000.0
_NU = 0.2
_P = 100.0
_SPIKE_2X2_TOP_UX = 2.689e-4
_SPIKE_4X4_TOP_UX = 2.883e-4


def _authored_wall(nx: int, ny: int) -> StructuralModel:
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, 6),
            2: Node(2, _LW, 0.0, 0.0, 6),
            3: Node(3, _LW, 0.0, _H, 6),
            4: Node(4, 0.0, 0.0, _H, 6),
        },
        walls={
            1: WallPanel(
                tag=1,
                node_1=1,
                node_2=2,
                node_3=3,
                node_4=4,
                thickness=_THICKNESS,
                nx=nx,
                ny=ny,
                elastic_modulus=_E,
                poisson_ratio=_NU,
            )
        },
    )


def _prepare_cantilever(nx: int, ny: int) -> StructuralModel:
    """Mesh first so base/top generated nodes can take fix/load tags.

    solve() remeshes with the same deterministic tags, so restraints
    written here still hit the OpenSees nodes that get built.
    """
    model = assemble_wall_meshes(_authored_wall(nx, ny))
    base = [node for node in model.nodes.values() if abs(node.z) <= 1.0e-12]
    top = [node for node in model.nodes.values() if abs(node.z - _H) <= 1.0e-12]
    assert len(base) == nx + 1
    assert len(top) == nx + 1
    model.boundaries = [
        BoundaryCondition(node.tag, (True, True, True, True, True, True)) for node in base
    ]
    share = _P / len(top)
    model.nodal_loads = [
        NodalLoad(node.tag, (share, 0.0, 0.0, 0.0, 0.0, 0.0)) for node in top
    ]
    return model


def _mean_top_ux(model: StructuralModel, result) -> float:
    top_tags = [tag for tag, node in model.nodes.items() if abs(node.z - _H) <= 1.0e-12]
    samples = [result.node_results[tag].displacement[0] for tag in top_tags]
    return sum(samples) / len(samples)


def _base_reaction_x(model: StructuralModel, result) -> float:
    return sum(
        result.node_results[tag].reaction[0]
        for tag, node in model.nodes.items()
        if abs(node.z) <= 1.0e-12
    )


def test_check_determinacy_treats_a_wall_only_model_as_shell_not_empty() -> None:
    check = check_determinacy(_authored_wall(2, 2))
    assert check.system == "shell"
    assert not check.can_solve_without_materials


def test_2x2_cantilever_wall_solves_through_the_linear_static_pipeline() -> None:
    model = _prepare_cantilever(2, 2)
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED, result.messages
    assert len(model.shell_quads) == 4
    top_ux = _mean_top_ux(model, result)
    assert top_ux == pytest.approx(_SPIKE_2X2_TOP_UX, rel=0.05)
    assert _base_reaction_x(model, result) == pytest.approx(-_P, rel=1e-6, abs=1e-6)
    mid_top = next(
        node.tag
        for node in model.nodes.values()
        if abs(node.z - _H) <= 1.0e-12 and abs(node.x - _LW / 2.0) <= 1.0e-12
    )
    disp = result.node_results[mid_top].displacement
    assert len(disp) == 6
    assert all(math.isfinite(value) for value in disp)


def test_4x4_cantilever_wall_matches_the_spike_top_displacement() -> None:
    model = _prepare_cantilever(4, 4)
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED, result.messages
    assert len(model.shell_quads) == 16
    top_ux = _mean_top_ux(model, result)
    assert top_ux == pytest.approx(_SPIKE_4X4_TOP_UX, rel=0.05)
    assert _base_reaction_x(model, result) == pytest.approx(-_P, rel=1e-6, abs=1e-6)


def test_generated_wall_mesh_nodes_collect_six_dof_displacement() -> None:
    model = _prepare_cantilever(2, 2)
    result = MaterialFreeStaticsSolver().solve(model)
    generated = [node for node in model.nodes.values() if node.is_wall_mesh]

    assert generated
    for node in generated:
        node_result = result.node_results[node.tag]
        assert len(node_result.displacement) == 6
        assert all(math.isfinite(value) for value in node_result.displacement)


def test_frame_node_results_are_unchanged_when_a_disconnected_wall_is_present() -> None:
    """Shell assembly must not rewrite beam element tags or steal frame DOFs.

    The wall sits far from the column and shares no nodes, so the column
    tip is independent of the wall solve. Both need real 3D stiffness
    because a wall forces the physical-stiffness path.
    """
    properties = {
        "E": 2.0e8,
        "A": 0.04,
        "G": 8.0e7,
        "J": 1.0e-4,
        "Iy": 1.0e-4,
        "Iz": 1.0e-4,
    }
    column = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            10: Node(10, 20.0, 0.0, 0.0, 6),
            11: Node(11, 20.0, 0.0, 4.0, 6),
        },
        elements={
            10: Element(10, 10, 11, "elasticBeamColumn", properties=properties),
        },
        boundaries=[BoundaryCondition(10, (True, True, True, True, True, True))],
        nodal_loads=[NodalLoad(11, (50.0, 0.0, 0.0, 0.0, 0.0, 0.0))],
    )
    beam_only = MaterialFreeStaticsSolver().solve(column)
    assert beam_only.status == AnalysisStatus.COMPLETED, beam_only.messages

    mixed = _authored_wall(2, 2)
    mixed.nodes[10] = column.nodes[10]
    mixed.nodes[11] = column.nodes[11]
    mixed.elements[10] = column.elements[10]
    mixed = assemble_wall_meshes(mixed)
    base = [node for node in mixed.nodes.values() if abs(node.z) <= 1.0e-12 and node.tag < 10]
    top = [node for node in mixed.nodes.values() if abs(node.z - _H) <= 1.0e-12 and node.tag < 10]
    share = _P / len(top)
    mixed.boundaries = [
        BoundaryCondition(node.tag, (True, True, True, True, True, True)) for node in base
    ] + list(column.boundaries)
    mixed.nodal_loads = [
        NodalLoad(node.tag, (share, 0.0, 0.0, 0.0, 0.0, 0.0)) for node in top
    ] + list(column.nodal_loads)
    combined = MaterialFreeStaticsSolver().solve(mixed)
    assert combined.status == AnalysisStatus.COMPLETED, combined.messages

    assert combined.node_results[11].displacement == pytest.approx(
        beam_only.node_results[11].displacement, rel=1e-6, abs=1e-9
    )
    assert combined.element_results[10].local_forces == pytest.approx(
        beam_only.element_results[10].local_forces, rel=1e-6, abs=1e-8
    )
    # Shell quads are not stuffed into ElementResult.local_forces.
    assert 10 in combined.element_results
    assert all(tag in mixed.elements for tag in combined.element_results)


def test_beam_only_linear_static_is_unchanged_without_walls() -> None:
    model = StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 3.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True, True, True))],
        nodal_loads=[NodalLoad(2, (0.0, -12.0, 0.0))],
    )
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[1].reaction[1] == pytest.approx(12.0)
    assert result.node_results[1].reaction[2] == pytest.approx(36.0)
    assert model.shell_quads == {}


def test_deformed_wall_payload_follows_solved_top_displacement() -> None:
    model = _prepare_cantilever(1, 1)
    result = MaterialFreeStaticsSolver().solve(model)
    assert result.status == AnalysisStatus.COMPLETED, result.messages
    displacements = {
        tag: node_result.displacement for tag, node_result in result.node_results.items()
    }
    undeformed = wall_quad_payloads(model)
    deformed = wall_quad_payloads(model, displacements=displacements, scale=1.0)
    top_left_u = deformed[0].corners[3][0] - undeformed[0].corners[3][0]
    assert top_left_u == pytest.approx(result.node_results[4].displacement[0])
    assert top_left_u > 0.0
