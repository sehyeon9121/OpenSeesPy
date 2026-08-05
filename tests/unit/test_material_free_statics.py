import pytest

from openframe.core.domain import (
    AnalysisStatus,
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
    UniformElementLoad,
)
from openframe.features.analysis.statics import MaterialFreeStaticsSolver, check_determinacy
from openframe.features.results.diagrams import member_diagrams


def _simply_supported_beam() -> StructuralModel:
    return StructuralModel(
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[
            BoundaryCondition(1, (True, True, False)),
            BoundaryCondition(2, (False, True, False)),
        ],
        element_loads=[UniformElementLoad(1, wy=-10.0)],
    )


def test_determinate_beam_is_solved_without_material_properties() -> None:
    model = _simply_supported_beam()

    assert check_determinacy(model).degree == 0
    result = MaterialFreeStaticsSolver().solve(model)

    assert result.status == AnalysisStatus.COMPLETED
    assert result.node_results[1].reaction[1] == pytest.approx(20.0)
    assert result.node_results[2].reaction[1] == pytest.approx(20.0)
    _, shear, moment = member_diagrams(result.element_results[1])
    assert max(point.value for point in moment.points) == pytest.approx(20.0)
    assert shear.points[0].value == pytest.approx(20.0)
    assert shear.points[-1].value == pytest.approx(-20.0)


def test_cantilever_point_load_reaction_and_moment() -> None:
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


def test_indeterminate_beam_requires_stiffness_instead_of_using_fake_values() -> None:
    model = _simply_supported_beam()
    model.boundaries[1] = BoundaryCondition(2, (True, True, False))

    check = check_determinacy(model)
    result = MaterialFreeStaticsSolver().solve(model)

    assert check.degree == 1
    assert result.status == AnalysisStatus.FAILED
    assert "부정정" in result.messages[0]
