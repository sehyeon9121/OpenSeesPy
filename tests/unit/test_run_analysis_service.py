from pathlib import Path

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.application.run_analysis import RunAnalysisService


class _StubModule:
    def __init__(self, errors: list[str] | None = None, result: AnalysisResult | None = None) -> None:
        self._errors = errors or []
        self._result = result or AnalysisResult(status=AnalysisStatus.COMPLETED)
        self.ran = False

    def validate(self, request: AnalysisRequest) -> list[str]:
        return list(self._errors)

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        self.ran = True
        return self._result


def _request(kind: AnalysisKind = AnalysisKind.LINEAR_STATIC) -> AnalysisRequest:
    return AnalysisRequest(source_path=Path("model.py"), kind=kind)


def test_dispatches_to_module_matching_request_kind() -> None:
    linear = _StubModule()
    service = RunAnalysisService({AnalysisKind.LINEAR_STATIC: linear})

    result = service.execute(_request())

    assert linear.ran
    assert result.status == AnalysisStatus.COMPLETED


def test_validation_errors_short_circuit_before_run() -> None:
    module = _StubModule(errors=["Python 파일이 필요합니다."])
    service = RunAnalysisService({AnalysisKind.LINEAR_STATIC: module})

    result = service.execute(_request())

    assert not module.ran
    assert result.status == AnalysisStatus.FAILED
    assert result.messages == ["Python 파일이 필요합니다."]


def test_unregistered_kind_fails_without_crashing() -> None:
    service = RunAnalysisService({})

    result = service.execute(_request(AnalysisKind.NONLINEAR_STATIC))

    assert result.status == AnalysisStatus.FAILED
    assert result.messages
