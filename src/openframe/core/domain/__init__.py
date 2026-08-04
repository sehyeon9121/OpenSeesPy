"""Framework-independent structural engineering domain objects."""

from openframe.core.domain.analysis import AnalysisKind, AnalysisRequest
from openframe.core.domain.model import (
    BoundaryCondition,
    Element,
    NodalLoad,
    Node,
    StructuralModel,
    SupportKind,
)
from openframe.core.domain.results import (
    AnalysisResult,
    AnalysisStatus,
    ElementResult,
    NodeResult,
)

__all__ = [
    "AnalysisKind",
    "AnalysisRequest",
    "AnalysisResult",
    "AnalysisStatus",
    "BoundaryCondition",
    "Element",
    "ElementResult",
    "NodalLoad",
    "Node",
    "NodeResult",
    "StructuralModel",
    "SupportKind",
]
