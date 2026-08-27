"""run_precheck - the method-agnostic rules (empty model, static analysis
with no load, "not wired to execution yet" notice) plus Time History's own
settings-dependent rules now that its Quick Settings page exists. Every
other per-kind rule from the full spec slots in once its own settings field
exists on AnalysisCase (see analysis_case.py's own docstring for why
settings is still a plain dict in this pass)."""

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
    to the two kinds that actually solve, Linear/Nonlinear Static. Modal
    still gets the "not wired" INFO notice (see below), which never blocks
    can_run on its own."""
    model = _frame_model(with_load=False)

    report = run_precheck(_case(AnalysisKind.MODAL), model)

    assert report.can_run
    assert [issue.code for issue in report.issues] == ["not_wired"]
    assert report.issues[0].severity is Severity.INFO


def test_modal_and_buckling_and_time_history_get_a_not_wired_info_notice() -> None:
    model = _frame_model(with_load=True)

    for kind in (AnalysisKind.MODAL, AnalysisKind.BUCKLING):
        report = run_precheck(_case(kind), model)
        assert any(issue.code == "not_wired" and issue.severity is Severity.INFO for issue in report.issues)


def test_linear_and_nonlinear_static_get_no_not_wired_notice() -> None:
    """These are the two kinds MaterialFreeStaticsSolver actually runs -
    they must never be told they are unsupported."""
    model = _frame_model(with_load=True)

    for kind in (AnalysisKind.LINEAR_STATIC, AnalysisKind.NONLINEAR_STATIC):
        report = run_precheck(_case(kind), model)
        assert not any(issue.code == "not_wired" for issue in report.issues)


def _time_history_case(settings: dict[str, object]) -> AnalysisCase:
    case = _case(AnalysisKind.TIME_HISTORY)
    case.settings = settings
    return case


_VALID_TIME_HISTORY_SETTINGS: dict[str, object] = {
    "active_x": True,
    "active_y": False,
    "active_z": False,
    "ground_motion_x": {"name": "Kobe"},
    "ground_motion_y": None,
    "ground_motion_z": None,
    "output_dt": 0.01,
    "analysis_dt": 0.005,
    "start_time": 0.0,
    "end_time": 10.0,
}


def test_time_history_with_no_active_direction_cannot_run() -> None:
    model = _frame_model(with_load=False)
    settings = {**_VALID_TIME_HISTORY_SETTINGS, "active_x": False}

    report = run_precheck(_time_history_case(settings), model)

    assert not report.can_run
    assert any(issue.code == "no_active_direction" for issue in report.issues)


def test_time_history_active_direction_without_ground_motion_cannot_run() -> None:
    model = _frame_model(with_load=False)
    settings = {**_VALID_TIME_HISTORY_SETTINGS, "ground_motion_x": None}

    report = run_precheck(_time_history_case(settings), model)

    assert not report.can_run
    assert any(issue.code == "missing_ground_motion_x" for issue in report.issues)


def test_time_history_with_everything_valid_has_no_errors() -> None:
    model = _frame_model(with_load=False)  # Time History never requires model.nodal_loads

    report = run_precheck(_time_history_case(_VALID_TIME_HISTORY_SETTINGS), model)

    assert report.can_run
    assert not any(issue.severity is Severity.ERROR for issue in report.issues)


def test_time_history_rejects_non_positive_dt() -> None:
    model = _frame_model(with_load=False)
    for key in ("output_dt", "analysis_dt"):
        settings = {**_VALID_TIME_HISTORY_SETTINGS, key: 0.0}
        report = run_precheck(_time_history_case(settings), model)
        assert not report.can_run
        assert any(issue.code == f"invalid_{key}" for issue in report.issues)


def test_time_history_rejects_end_time_not_after_start_time() -> None:
    model = _frame_model(with_load=False)
    settings = {**_VALID_TIME_HISTORY_SETTINGS, "start_time": 10.0, "end_time": 10.0}

    report = run_precheck(_time_history_case(settings), model)

    assert not report.can_run
    assert any(issue.code == "invalid_time_window" for issue in report.issues)


def test_precheck_report_can_run_is_false_only_when_an_error_is_present() -> None:
    from openframe.features.model.presentation.analysis_precheck import PrecheckIssue, PrecheckReport

    warning_only = PrecheckReport((PrecheckIssue(Severity.WARNING, "w", "warn"),))
    assert warning_only.can_run is True
    assert warning_only.has_warnings is True

    with_error = PrecheckReport((PrecheckIssue(Severity.ERROR, "e", "err"),))
    assert with_error.can_run is False
