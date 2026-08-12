"""Nonlinear static analysis module: incremental LoadControl pushover, delegated to
an AnalysisRunner exactly like LinearStaticAnalysis - the kind/options on the request
tell OpenSeesProcessRunner which solver the worker subprocess should run."""

from collections.abc import Callable

from openframe.core.contracts import AnalysisRunner
from openframe.core.domain import AnalysisKind, AnalysisRequest, AnalysisResult
from openframe.features.analysis.common import AnalysisModule


class NonlinearStaticAnalysis(AnalysisModule):
    kind = AnalysisKind.NONLINEAR_STATIC

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    def validate(self, request: AnalysisRequest) -> list[str]:
        errors: list[str] = []
        options = request.options
        if request.source_path.suffix.lower() != ".py":
            errors.append("Python 파일이 필요합니다.")
        if options.get("control_node") is None:
            errors.append("비선형 정적해석에는 CONTROL NODE 지정이 필요합니다.")
        if options.get("integrator_type") == "DisplacementControl" and not options.get(
            "target_displacement"
        ):
            errors.append("DisplacementControl에는 0이 아닌 TARGET DISPLACEMENT 값이 필요합니다.")
        positive_fields = {
            "num_steps": "LOAD STEPS",
            "tolerance": "TOLERANCE",
            "max_iterations": "MAX ITERATIONS",
            "gravity_steps": "GRAVITY STEPS",
            "execution_timeout_seconds": "MAX RUNTIME",
            "target_load_factor": "TARGET LOAD FACTOR",
            "min_increment": "MIN INCREMENT",
            "max_increment": "MAX INCREMENT",
        }
        for field, label in positive_fields.items():
            value = options.get(field)
            if value is not None and float(value) <= 0:
                errors.append(f"{label} 값은 0보다 커야 합니다.")
        max_bisections = options.get("max_bisections")
        if max_bisections is not None and int(max_bisections) < 0:
            errors.append("MAX BISECTIONS 값은 0 이상이어야 합니다.")
        min_increment = options.get("min_increment")
        max_increment = options.get("max_increment")
        if (
            min_increment is not None
            and max_increment is not None
            and float(min_increment) > float(max_increment)
        ):
            errors.append("MIN INCREMENT는 MAX INCREMENT보다 클 수 없습니다.")
        if (
            options.get("gravity_pattern") is not None
            and options.get("lateral_pattern") == options.get("gravity_pattern")
        ):
            errors.append("GRAVITY PATTERN과 LATERAL PATTERN은 서로 달라야 합니다.")

        allowed_values = {
            "integrator_type": {"LoadControl", "DisplacementControl"},
            "algorithm": {"Newton", "ModifiedNewton", "KrylovNewton", "NewtonLineSearch"},
            "test_type": {"NormDispIncr", "EnergyIncr", "NormUnbalance"},
            "system": {"BandGeneral", "UmfPack", "ProfileSPD"},
            "constraints_type": {"Plain", "Transformation"},
            "numberer": {"RCM", "Plain", "AMD"},
            "geometric_transform_type": {"Linear", "PDelta", "Corotational"},
        }
        for field, allowed in allowed_values.items():
            value = options.get(field)
            if value is not None and str(value) not in allowed:
                errors.append(f"지원하지 않는 {field} 설정입니다: {value}")
        return errors

    def run(
        self,
        request: AnalysisRequest,
        *,
        progress_callback: Callable[[int | None, str], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> AnalysisResult:
        if progress_callback is None and cancellation_requested is None:
            return self._runner.run(request)
        return self._runner.run(
            request,
            progress_callback=progress_callback,
            cancellation_requested=cancellation_requested,
        )
