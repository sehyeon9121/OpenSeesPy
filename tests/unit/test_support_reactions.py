from openframe.core.domain import (
    AnalysisResult,
    AnalysisStatus,
    BoundaryCondition,
    Node,
    NodeResult,
    StructuralModel,
)
from openframe.features.results.reactions import reaction_resultant, support_reactions


def _model() -> StructuralModel:
    return StructuralModel(
        nodes={
            1: Node(tag=1, x=0.0, y=0.0),
            2: Node(tag=2, x=4.0, y=0.0),
            3: Node(tag=3, x=2.0, y=3.0),
        },
        boundaries=[
            BoundaryCondition(node_tag=1, restraints=(True, True, False)),
            BoundaryCondition(node_tag=2, restraints=(False, True, False)),
        ],
    )


def _result() -> AnalysisResult:
    return AnalysisResult(
        status=AnalysisStatus.COMPLETED,
        node_results={
            1: NodeResult(node_tag=1, reaction=(-35.0, 30.0, 0.0)),
            2: NodeResult(node_tag=2, reaction=(0.0, 50.0, 0.0)),
            3: NodeResult(node_tag=3, reaction=(0.0, 0.0, 0.0)),
        },
    )


def test_returns_one_entry_per_restrained_node_with_coordinates() -> None:
    reactions = support_reactions(_model(), _result())

    assert [reaction.node_tag for reaction in reactions] == [1, 2]
    assert (reactions[0].x, reactions[0].y) == (0.0, 0.0)
    assert (reactions[1].x, reactions[1].y) == (4.0, 0.0)
    assert (reactions[0].fx, reactions[0].fy) == (-35.0, 30.0)
    assert (reactions[1].fx, reactions[1].fy) == (0.0, 50.0)


def test_unrestrained_nodes_are_excluded() -> None:
    reactions = support_reactions(_model(), _result())

    assert all(reaction.node_tag != 3 for reaction in reactions)


def test_solver_noise_is_reported_as_zero() -> None:
    model = _model()
    result = _result()
    result.node_results[2] = NodeResult(node_tag=2, reaction=(3.2e-11, 50.0, 0.0))

    reactions = support_reactions(model, result)

    noisy = next(item for item in reactions if item.node_tag == 2)
    assert noisy.fx == 0.0
    assert noisy.fy == 50.0


def test_moment_noise_is_zeroed_even_when_no_real_moment_reaction_exists() -> None:
    """Regression: a pin+roller frame has no real Mz anywhere, so judging noise
    against other Mz values compares noise to noise and lets it through."""
    model = _model()
    result = _result()
    result.node_results[1] = NodeResult(node_tag=1, reaction=(-35.0, 30.0, 1.1e-12))
    result.node_results[2] = NodeResult(node_tag=2, reaction=(0.0, 50.0, -2.3e-12))

    reactions = support_reactions(model, result)

    assert all(reaction.mz == 0.0 for reaction in reactions)
    assert all(not reaction.has_moment for reaction in reactions)


def test_resultant_sums_reactions_for_an_equilibrium_check() -> None:
    total_x, total_y = reaction_resultant(support_reactions(_model(), _result()))

    assert total_x == -35.0
    assert total_y == 80.0


def test_missing_node_result_is_skipped_without_error() -> None:
    model = _model()
    result = AnalysisResult(status=AnalysisStatus.COMPLETED, node_results={})

    assert support_reactions(model, result) == ()
