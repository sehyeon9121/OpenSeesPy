from pathlib import Path

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.linear_static.module import LinearStaticAnalysis


class _StubRunner:
    def __init__(self, result: AnalysisResult) -> None:
        self.result = result
        self.received_request: AnalysisRequest | None = None

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        self.received_request = request
        return self.result


def test_run_delegates_to_injected_runner() -> None:
    expected = AnalysisResult(status=AnalysisStatus.COMPLETED)
    runner = _StubRunner(expected)
    module = LinearStaticAnalysis(runner)
    request = AnalysisRequest(source_path=Path("model.py"), kind=AnalysisKind.LINEAR_STATIC)

    result = module.run(request)

    assert result is expected
    assert runner.received_request is request


def test_validate_rejects_non_python_source() -> None:
    module = LinearStaticAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(AnalysisRequest(source_path=Path("model.txt")))

    assert errors == ["Python 파일이 필요합니다."]
