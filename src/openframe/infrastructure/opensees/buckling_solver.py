"""Run an elastic global eigenvalue buckling analysis for an OpenSeesPy source.

Deliberately does *not* call ``ops.eigen()`` - that solves a mass-matrix
eigenproblem (natural vibration modes), a completely different physical
question from linearized elastic buckling. Instead this builds two tangent
stiffness matrices by hand (unloaded, and at a reference load state) and solves
the generalized eigenproblem ``K_material . phi = lambda . K_geometric . phi``
with SciPy directly - see ``run_buckling_analysis`` below for the full
procedure and its honest scope (elastic, global, linearized only).
"""

from pathlib import Path
from typing import Any

import numpy as np
import openseespy.opensees as ops
import scipy.linalg

from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script

#: Geometric transformations Setup may override every ops.geomTransf(...) call
#: with, and the only ones this function currently accepts. Officially
#: restricted to P-Delta only, for now - the Euler-column closed-form
#: validation this module's accuracy rests on was only ever run against
#: PDelta; Corotational's large-displacement kinematics interacting with the
#: K_material/K_loaded linearization has not been separately verified, so it
#: is not offered as a real choice yet (see _REJECTED_GEOMETRIC_TRANSFORM_TYPES
#: below for its explicit rejection message). "Linear" is excluded for a
#: different, permanent reason - it produces no geometric stiffness at all
#: (Kg is linear in axial force for PDelta/Corotational, identically zero for
#: Linear), so a buckling run against it could only ever fail the
#: K_geometric~=0 check below; rejected immediately instead, before the model
#: is even built, for a much clearer reason than that generic failure.
_OVERRIDE_GEOMETRIC_TRANSFORM_TYPES = frozenset({"PDelta"})
#: Sentinel meaning "install no override - keep each element's own geomTransf
#: exactly as the model defines it" ("From Model" in Setup, not currently
#: offered - see _GEOMETRIC_TRANSFORM_TYPES). Mirrors nonlinear_static_solver.py's
#: own ``_USE_MODEL_DEFINITION`` exactly (see
#: ModelCommandCollector.install(geom_transf_override=...), the shared
#: mechanism this reuses rather than duplicating) - kept defined so re-enabling
#: it later (once validated) does not require touching the shared mechanism.
_USE_MODEL_DEFINITION = "UseModelDefinition"
_GEOMETRIC_TRANSFORM_TYPES = _OVERRIDE_GEOMETRIC_TRANSFORM_TYPES
#: Real, recognized transform types this function still refuses - each for
#: reasons worth telling the caller precisely rather than a generic "not
#: supported" (see the rejection branch in run_buckling_analysis below).
_NOT_YET_SUPPORTED_TRANSFORM_TYPES = frozenset({"Corotational", _USE_MODEL_DEFINITION})

#: Pattern TimeSeries types treated as a genuine, single-valued static reference
#: load. Anything else (Path, Trig, ...) cannot be reduced to one reference load
#: state without guessing which instant "the load" means, so it is rejected
#: outright instead of silently picking a value.
_STATIC_TIME_SERIES_TYPES = frozenset({"linear", "constant"})

#: System DOF count above which a warning about Dense FullGeneral matrix
#: extraction + SciPy's O(n**3) dense generalized eigensolve is added to the
#: result - both scale cubically in time and quadratically in memory with
#: system size, unlike the sparse/banded solvers this project's other
#: analyses use. Not a hard limit - a run above this still completes, just
#: slower - so this only ever adds a message, never blocks anything.
_LARGE_SYSTEM_DOF_WARNING_THRESHOLD = 500

#: K_geometric is treated as (numerically) the zero matrix once its largest-
#: magnitude entry is this many times smaller than K_material's largest entry -
#: below that, any "eigenvalues" solved from it are floating-point noise, not
#: real buckling factors. This is exactly what a Linear-only geomTransf, or a
#: reference load with no axial/geometric effect at all, produces.
_GEOMETRIC_STIFFNESS_RELATIVE_FLOOR = 1.0e-10

#: Default (AUTO) tolerance for accepting a solved eigenvalue as real, relative
#: to the eigenvalue's own magnitude (so it scales with the problem instead of
#: assuming a particular unit system): |imag(lambda)| <= tolerance * max(|real(lambda)|, 1).
_AUTO_EIGENVALUE_TOLERANCE = 1.0e-6


