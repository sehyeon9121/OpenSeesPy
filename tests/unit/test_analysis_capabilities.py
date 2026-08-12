"""Pure unit tests for the analysis capability metadata registry.

These only import ``openframe.core.domain`` - no Qt, no OpenSeesPy solve, no
subprocess. Test 6 is the important one long-term: it reads the actual
solver source files as plain text and checks that every ENGINE_FIXED/
AUTOMATIC value the registry claims still appears in the code that is
supposed to hardcode it, so the registry cannot silently drift away from
what the engine really does (e.g. someone changes Linear Static's equation
solver to "UmfPack" without updating the registry to match).
"""

import dataclasses
from pathlib import Path

from openframe.core.domain import (
    ANALYSIS_CAPABILITIES,
    AnalysisCapabilities,
    AnalysisKind,
    ComponentField,
    FieldState,
)

_COMPONENT_FIELD_NAMES = tuple(field.name for field in dataclasses.fields(AnalysisCapabilities))

_INFRASTRUCTURE_DIR = Path(__file__).parents[2] / "src" / "openframe" / "infrastructure" / "opensees"

#: Only kinds whose solver hardcodes literal ops.* values as plain string
#: arguments - Nonlinear Static's fields are all EDITABLE (no fixed value to
#: check), so it has no entry here.
_SOLVER_SOURCE_BY_KIND = {
    AnalysisKind.LINEAR_STATIC: _INFRASTRUCTURE_DIR / "linear_static_solver.py",
    AnalysisKind.MODAL: _INFRASTRUCTURE_DIR / "modal_solver.py",
    AnalysisKind.TIME_HISTORY: _INFRASTRUCTURE_DIR / "time_history_solver.py",
}


def _all_component_fields() -> list[tuple[AnalysisKind, str, ComponentField]]:
    return [
        (kind, name, getattr(capabilities, name))
        for kind, capabilities in ANALYSIS_CAPABILITIES.items()
        for name in _COMPONENT_FIELD_NAMES
    ]


def test_every_analysis_kind_has_a_capabilities_entry() -> None:
    assert set(ANALYSIS_CAPABILITIES.keys()) == set(AnalysisKind)


def test_every_component_field_has_a_valid_field_state() -> None:
    for kind, name, field in _all_component_fields():
        assert isinstance(field.state, FieldState), f"{kind}.{name} has an invalid state"


def test_engine_fixed_fields_always_carry_the_actual_engine_value() -> None:
    for kind, name, field in _all_component_fields():
        if field.state is FieldState.ENGINE_FIXED:
            assert field.value, f"{kind}.{name} is ENGINE_FIXED but has no value to display"


def test_automatic_fields_always_explain_how_the_engine_decides() -> None:
    for kind, name, field in _all_component_fields():
        if field.state is FieldState.AUTOMATIC:
            assert field.value or field.details, (
                f"{kind}.{name} is AUTOMATIC but explains nothing (no value, no details)"
            )


def test_nonlinear_static_editable_components_match_what_the_solver_actually_accepts() -> None:
    """run_nonlinear_static_analysis(..., algorithm=, test_type=, system=,
    constraints_type=, numberer=, integrator_type=, ...) really does take and
    use these six as keyword arguments (see nonlinear_static_solver.py) -
    this pins that set so a future edit cannot silently mark one of them
    ENGINE_FIXED (or add a phantom EDITABLE one) without this test noticing."""
    capabilities = ANALYSIS_CAPABILITIES[AnalysisKind.NONLINEAR_STATIC]
    editable = {
        "equation_solver",
        "algorithm",
        "static_integrator",
        "convergence_test",
        "constraint_handler",
        "numberer",
    }
    not_applicable = {"dynamic_integrator", "eigen_solver", "damping"}
    for name in editable:
        assert getattr(capabilities, name).state is FieldState.EDITABLE, name
    for name in not_applicable:
        assert getattr(capabilities, name).state is FieldState.NOT_APPLICABLE, name


def test_engine_fixed_and_automatic_values_still_appear_in_their_solver_source() -> None:
    """Drift guard: if a solver's hardcoded ops.* literal ever changes (e.g.
    Linear Static's equation solver stops being "BandGeneral"), the matching
    registry entry must be updated too, or this fails. Deliberately a plain
    substring check on the source file's text, not an AST walk - simplest
    thing that actually catches the drift this registry exists to prevent."""
    for kind, source_path in _SOLVER_SOURCE_BY_KIND.items():
        source_text = source_path.read_text(encoding="utf-8").lower()
        capabilities = ANALYSIS_CAPABILITIES[kind]
        for name in _COMPONENT_FIELD_NAMES:
            field = getattr(capabilities, name)
            if field.state not in (FieldState.ENGINE_FIXED, FieldState.AUTOMATIC):
                continue
            if not field.value:
                continue
            assert field.value.lower() in source_text, (
                f"{kind}.{name} claims {field.value!r}, but that string is not in "
                f"{source_path.name} - registry and solver have drifted apart"
            )
