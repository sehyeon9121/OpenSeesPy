from pathlib import Path

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.nonlinear_static.module import NonlinearStaticAnalysis


class _StubRunner:
    def __init__(self, result: AnalysisResult) -> None:
        self.result = result
        self.received_request: AnalysisRequest | None = None

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        self.received_request = request
        return self.result


def _request(**options: object) -> AnalysisRequest:
    return AnalysisRequest(
        source_path=Path("model.py"),
        kind=AnalysisKind.NONLINEAR_STATIC,
        options=options,
    )


def test_run_delegates_to_injected_runner() -> None:
    expected = AnalysisResult(status=AnalysisStatus.COMPLETED)
    runner = _StubRunner(expected)
    module = NonlinearStaticAnalysis(runner)
    request = _request(control_node=2)

    result = module.run(request)

    assert result is expected
    assert runner.received_request is request


def test_validate_rejects_non_python_source() -> None:
    module = NonlinearStaticAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(
        AnalysisRequest(
            source_path=Path("model.txt"),
            kind=AnalysisKind.NONLINEAR_STATIC,
            options={"control_node": 2},
        )
    )

    assert "Python 파일이 필요합니다." in errors


def test_validate_requires_control_node() -> None:
    module = NonlinearStaticAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(_request())

    assert errors == ["비선형 정적해석에는 CONTROL NODE 지정이 필요합니다."]


def test_validate_passes_with_control_node_set() -> None:
    module = NonlinearStaticAnalysis(_StubRunner(AnalysisResult()))

    assert module.validate(_request(control_node=2)) == []


def test_validate_requires_target_displacement_for_displacement_control() -> None:
    module = NonlinearStaticAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(
        _request(control_node=2, integrator_type="DisplacementControl")
    )

    assert errors == ["DisplacementControl에는 0이 아닌 TARGET DISPLACEMENT 값이 필요합니다."]


def test_validate_passes_for_displacement_control_with_a_target() -> None:
    module = NonlinearStaticAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(
        _request(
            control_node=2, integrator_type="DisplacementControl", target_displacement=0.5
        )
    )

    assert errors == []