def _all_pattern_tags(property_collector: ModelCommandCollector) -> set[int]:
    tags = {
        int(item["pattern_tag"])
        for item in property_collector.loads
        if item.get("pattern_tag") is not None
    }
    tags |= {
        int(pattern_tag)
        for pattern_tag, _element_tag in property_collector.element_loads.uniform_load_cases
        if pattern_tag is not None
    }
    tags |= {
        int(item["pattern_tag"])
        for item in property_collector.element_loads.point_load_cases
        if item.get("pattern_tag") is not None
    }
    return tags


def _reference_load_pattern_tags(
    property_collector: ModelCommandCollector,
    reference_load_pattern: int | None,
) -> set[int]:
    """The "Load Case" pattern tag(s) that make up the reference load -
    ``reference_load_pattern=None`` means "the model's current static load"
    (every existing pattern, combined), a specific tag means exactly that one
    pattern - mirroring how ``lateral_pattern``/``gravity_pattern`` already
    work in nonlinear_static_solver.py's own inline editor.
    """
    all_tags = _all_pattern_tags(property_collector)
    if reference_load_pattern is None:
        return all_tags
    if reference_load_pattern not in all_tags:
        raise RuntimeError(
            f"LOAD CASE {reference_load_pattern}가 모델에 존재하지 않습니다."
        )
    return {reference_load_pattern}


def _reject_non_static_patterns(
    property_collector: ModelCommandCollector, pattern_tags: set[int]
) -> None:
    """Block a reference load whose pattern is not a plain, single-valued
    static load - a Path/Trig (or other genuinely time-varying) TimeSeries has
    no one "current value" this analysis can safely take as the reference
    state, and a non-"Plain" pattern (e.g. UniformExcitation) is not a static
    load pattern at all. Never estimated or guessed at - rejected outright."""
    for tag in sorted(pattern_tags):
        definition = property_collector.pattern_definitions.get(tag)
        if definition is None or definition[0].lower() != "plain":
            raise RuntimeError(
                f"LOAD CASE {tag}는 정적 하중 패턴(Plain)이 아니어서 기준하중으로 사용할 수 "
                "없습니다."
            )
        arguments = definition[1]
        if not arguments:
            raise RuntimeError(f"LOAD CASE {tag}의 TimeSeries를 확인할 수 없습니다.")
        time_series_tag = int(arguments[0])
        series_type = property_collector.time_series_definitions.get(time_series_tag)
        if series_type is None or series_type.lower() not in _STATIC_TIME_SERIES_TYPES:
            raise RuntimeError(
                f"LOAD CASE {tag}는 Path/동적 TimeSeries를 사용하고 있어 기준하중을 안전하게 "
                "분리할 수 없습니다. 정적(Linear/Constant) TimeSeries를 사용하는 하중 패턴만 "
                "지원합니다."
            )


def _reference_load_magnitude(
    property_collector: ModelCommandCollector, pattern_tags: set[int]
) -> float:
    """Sum of absolute nodal + uniform element + concentrated element load
    values across the selected pattern(s) - a coarse but honest "is there
    anything here at all" measure, not a physical resultant (mixed
    force/moment components are not physically summable, and that is not
    what this checks for)."""
    total = 0.0
    for item in property_collector.loads:
        if item.get("pattern_tag") in pattern_tags:
            total += sum(abs(float(value)) for value in item["values"])
    for (pattern_tag, _element_tag), values in property_collector.element_loads.uniform_load_cases.items():
        if pattern_tag in pattern_tags:
            total += sum(abs(float(value)) for value in values)
    for item in property_collector.element_loads.point_load_cases:
        if item.get("pattern_tag") in pattern_tags:
            total += abs(item["py"]) + abs(item["pz"]) + abs(item["n"])
    return total


