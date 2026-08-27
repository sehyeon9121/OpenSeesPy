"""run_precheck - the two rules this first pass implements (empty model,
static analysis with no load). Every other rule from the full spec slots in
once its own settings field exists on AnalysisCase (see analysis_case.py's
own docstring for why settings is still a plain dict in this pass)."""

from openframe.core.domain import AnalysisKind, Element, NodalLoad, Node, StructuralModel
from openframe.features.model.presentation.analysis_case import AnalysisCase
from openframe.features.model.presentation.analysis_precheck import Severity, run_precheck


def _case(kind: AnalysisKind) -> AnalysisCase:
    return AnalysisCase.new(kind, "test-case")


def test_empty_model_is_an_error_for_every_kind() -> None:
    model = StructuralModel(ndm=2)

    for kind in (AnalysisKind.LINEAR_STATIC, AnalysisKind.MODAL, AnalysisKind.TIME_HISTORY):
        report = run_precheck(_case(kind), model)
        assert not report.can_run
        assert any(issue.code == "empty_model" for issue in report.issues)
        assert all(issue.severity is Severity.ERROR for issue in report.issues)


def _frame_model(*, with_load: bool) -> StructuralModel:
    return StructuralModel(
        ndm=2,
        nodes={1: Node(1, 0.0, 0.0), 2: Node(2, 4.0, 0.0)},
        elements={1: Element(1, 1, 2, "frame", properties={"E": 200000.0, "A": 0.02, "I": 0.0002})},
        nodal_loads=[NodalLoad(2, (0.0, -10.0, 0.0))] if with_load else [],
    )


def test_static_analysis_with_no_load_cannot_run() -> None:
    model = _frame_model(with_load=False)

    report = run_precheck(_case(AnalysisKind.LINEAR_STATIC), model)

    assert not report.can_run
    assert any(issue.code == "no_load" for issue in report.issues)


def test_static_analysis_with_a_load_has_no_issues() -> None:
    model = _frame_model(with_load=True)

    report = run_precheck(_case(AnalysisKind.LINEAR_STATIC), model)

    assert report.can_run
    assert report.issues == ()


def test_nonlinear_static_also_requires_a_load() -> None:
    model = _frame_model(with_load=False)

    report = run_precheck(_case(AnalysisKind.NONLINEAR_STATIC), model)

    assert not report.can_run


def test_a_non_static_kind_does_not_require_a_load() -> None:
    """Modal/Buckling/Time History have no execution path in this canvas at
    all yet (see the plan's own §10) - the load-required rule only applies
    to the two kinds that actually solve, Linear/Nonlinear Static."""
    model = _frame_model(with_load=False)

    report = run_precheck(_case(AnalysisKind.MODAL), model)

    assert report.can_run
    assert report.issues == ()


def test_precheck_report_can_run_is_false_only_when_an_error_is_present() -> None:
    from openframe.features.model.presentation.analysis_precheck import PrecheckIssue, PrecheckReport

    warning_only = PrecheckReport((PrecheckIssue(Severity.WARNING, "w", "warn"),))
    assert warning_only.can_run is True
    assert warning_only.has_warnings is True

    with_error = PrecheckReport((PrecheckIssue(Severity.ERROR, "e", "err"),))
    assert with_error.can_run is False
