"""Domain-level structural topology precheck — no OpenSees, no stiffness matrix."""

import ast
from pathlib import Path

from openframe.core.domain import (
    AnalysisKind,
    BoundaryCondition,
    Element,
    Node,
    RigidDiaphragm,
    StructuralModel,
)
from openframe.features.model.application.structural_precheck import (
    StructuralPrecheckSeverity,
    run_structural_precheck,
)
from openframe.features.model.presentation.analysis_case import AnalysisCase
from openframe.features.model.presentation.analysis_precheck import run_precheck


def _codes(model: StructuralModel) -> list[str]:
    return [issue.code for issue in run_structural_precheck(model)]


def _issues_of(model: StructuralModel, code: str):
    return [issue for issue in run_structural_precheck(model) if issue.code == code]


def _stable_3d_frame() -> StructuralModel:
    return StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, ndf=6),
            2: Node(2, 0.0, 0.0, 4.0, ndf=6),
        },
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )


def _tetrahedral_truss(*, ndf: int) -> StructuralModel:
    """Apex free, three pinned bases — a valid space truss."""
    return StructuralModel(
        ndm=3,
        ndf=ndf,
        nodes={
            1: Node(1, 0.0, 0.0, 3.0, ndf=ndf),
            2: Node(2, -2.0, -2.0, 0.0, ndf=ndf),
            3: Node(3, 2.0, -2.0, 0.0, ndf=ndf),
            4: Node(4, 0.0, 2.0, 0.0, ndf=ndf),
        },
        elements={
            1: Element(1, 1, 2, "truss"),
            2: Element(2, 1, 3, "truss"),
            3: Element(3, 1, 4, "truss"),
        },
        boundaries=[
            BoundaryCondition(2, (True, True, True)),
            BoundaryCondition(3, (True, True, True)),
            BoundaryCondition(4, (True, True, True)),
        ],
    )


def test_stable_3d_frame_has_no_issues() -> None:
    assert run_structural_precheck(_stable_3d_frame()) == ()


def test_isolated_user_node_is_detected() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, ndf=6),
            2: Node(2, 0.0, 0.0, 4.0, ndf=6),
            17: Node(17, 10.0, 0.0, 0.0, ndf=6),
        },
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )

    issues = _issues_of(model, "isolated_node")
    assert len(issues) == 1
    assert issues[0].severity is StructuralPrecheckSeverity.ERROR
    assert issues[0].node_tags == (17,)
    assert "17" in issues[0].message


def test_unsupported_component_is_detected() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={tag: Node(tag, float(tag), 0.0, 0.0, ndf=6) for tag in range(21, 29)},
        elements={
            tag: Element(tag, tag, tag + 1, "frame") for tag in range(21, 28)
        },
    )

    issues = _issues_of(model, "unsupported_component")
    assert len(issues) == 1
    assert issues[0].severity is StructuralPrecheckSeverity.ERROR
    assert issues[0].node_tags == tuple(range(21, 29))
    assert "21–28" in issues[0].message


def test_supported_component_is_not_reported_as_floating() -> None:
    model = StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True, True, False))],
    )
    assert "unsupported_component" not in _codes(model)


def test_tetrahedral_truss_has_no_instability_error() -> None:
    """A valid space truss must not be flagged as unstable.

    Canvas 3D models declare ndf=6, so unused rotations may produce INFO, but
    never an ERROR that would block the run as if the truss were a mechanism.
    """
    for ndf in (3, 6):
        issues = run_structural_precheck(_tetrahedral_truss(ndf=ndf))
        assert not any(
            issue.severity is StructuralPrecheckSeverity.ERROR for issue in issues
        )
        if ndf < 6:
            assert issues == ()
        else:
            info = [issue for issue in issues if issue.code == "truss_rotational_dof"]
            assert len(info) == 1
            assert info[0].severity is StructuralPrecheckSeverity.INFO


def test_normal_hinge_frame_is_not_a_mechanism() -> None:
    """Gerber-style interior release: one member stays continuous at the joint.

    Matches canvas ``_apply_hinge_releases``, which keeps one end rigid at an
    unrestrained hinge node. Must not emit orphan-release or any ERROR.
    """
    model = StructuralModel(
        ndm=2,
        nodes={
            1: Node(1, 0.0, 0.0),
            2: Node(2, 4.0, 0.0),
            3: Node(3, 8.0, 0.0),
        },
        elements={
            1: Element(1, 1, 2, "frame"),
            2: Element(2, 2, 3, "frame", moment_release_i=True),
        },
        boundaries=[
            BoundaryCondition(1, (True, True, False)),
            BoundaryCondition(3, (False, True, False)),
        ],
    )
    issues = run_structural_precheck(model)
    assert issues == ()