def _apply_reference_load(
    property_collector: ModelCommandCollector,
    pattern_tags: set[int],
    scale: float,
    ndm: int,
) -> None:
    """Re-issue every nodal/uniform-element/concentrated-element load in
    ``pattern_tags`` under one fresh Constant-TimeSeries Plain pattern, scaled
    by ``scale`` - this is the "단위 reference load pattern" the generalized
    eigenproblem is solved
    against. A Constant series (not Linear) is used deliberately: this single
    ``ops.analyze(1)`` step must apply the *full* reference-load-scale
    magnitude in one shot, and a Constant series does exactly that regardless
    of the analysis's own pseudo-time increment."""
    reference_tag = max(pattern_tags, default=0) + 1_000_000
    ops.timeSeries("Constant", reference_tag)
    ops.pattern("Plain", reference_tag, reference_tag)
    for item in property_collector.loads:
        if item.get("pattern_tag") not in pattern_tags:
            continue
        values = [float(value) * scale for value in item["values"]]
        ops.load(int(item["node_tag"]), *values)
    for (pattern_tag, element_tag), values in property_collector.element_loads.uniform_load_cases.items():
        if pattern_tag not in pattern_tags:
            continue
        wx, wy, wz = (value * scale for value in values)
        if ndm == 3:
            ops.eleLoad("-ele", element_tag, "-type", "-beamUniform", wy, wz, wx)
        else:
            ops.eleLoad("-ele", element_tag, "-type", "-beamUniform", wy, wx)
    for item in property_collector.element_loads.point_load_cases:
        if item.get("pattern_tag") not in pattern_tags:
            continue
        py, pz, position, n = (
            item["py"] * scale,
            item["pz"] * scale,
            item["position"],
            item["n"] * scale,
        )
        if ndm == 3:
            ops.eleLoad("-ele", item["element_tag"], "-type", "-beamPoint", py, pz, position, n)
        else:
            ops.eleLoad("-ele", item["element_tag"], "-type", "-beamPoint", py, position, n)


def _count_near_zero_stiffness_modes(system_size: int) -> int:
    """How many structural modes K fails to resist at the current state.

    Called only after ``ops.analyze`` itself has already failed - ``printA`` still
    returns the assembled tangent even though the linear solve hit a zero pivot.
    """
    matrix = _extract_stiffness_matrix(system_size)
    symmetric = (matrix + matrix.T) / 2.0
    eigenvalues = np.linalg.eigvalsh(symmetric)
    scale = float(np.max(np.abs(eigenvalues))) if eigenvalues.size else 0.0
    floor = max(1.0e-6 * scale, 1.0e-6)
    return int(np.sum(np.abs(eigenvalues) <= floor))


def _raise_zero_load_stiffness_failure(system_size: int) -> None:
    if system_size > 0 and _count_near_zero_stiffness_modes(system_size) > 0:
        raise RuntimeError(
            "모멘트 해제로 인해 구조가 기구 상태가 되어 좌굴해석을 수행할 수 없습니다."
        )
    raise RuntimeError("무하중 상태의 재료강성 해석이 수렴하지 않았습니다.")


def _extract_stiffness_matrix(size: int) -> np.ndarray:
    flat = ops.printA("-ret")
    matrix = np.asarray(flat, dtype=float).reshape(size, size)
    if not np.all(np.isfinite(matrix)):
        raise RuntimeError("강성행렬에 NaN/Inf 값이 있습니다. 모델 상태를 확인하세요.")
    return matrix


def _translational_count(ndm: int, ndf: int) -> int:
    return min(3 if ndm == 3 else 2, ndf)


def _mode_shape_from_eigenvector(
    eigenvector: np.ndarray,
    node_tags: list[int],
    node_dof_equations: dict[int, list[int]],
    system_size: int,
) -> dict[int, list[float]]:
    """Map a system-equation-ordered eigenvector back to per-node DOF
    components using ``ops.nodeDOFs`` - a restrained DOF's equation number is
    negative (OpenSeesPy returns -1), and is reported as displacement 0.0
    rather than indexed into the vector."""
    shape: dict[int, list[float]] = {}
    for tag in node_tags:
        equations = node_dof_equations[tag]
        shape[tag] = [
            float(eigenvector[equation]) if 0 <= equation < system_size else 0.0
            for equation in equations
        ]
    return shape


#: Which perpendicular-axis rigidDiaphragm (see ops.rigidDiaphragm(perpDirn, ...))
#: a constrained node's tied-DOF set implies - OpenSees always ties exactly the
#: two in-plane translations plus the one rotation about perpDirn, so the DOF
#: set alone identifies it unambiguously (1-indexed DOF numbers: 1=Ux, 2=Uy,
#: 3=Uz, 4=Rx, 5=Ry, 6=Rz). There is no ops getter for perpDirn itself.
_RIGID_DIAPHRAGM_DOF_PATTERNS: dict[frozenset[int], int] = {
    frozenset({2, 3, 4}): 1,
    frozenset({1, 3, 5}): 2,
    frozenset({1, 2, 6}): 3,
}


