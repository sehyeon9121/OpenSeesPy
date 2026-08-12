"""Framework-independent structural engineering domain objects."""

from openframe.core.domain.analysis import AnalysisKind, AnalysisRequest
from openframe.core.domain.analysis_capabilities import (
    ANALYSIS_CAPABILITIES,
    AnalysisCapabilities,
    ComponentField,
    FieldState,
)
from openframe.core.domain.ground_motion import GroundMotionRecord, GroundMotionSource
from openframe.core.domain.materials import (
    MaterialDefinition,
    MaterialFamily,
    MaterialSource,
    ShearDeformationSettings,
    ShearModulusMode,
)
from openframe.core.domain.model import (
    BoundaryCondition,
    Element,
    LoadCaseKind,
    NodalLoad,
    Node,
    StructuralModel,
    SupportKind,
    UniformElementLoad,
)
from openframe.core.domain.results import (
    AnalysisResult,
    AnalysisStatus,
    ElementResult,
    LoadDisplacementPoint,
    ModeShape,
    NodeResult,
    NonlinearConvergence,
    TimeHistoryStep,
)
from openframe.core.domain.units import (
    DEFAULT_UNIT_SYSTEM,
    FORCE_UNITS,
    LENGTH_UNITS,
    TIME_UNITS,
    UnitSystem,
)

__all__ = [
    "ANALYSIS_CAPABILITIES",
    "DEFAULT_UNIT_SYSTEM",
    "FORCE_UNITS",
    "LENGTH_UNITS",
    "TIME_UNITS",
    "AnalysisCapabilities",
    "AnalysisKind",
    "AnalysisRequest",
    "AnalysisResult",
    "AnalysisStatus",
    "BoundaryCondition",
    "ComponentField",
    "Element",
    "ElementResult",
    "FieldState",
    "GroundMotionRecord",
    "GroundMotionSource",
    "LoadCaseKind",
    "LoadDisplacementPoint",
    "MaterialDefinition",
    "MaterialFamily",
    "MaterialSource",
    "ModeShape",
    "NodalLoad",
    "Node",
    "NodeResult",
    "NonlinearConvergence",
    "ShearDeformationSettings",
    "ShearModulusMode",
    "StructuralModel",
    "SupportKind",
    "TimeHistoryStep",
    "UniformElementLoad",
    "UnitSystem",
]