def test_zero_length_element_is_detected() -> None:
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, ndf=6),
            2: Node(2, 0.0, 0.0, 0.0, ndf=6),
            3: Node(3, 0.0, 0.0, 4.0, ndf=6),
        },
        elements={
            1: Element(1, 1, 2, "frame"),
            2: Element(2, 2, 3, "frame"),
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )

    issues = _issues_of(model, "zero_length_element")
    assert len(issues) == 1
    assert issues[0].severity is StructuralPrecheckSeverity.ERROR
    assert issues[0].element_tags == (1,)
    assert issues[0].node_tags == (1, 2)


def test_auxiliary_dummy_node_is_not_reported_as_a_user_error() -> None:
    """Hinge/support dummy tags live in the solver, not on StructuralModel.
    If one nevertheless appears in ``nodes``, it must not look like a user
    isolated-node mistake.
    """
    dummy_tag = 8_000_000
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, ndf=6),
            2: Node(2, 0.0, 0.0, 4.0, ndf=6),
            dummy_tag: Node(dummy_tag, 0.0, 0.0, 4.0, ndf=6),
            17: Node(17, 10.0, 0.0, 0.0, ndf=6),
        },
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True,) * 6)],
    )

    isolated = _issues_of(model, "isolated_node")
    assert [issue.node_tags for issue in isolated] == [(17,)]
    assert all(dummy_tag not in issue.node_tags for issue in run_structural_precheck(model))


def test_all_released_joint_is_info_not_a_mechanism_error() -> None:
    """Every frame end at the joint released — the solver pins joint rotation.
    Reportable, but not as an instability ERROR.
    """
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, ndf=6),
            2: Node(2, 4.0, 0.0, 0.0, ndf=6),
            3: Node(3, 8.0, 0.0, 0.0, ndf=6),
        },
        elements={
            1: Element(1, 1, 2, "frame", moment_release_j=True),
            2: Element(2, 2, 3, "frame", moment_release_i=True),
        },
        boundaries=[
            BoundaryCondition(1, (True,) * 6),
            BoundaryCondition(3, (True, True, True, False, False, False)),
        ],
    )
    issues = _issues_of(model, "orphan_release_rotation")
    assert len(issues) == 1
    assert issues[0].severity is StructuralPrecheckSeverity.INFO
    assert issues[0].node_tags == (2,)
    assert not any(
        issue.severity is StructuralPrecheckSeverity.ERROR
        for issue in run_structural_precheck(model)
    )


def test_rigid_diaphragm_ties_otherwise_separate_frames_for_support() -> None:
    """A supported frame plus an unsupported frame sharing a diaphragm must
    not be reported as a floating component — the floor tie is connectivity
    for this coarse check. Exact in-plane vs out-of-plane mechanisms are
    left to the matrix diagnostic.
    """
    model = StructuralModel(
        ndm=3,
        ndf=6,
        nodes={
            1: Node(1, 0.0, 0.0, 0.0, ndf=6),
            2: Node(2, 0.0, 0.0, 4.0, ndf=6),
            3: Node(3, 8.0, 0.0, 0.0, ndf=6),
            4: Node(4, 8.0, 0.0, 4.0, ndf=6),
        },
        elements={
            1: Element(1, 1, 2, "frame"),
            2: Element(2, 3, 4, "frame"),
        },
        boundaries=[BoundaryCondition(1, (True,) * 6)],
        rigid_diaphragms=(RigidDiaphragm(perp_dirn=3, master_tag=2, slave_tags=(4,)),),
    )
    assert "unsupported_component" not in _codes(model)


def test_precheck_module_does_not_import_opensees_or_solvers() -> None:
    """This layer must stay off the OpenSees / FullGeneral path the other
    worker is validating — a stray solver import would pull openseespy in
    at module load and couple the two jobs.
    """
    path = (
        Path(__file__).parents[2]
        / "src"
        / "openframe"
        / "features"
        / "model"
        / "application"
        / "structural_precheck.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = (
        "openseespy",
        "openframe.features.analysis.statics.solver",
        "openframe.infrastructure.opensees",
    )
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imported
        for prefix in forbidden
    )


def test_run_precheck_surfaces_isolated_node() -> None:
    model = StructuralModel(
        ndm=2,
        nodes={
            1: Node(1, 0.0, 0.0),
            2: Node(2, 4.0, 0.0),
            17: Node(17, 10.0, 0.0),
        },
        elements={1: Element(1, 1, 2, "frame")},
        boundaries=[BoundaryCondition(1, (True, True, True))],
    )
    report = run_precheck(AnalysisCase.new(AnalysisKind.LINEAR_STATIC, "case"), model)
    assert any(issue.code == "isolated_node" for issue in report.issues)
    assert not report.can_run
