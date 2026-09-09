"""Independent textbook/matrix checks for the 2D linear classroom workflow."""

from dataclasses import replace

import numpy as np
import pytest

from openframe.core.domain import (
    AnalysisStatus, BoundaryCondition, Element, NodalLoad, Node, StructuralModel,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver


def _model(*, redundant=False, reverse=False, scale=1.0):
    points = [(0, 0), (3, 0), (6, 0), (1.5, 2), (4.5, 2)]
    pairs = [(1, 2), (2, 3), (1, 4), (4, 2), (2, 5), (5, 3), (4, 5)]
    if redundant:
        pairs.append((1, 5))
    return StructuralModel(
        ndm=2,
        nodes={i: Node(i, x*scale, y*scale) for i, (x, y) in enumerate(points, 1)},
        elements={
            i: Element(i, *(pair[::-1] if reverse else pair), "truss",
                       properties={"E": (180e6+i*1e6)/scale**2, "A": (0.001+i*0.0002)*scale**2})
            for i, pair in enumerate(pairs, 1)
        },
        boundaries=[BoundaryCondition(1, (True, True)), BoundaryCondition(3, (False, True))],
        nodal_loads=[NodalLoad(4, (7.0, -20.0)), NodalLoad(5, (-3.0, -10.0))],
    )


def _reference(model):
    tags = list(model.nodes)
    indexes = {tag: 2*i for i, tag in enumerate(tags)}
    stiffness = np.zeros((2*len(tags), 2*len(tags)))
    force = np.zeros(2*len(tags))
    for member in model.elements.values():
        a, b = model.nodes[member.node_i], model.nodes[member.node_j]
        delta = np.array([b.x-a.x, b.y-a.y])
        length = np.linalg.norm(delta)
        extension = np.r_[-delta/length, delta/length]
        dofs = [indexes[member.node_i]+j for j in (0, 1)] + [indexes[member.node_j]+j for j in (0, 1)]
        stiffness[np.ix_(dofs, dofs)] += member.properties['E']*member.properties['A']/length*np.outer(extension, extension)
    for load in model.nodal_loads:
        force[indexes[load.node_tag]:indexes[load.node_tag]+2] += load.values[:2]
    fixed = [indexes[b.node_tag]+i for b in model.boundaries for i, value in enumerate(b.restraints[:2]) if value]
    free = np.setdiff1d(np.arange(len(force)), fixed)
    displacement = np.zeros_like(force)
    displacement[free] = np.linalg.solve(stiffness[np.ix_(free, free)], force[free])
    return indexes, displacement, stiffness@displacement-force


@pytest.mark.parametrize('redundant', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('scale', [1.0, 1000.0])
def test_textbook_truss_matches_independent_stiffness_solution(redundant, reverse, scale):
    model = _model(redundant=redundant, reverse=reverse, scale=scale)
    indexes, displacements, reactions = _reference(model)
    result = MaterialFreeStaticsSolver().solve(model)
    assert result.status == AnalysisStatus.COMPLETED
    for tag, index in indexes.items():
        assert result.node_results[tag].displacement == pytest.approx(displacements[index:index+2], abs=1e-8)
        assert result.node_results[tag].reaction == pytest.approx(reactions[index:index+2], abs=1e-8)
    for member in model.elements.values():
        a, b = model.nodes[member.node_i], model.nodes[member.node_j]
        delta = np.array([b.x-a.x, b.y-a.y])
        relative = displacements[indexes[b.tag]:indexes[b.tag]+2]-displacements[indexes[a.tag]:indexes[a.tag]+2]
        axial = member.properties['E']*member.properties['A']*np.dot(relative, delta)/np.dot(delta, delta)
        assert result.element_results[member.tag].local_forces == pytest.approx((-axial, 0, 0, axial, 0, 0), abs=1e-8)


def test_truss_spring_reaction_balances_applied_load():
    model = StructuralModel(ndm=2, nodes={1: Node(1, 0, 0), 2: Node(2, 2, 0)},
        elements={1: Element(1, 1, 2, 'truss', properties={'E': 2e8, 'A': 0.01})},
        boundaries=[BoundaryCondition(1, (True, True)),
                    BoundaryCondition(2, (False, False), spring_stiffnesses=(None, 500.0))],
        nodal_loads=[NodalLoad(2, (10.0, -20.0))])
    result = MaterialFreeStaticsSolver().solve(model)
    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[2].displacement == pytest.approx((1e-5, -0.04))
    assert result.node_results[2].reaction == pytest.approx((0.0, 20.0), abs=1e-8)


def test_truss_nodal_moment_is_rejected_instead_of_discarded():
    model = _model()
    model.nodal_loads.append(NodalLoad(4, (0.0, 0.0, 10.0)))
    result = MaterialFreeStaticsSolver().solve(model)
    assert result.status == AnalysisStatus.FAILED
    assert any('모멘트' in message for message in result.messages)


@pytest.mark.parametrize('bad', [-1.0, 0.0, float('nan'), float('inf')])
def test_invalid_explicit_stiffness_does_not_become_unit_stiffness(bad):
    model = _model()
    model.elements[1] = replace(model.elements[1], properties={'E': bad, 'A': 0.01})
    result = MaterialFreeStaticsSolver().solve(model)
    assert result.status == AnalysisStatus.FAILED


def test_geometric_mechanism_with_zero_count_is_not_a_valid_linear_solution():
    model = StructuralModel(ndm=2,
        nodes={1: Node(1, 0, 0), 2: Node(2, 1, 0), 3: Node(3, 2, 0)},
        elements={1: Element(1, 1, 2, 'truss', properties={'E': 1000, 'A': 1}),
                  2: Element(2, 2, 3, 'truss', properties={'E': 1000, 'A': 1})},
        boundaries=[BoundaryCondition(1, (True, True)), BoundaryCondition(3, (True, True))],
        nodal_loads=[NodalLoad(2, (1.0, -1.0))])
    result = MaterialFreeStaticsSolver().solve(model)
    assert result.status == AnalysisStatus.FAILED
    assert not result.node_results