def _apply_rigid_diaphragm_offset(
    constrained_tag: int,
    master_tag: int,
    perp_dirn: int,
    shape: dict[int, list[float]],
    node_coordinates: dict[int, tuple[float, float, float]],
) -> None:
    """Standard rigid-body rotation relation ``u_c = u_r + omega x (r_c - r_r)``
    - verified against a real OpenSeesPy static solve (imposed SP displacement
    at the retained node) for all three perpDirn values before being trusted
    here; see the buckling-feature memory for the exact check."""
    master = shape[master_tag]
    constrained = shape[constrained_tag]
    dx, dy, dz = (
        node_coordinates[constrained_tag][axis] - node_coordinates[master_tag][axis]
        for axis in range(3)
    )
    if perp_dirn == 3:
        rotation = master[5]
        constrained[0] = master[0] - dy * rotation
        constrained[1] = master[1] + dx * rotation
        constrained[5] = rotation
    elif perp_dirn == 1:
        rotation = master[3]
        constrained[1] = master[1] - dz * rotation
        constrained[2] = master[2] + dy * rotation
        constrained[3] = rotation
    else:  # perp_dirn == 2
        rotation = master[4]
        constrained[0] = master[0] + dz * rotation
        constrained[2] = master[2] - dx * rotation
        constrained[4] = rotation


def _correct_constrained_dof_values(
    node_tags: list[int],
    shape: dict[int, list[float]],
    ndm: int,
) -> bool:
    """Overwrite equalDOF/rigidDiaphragm-constrained node DOF values in
    ``shape`` in place - ``ops.nodeDOFs()`` reports a real (non-negative)
    equation number for a constrained DOF under the Transformation constraint
    handler this solver uses, but indexing an *externally* solved eigenvector
    at that equation does not give this node's own physical value the way
    ``ops.nodeDisp()`` does after a real ``ops.analyze()`` (verified - it
    silently came back exactly 0.0 for every constrained DOF before this
    fix). ``ops.getConstrainedDOFs``/``ops.getRetainedNodes`` (real OpenSeesPy
    introspection, not guessed at) identify what needs correcting:

    - A rigidDiaphragm's constrained node ties exactly two in-plane
      translations plus the one rotation about perpDirn - corrected via the
      exact rigid-body relation (see ``_apply_rigid_diaphragm_offset``).
    - Anything else (equalDOF, or a rigidDiaphragm rotation DOF standing
      alone) is a direct dof-to-dof tie with coefficient 1.0 - the
      constrained DOF simply copies its retained node's same-index value,
      exact for equalDOF by definition (``ops.equalDOF`` applies the same
      dof list to both nodes).

    Returns whether any constrained node was found at all (used to decide
    whether to mention this in the result's messages).
    """
    found_any = False
    for tag in node_tags:
        constrained_dofs = [int(dof) for dof in ops.getConstrainedDOFs(tag)]
        if not constrained_dofs:
            continue
        retained_nodes = ops.getRetainedNodes(tag)
        if not retained_nodes:
            continue
        found_any = True
        master_tag = int(retained_nodes[0])
        if master_tag not in shape or tag not in shape:
            continue
        perp_dirn = (
            _RIGID_DIAPHRAGM_DOF_PATTERNS.get(frozenset(constrained_dofs)) if ndm == 3 else None
        )
        if perp_dirn is not None:
            coordinates = {
                node_tag: tuple(
                    (*[float(v) for v in ops.nodeCoord(node_tag)], 0.0, 0.0)[:3]
                )
                for node_tag in (tag, master_tag)
            }
            _apply_rigid_diaphragm_offset(tag, master_tag, perp_dirn, shape, coordinates)
            continue
        master_shape = shape[master_tag]
        constrained_shape = shape[tag]
        for dof in constrained_dofs:
            index = dof - 1
            if 0 <= index < len(constrained_shape) and index < len(master_shape):
                constrained_shape[index] = master_shape[index]
    return found_any


