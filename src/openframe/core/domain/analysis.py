"""Analysis selection and request data shared across feature boundaries."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class AnalysisKind(StrEnum):
    LINEAR_STATIC = "linear_static"
    NONLINEAR_STATIC = "nonlinear_static"
    TIME_HISTORY = "time_history"
    MODAL = "modal"
    BUCKLING = "buckling"
    RESPONSE_SPECTRUM = "response_spectrum"


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    source_path: Path
    kind: AnalysisKind = AnalysisKind.LINEAR_STATIC
    options: dict[str, float | int | str | bool] = field(default_factory=dict)

