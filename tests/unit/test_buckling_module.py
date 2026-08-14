from pathlib import Path

from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult, AnalysisStatus
from openframe.features.analysis.buckling.module import BucklingAnalysis


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
        kind=AnalysisKind.BUCKLING,
        options=options,
    )


def test_run_delegates_to_injected_runner() -> None:
    expected = AnalysisResult(status=AnalysisStatus.COMPLETED)
    runner = _StubRunner(expected)
    module = BucklingAnalysis(runner)
    request = _request(num_modes=5)

    result = module.run(request)

    assert result is expected
    assert runner.received_request is request


def test_validate_rejects_non_python_source() -> None:
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(
        AnalysisRequest(source_path=Path("model.txt"), kind=AnalysisKind.BUCKLING, options={})
    )

    assert "Python 파일이 필요합니다." in errors


def test_validate_passes_with_no_options() -> None:
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    assert module.validate(_request()) == []


def test_validate_rejects_non_positive_num_modes() -> None:
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(_request(num_modes=0))

    assert errors == ["NUMBER OF MODES 값은 0보다 커야 합니다."]


def test_validate_rejects_zero_reference_load_scale() -> None:
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(_request(reference_load_scale=0))

    assert errors == ["REFERENCE LOAD SCALE은 0이 될 수 없습니다."]


def test_validate_rejects_non_positive_eigenvalue_tolerance() -> None:
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(_request(eigenvalue_tolerance=-1.0))

    assert errors == ["EIGENVALUE TOLERANCE 값은 0보다 커야 합니다."]


def test_validate_rejects_linear_geometric_transform() -> None:
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(_request(geometric_transform_type="Linear"))

    assert len(errors) == 1
    assert "Linear" in errors[0]


def test_validate_rejects_unsupported_geometric_transform() -> None:
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    errors = module.validate(_request(geometric_transform_type="Buckling"))

    assert errors == ["지원하지 않는 geometric_transform_type 설정입니다: Buckling"]


def test_validate_accepts_the_one_supported_geometric_transform_type() -> None:
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    assert module.validate(_request(geometric_transform_type="PDelta")) == []


def test_validate_rejects_not_yet_supported_geometric_transform_types() -> None:
    """Corotational/"From Model" are recognized, real transform types - just
    not offered yet (closing check after the feature's initial
    implementation) - so they get their own clear message, not the generic
    "unsupported setting" one."""
    module = BucklingAnalysis(_StubRunner(AnalysisResult()))

    for transform in ("Corotational", "UseModelDefinition"):
        errors = module.validate(_request(geometric_transform_type=transform))
        assert len(errors) == 1
        assert "P-Delta" in errors[0]
        assert transform in errors[0]