def _normalize_mode_shape(
    raw_shape: dict[int, list[float]], ndm: int
) -> dict[int, list[float]]:
    """Scale so the largest-magnitude *translational* component is 1.0 - or,
    if every translational component is ~0 (e.g. a mechanism that only shows
    up as rotation), the largest-magnitude component of any kind. The
    eigenvector's sign is arbitrary either way; this never attempts to pick a
    "positive" direction."""
    max_translational = 0.0
    for components in raw_shape.values():
        count = _translational_count(ndm, len(components))
        for value in components[:count]:
            max_translational = max(max_translational, abs(value))
    if max_translational > 1.0e-12:
        scale = 1.0 / max_translational
    else:
        max_any = max(
            (abs(value) for components in raw_shape.values() for value in components),
            default=0.0,
        )
        scale = 1.0 / max_any if max_any > 1.0e-12 else 1.0
    return {tag: [value * scale for value in components] for tag, components in raw_shape.items()}


def run_buckling_analysis(
    source: Path,
    *,
    reference_load_pattern: int | None = None,
    reference_load_scale: float = 1.0,
    num_modes: int = 5,
    geometric_transform_type: str = "PDelta",
    eigenvalue_tolerance: float | None = None,
) -> dict[str, Any]:
    """Build the model by executing ``source``, then solve for its global
    elastic buckling load factors and mode shapes.

    Procedure (see the module docstring for why this does not use ``ops.eigen()``):

    1. Every load pattern the script defines is removed, and one static-analysis
       object (FullGeneral/RCM/Transformation/Linear/LoadControl) is created once
       and reused for both steps below, so DOF numbering is identical between them.
    2. A single ``ops.analyze(1)`` at zero load extracts ``K_material`` via
       ``ops.printA("-ret")`` - the model's tangent stiffness with no reference
       load applied at all (not "approximately unloaded"; the patterns are gone).
    3. The selected reference load pattern(s) (``reference_load_pattern=None``
       means every pattern in the model, combined; a specific tag means exactly
       that one) are re-applied as one fresh Constant-TimeSeries pattern, scaled
       by ``reference_load_scale``, and a second ``ops.analyze(1)`` (one full
       LoadControl step - this is a linear-elastic solve, no material
       nonlinearity is in scope) extracts ``K_loaded`` the same way.
       ``K_geometric = K_material - K_loaded``.
    4. ``scipy.linalg.eig(K_material, K_geometric)`` solves the generalized
       eigenproblem directly - never via an explicit matrix inverse. Eigenvalues
       are filtered to finite, effectively-real (within ``eigenvalue_tolerance``,
       relative to magnitude; ``None`` = AUTO = 1e-6), and strictly positive, then
       sorted ascending; the smallest is the Critical Buckling Factor.
    5. Each accepted eigenvalue's eigenvector is mapped from system-equation
       ordering back to nodes via ``ops.nodeDOFs``, and normalized (largest
       translational component = 1.0) for display, alongside the raw eigenvector.

    ``geometric_transform_type`` overrides every ``ops.geomTransf(...)`` call the
    same way ``run_nonlinear_static_analysis``'s does (same shared
    ``ModelCommandCollector`` mechanism) - only "PDelta" is currently accepted
    (see the module-level comment on ``_GEOMETRIC_TRANSFORM_TYPES`` for why
    Corotational/"From Model" are not offered yet). "Linear" is rejected for a
    different, permanent reason: it produces zero geometric stiffness by
    construction, so it would only ever fail step 3's K_geometric~=0 check,
    with a far less clear reason.

    The result is an *elastic global* buckling factor against the *given
    reference load pattern* only - material yielding, initial imperfections,
    post-buckling behavior and local/section buckling are all out of scope (see
    the module docstring); the returned ``messages`` always say so explicitly.
    """
    if num_modes <= 0:
        raise RuntimeError("NUMBER OF MODES는 1 이상이어야 합니다.")
    if reference_load_scale == 0:
        raise RuntimeError("REFERENCE LOAD SCALE은 0이 될 수 없습니다.")
    if eigenvalue_tolerance is not None and eigenvalue_tolerance <= 0:
        raise RuntimeError("EIGENVALUE TOLERANCE는 0보다 커야 합니다.")
    if geometric_transform_type not in _GEOMETRIC_TRANSFORM_TYPES:
        if geometric_transform_type == "Linear":
            raise RuntimeError(
                "GEOMETRIC TRANSFORMATION에 Linear는 사용할 수 없습니다 - Linear 변환은 "
                "기하강성을 만들지 않아 좌굴해석이 성립하지 않습니다. P-Delta를 선택하세요."
            )
        if geometric_transform_type in _NOT_YET_SUPPORTED_TRANSFORM_TYPES:
            raise RuntimeError(
                f"GEOMETRIC TRANSFORMATION은 현재 P-Delta만 정식 지원합니다. "
                f"'{geometric_transform_type}'은(는) 추가 검증 후 지원 예정입니다."
            )
        raise RuntimeError(f"지원하지 않는 GEOMETRIC TRANSFORMATION 설정입니다: {geometric_transform_type}")

    effective_geom_transf_override = (
        None if geometric_transform_type == _USE_MODEL_DEFINITION else geometric_transform_type
    )
    property_collector = ModelCommandCollector()
    property_collector.install(geom_transf_override=effective_geom_transf_override)
    try:
        run_model_script(source)
    finally:
        property_collector.restore()

    node_tags = [int(tag) for tag in ops.getNodeTags()]
    element_tags = [int(tag) for tag in ops.getEleTags()]
    if not node_tags or not element_tags:
        raise RuntimeError(
            "해석할 모델이 비어 있습니다. 스크립트 끝에서 ops.wipe()로 모델을 지우고 "
            "있지 않은지 확인하세요."
        )
    if not property_collector.boundaries and not ops.getFixedNodes():
        raise RuntimeError(
            "경계조건이 없습니다. 지점이 없는 모델은 강체운동만 가능해 좌굴해석이 성립하지 "
            "않습니다."
        )
    messages: list[str] = []

    all_pattern_tags = _all_pattern_tags(property_collector)
    if not all_pattern_tags:
        raise RuntimeError("REFERENCE LOAD로 사용할 정적 하중 패턴이 모델에 없습니다.")
    reference_pattern_tags = _reference_load_pattern_tags(
        property_collector, reference_load_pattern
    )
    _reject_non_static_patterns(property_collector, reference_pattern_tags)
    if _reference_load_magnitude(property_collector, reference_pattern_tags) <= 0.0:
        raise RuntimeError("REFERENCE LOAD의 크기가 0입니다.")

    for tag in sorted(all_pattern_tags):
        ops.remove("loadPattern", tag)

    ops.wipeAnalysis()
    ops.system("FullGeneral")
    ops.numberer("RCM")
    ops.constraints("Transformation")
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 0.0)
    ops.analysis("Static")
    if ops.analyze(1) != 0:
        _raise_zero_load_stiffness_failure(ops.systemSize())
    system_size = ops.systemSize()
    if system_size <= 0:
        raise RuntimeError("시스템 자유도 수가 0입니다.")
    if system_size > _LARGE_SYSTEM_DOF_WARNING_THRESHOLD:
        messages.append(
            f"시스템 자유도 수가 {system_size}개로, 밀집(Dense) FullGeneral 행렬 계산과 "
            f"SciPy 일반화고유치 해석은 O(n³)로 느려집니다 (임계값 "
            f"{_LARGE_SYSTEM_DOF_WARNING_THRESHOLD}개). 대형 모델에서는 계산 시간과 메모리 "
            "사용량이 크게 늘어날 수 있습니다."
        )
    k_material = _extract_stiffness_matrix(system_size)

    _apply_reference_load(
        property_collector, reference_pattern_tags, reference_load_scale, property_collector.ndm
    )
    ops.integrator("LoadControl", 1.0)
    if ops.analyze(1) != 0:
        raise RuntimeError(
            "REFERENCE LOAD 적용 상태의 강성 해석이 수렴하지 않았습니다. REFERENCE LOAD SCALE을 "
            "낮춰 보세요."
        )
    if ops.systemSize() != system_size:
        raise RuntimeError(
            "기준하중 적용 전후 시스템 자유도 수가 달라졌습니다 - 해석을 신뢰할 수 없어 "
            "중단합니다."
        )
    k_loaded = _extract_stiffness_matrix(system_size)

    k_geometric = k_material - k_loaded
    material_scale = float(np.max(np.abs(k_material))) if k_material.size else 0.0
    geometric_scale = float(np.max(np.abs(k_geometric))) if k_geometric.size else 0.0
    if material_scale <= 0.0 or geometric_scale <= material_scale * _GEOMETRIC_STIFFNESS_RELATIVE_FLOOR:
        raise RuntimeError(
            "기준하중 상태에서 기하강성(K_geometric)이 사실상 0입니다. GEOMETRIC "
            "TRANSFORMATION이 P-Delta인지, REFERENCE LOAD가 부재에 축력을 "
            "일으키는지 확인하세요."
        )

    eigenvalues, eigenvectors = scipy.linalg.eig(k_material, k_geometric)
    tolerance = eigenvalue_tolerance if eigenvalue_tolerance is not None else _AUTO_EIGENVALUE_TOLERANCE
    accepted: list[tuple[float, int]] = []
    filtered_infinite = 0
    filtered_complex = 0
    filtered_nonpositive = 0
    for index, value in enumerate(eigenvalues):
        if not np.isfinite(value):
            filtered_infinite += 1
            continue
        if abs(value.imag) > tolerance * max(abs(value.real), 1.0):
            filtered_complex += 1
            continue
        if value.real <= 0.0:
            filtered_nonpositive += 1
            continue
        accepted.append((float(value.real), index))
    accepted.sort(key=lambda item: item[0])

    if not accepted:
        raise RuntimeError(
            "유효한 양의 실수 좌굴하중계수를 찾지 못했습니다 "
            f"(제외됨: 무한/미해결 {filtered_infinite}개, 복소 {filtered_complex}개, "
            f"0 이하 {filtered_nonpositive}개)."
        )

    node_dof_equations = {tag: [int(value) for value in ops.nodeDOFs(tag)] for tag in node_tags}
    reference_load_case = (
        "All Patterns"
        if reference_load_pattern is None
        else f"Pattern {reference_load_pattern}"
    )
    selected = accepted[:num_modes]
    buckling_modes: list[dict[str, Any]] = []
    has_constrained_nodes = False
    for mode_number, (factor, index) in enumerate(selected, start=1):
        eigenvector = eigenvectors[:, index].real
        raw_shape = _mode_shape_from_eigenvector(
            eigenvector, node_tags, node_dof_equations, system_size
        )
        if _correct_constrained_dof_values(node_tags, raw_shape, property_collector.ndm):
            has_constrained_nodes = True
        normalized_shape = _normalize_mode_shape(raw_shape, property_collector.ndm)
        buckling_modes.append(
            {
                "mode_number": mode_number,
                "buckling_load_factor": factor,
                "raw_eigenvalue": factor,
                "node_results": [
                    {"node_tag": tag, "displacement": components}
                    for tag, components in raw_shape.items()
                ],
                "normalized_node_results": [
                    {"node_tag": tag, "displacement": components}
                    for tag, components in normalized_shape.items()
                ],
                "reference_load_case": reference_load_case,
                "reference_load_scale": reference_load_scale,
            }
        )

    messages.insert(
        0,
        "Elastic global buckling based on the selected reference load pattern. "
        "Material yielding, imperfections and local section buckling are not included.",
    )
    if filtered_infinite or filtered_complex or filtered_nonpositive:
        messages.append(
            f"고유값 {len(eigenvalues)}개 중 유효하지 않은 값 "
            f"{filtered_infinite + filtered_complex + filtered_nonpositive}개를 제외했습니다 "
            f"(무한/미해결 {filtered_infinite}개, 복소 {filtered_complex}개, 0 이하 "
            f"{filtered_nonpositive}개)."
        )
    if has_constrained_nodes:
        messages.append(
            "모델에 equalDOF/rigidDiaphragm 등 다점구속(constrained node)이 있어 좌굴모드 "
            "형상을 구속관계로부터 복원했습니다. equalDOF와 rigidDiaphragm(모든 perpDirn)은 "
            "정확히 복원되며, 그 외 다점구속 유형은 종속절점-주절점 동일 인덱스 복사로 "
            "근사됩니다."
        )
    status = "completed"
    if len(accepted) < num_modes:
        status = "partial"
        messages.append(
            f"요청한 {num_modes}개 모드 중 {len(accepted)}개의 유효한 좌굴모드만 찾았습니다."
        )

    return {
        "status": status,
        "buckling_modes": buckling_modes,
        "reference_load_case": reference_load_case,
        "reference_load_scale": reference_load_scale,
        "geometric_transform_type": geometric_transform_type,
        "messages": messages,
    }
