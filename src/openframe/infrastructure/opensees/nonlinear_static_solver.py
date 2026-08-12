"""Run an incremental nonlinear static (pushover) analysis for an OpenSeesPy source."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.element_load_collector import ElementLoadCollector
from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script

#: Algorithms tried, in order, when the configured one fails to converge on a step -
#: a plain LoadControl/DisplacementControl run otherwise stops dead at the first
#: iteration count the *chosen* algorithm cannot satisfy, even when a different
#: algorithm would have sailed through the same increment.
_FALLBACK_ALGORITHMS = ("Newton", "ModifiedNewton", "KrylovNewton", "NewtonLineSearch")
#: How many times a single reporting step may be halved before it counts as a real
#: non-convergence. Each halving is a much smaller ask of the same equations, so a
#: step that only fails because the increment was too coarse usually succeeds well
#: before this limit.
_MAX_BISECTIONS = 4
#: Reserved timeSeries/pattern tag offset used when a lateral pattern is torn down
#: for the gravity phase and rebuilt afterwards, kept clear of the user's own tags.
_REPLAY_TAG_OFFSET = 900_000_000


@dataclass(slots=True)
class _StepDiagnostics:
    """Solver work needed to commit one user-visible increment."""

    attempts: int = 0
    substeps: int = 0
    iterations: int = 0
    bisections: int = 0


def _record_test_iterations(diagnostics: _StepDiagnostics | None) -> None:
    if diagnostics is None:
        return
    try:
        diagnostics.iterations += max(int(ops.testIter()), 0)
    except (AttributeError, TypeError, ValueError):
        # Some OpenSees builds/equation tests do not expose an iteration count.
        # Attempts and substeps still provide deterministic convergence diagnostics.
        pass


def _local_forces(element_tag: int) -> list[float]:
    """Return end forces along the member's own axes (see linear_static_solver)."""
    response = ops.eleResponse(element_tag, "localForce")
    return [float(value) for value in response]


def _element_length(element_tag: int) -> float:
    nodes = ops.eleNodes(element_tag)
    if len(nodes) < 2:
        return 0.0
    start = ops.nodeCoord(int(nodes[0]))
    end = ops.nodeCoord(int(nodes[1]))
    if len(start) < 2 or len(end) < 2:
        return 0.0
    deltas = [float(b) - float(a) for a, b in zip(start, end, strict=False)]
    return math.sqrt(sum(value * value for value in deltas))


def _support_reaction_nodes(
    node_tags: list[int], fixed_nodes: list[int], control_dof: int
) -> list[int]:
    """Return nodes whose reactions make up the structural base shear.

    Concentrated-plasticity frame models commonly put a zeroLength rotational
    spring between a fixed joint and the first beam-column node.  Translational
    DOFs are tied with ``equalDOF``; OpenSees then reports the member's horizontal
    reaction on the coincident constrained node, not necessarily on the node that
    owns the SP fixity.  Summing only ``getFixedNodes()`` therefore drops the frame
    columns entirely (the official two-story benchmark records nodes 117/217 for
    exactly this reason).  Include coincident nodes at every fixed support while
    retaining the old behavior for ordinary non-spring supports.
    """
    support_coordinates = [tuple(float(value) for value in ops.nodeCoord(tag)) for tag in fixed_nodes]

    def is_at_support(tag: int) -> bool:
        coordinates = tuple(float(value) for value in ops.nodeCoord(tag))
        return any(
            len(coordinates) == len(support)
            and all(
                math.isclose(value, reference, rel_tol=1.0e-12, abs_tol=1.0e-9)
                for value, reference in zip(coordinates, support, strict=True)
            )
            for support in support_coordinates
        )

    return [
        tag
        for tag in node_tags
        if is_at_support(tag) and len(ops.nodeReaction(tag)) >= control_dof
    ]


def _flexural_rigidity(collector: ModelCommandCollector, element_tag: int) -> float:
    properties = collector.elements.get(element_tag, {}).get("properties", {})
    try:
        inertia = properties.get("I", properties.get("Iz"))
        return float(properties["E"]) * float(inertia)
    except (KeyError, TypeError, ValueError):
        return 0.0


def _load_warnings(collector: ElementLoadCollector, element_tags: list[int]) -> list[str]:
    unsupported = sorted(collector.unsupported.intersection(element_tags))
    if not unsupported:
        return []
    listed = ", ".join(str(tag) for tag in unsupported)
    return [
        (
            f"부재 {listed}에 등분포하중이 아닌 구간하중이 적용되어, "
            "해당 부재의 다이어그램은 양단값만으로 표시됩니다."
        )
    ]


def _model_nonlinearity_warnings(collector: ModelCommandCollector) -> list[str]:
    """Warn when a nonlinear solve is requested for an apparently linear model."""
    linear_materials = {"elastic", "elasticisotropic", "elasticorthotropic"}
    has_nonlinear_material = any(
        material.lower() not in linear_materials for material in collector.material_types
    )
    nonlinear_elements = {
        "forcebeamcolumn",
        "dispbeamcolumn",
        "displacementbeamcolumn",
        "corottruss",
        "corottrusssection",
    }
    has_nonlinear_element = any(
        str(item.get("element_type", "")).lower() in nonlinear_elements
        for item in collector.elements.values()
    )
    has_fiber_section = any("fiber" in section.lower() for section in collector.section_types)
    has_geometric_nonlinearity = any(
        transformation.lower() in {"pdelta", "corotational", "corot"}
        for transformation in collector.geom_transf_types
    )
    if any(
        (
            has_nonlinear_material,
            has_nonlinear_element,
            has_fiber_section,
            has_geometric_nonlinearity,
        )
    ):
        return []
    return [
        (
            "비선형 재료, Fiber section 또는 기하비선형 변환을 찾지 못했습니다. "
            "현재 모델은 비선형 해석기를 사용하더라도 탄성 증분해석으로 거동할 수 있습니다."
        )
    ]


def _all_pattern_tags(
    property_collector: ModelCommandCollector, load_collector: ElementLoadCollector
) -> set[int]:
    tags = {
        int(item["pattern_tag"])
        for item in property_collector.loads
        if item.get("pattern_tag") is not None
    }
    tags |= {
        int(pattern_tag)
        for pattern_tag, _element_tag in load_collector.uniform_load_cases
        if pattern_tag is not None
    }
    return tags


def _remove_patterns(pattern_tags: set[int]) -> None:
    for tag in sorted(pattern_tags):
        ops.remove("loadPattern", tag)


def _replay_patterns(
    pattern_tags: set[int],
    ndm: int,
    property_collector: ModelCommandCollector,
    load_collector: ElementLoadCollector,
) -> None:
    """Recreate the given patterns (nodal + element loads) from what was collected
    while the model script ran, so they can be torn down for the gravity-only phase
    and rebuilt afterwards with a clean pseudo-time - OpenSees has no "pause this
    pattern" command, only remove-and-redefine."""
    for pattern_tag in sorted(pattern_tags):
        definition = property_collector.pattern_definitions.get(pattern_tag)
        if definition is not None and definition[0].lower() == "plain":
            # Removing a pattern leaves its TimeSeries in the domain. Reuse the
            # original arguments so Constant/Path series do not become Linear.
            ops.pattern(definition[0], pattern_tag, *definition[1])
        else:
            replay_tag = _REPLAY_TAG_OFFSET + pattern_tag
            ops.timeSeries("Linear", replay_tag)
            ops.pattern("Plain", pattern_tag, replay_tag)
        for item in property_collector.loads:
            if item.get("pattern_tag") == pattern_tag:
                ops.load(int(item["node_tag"]), *[float(v) for v in item["values"]])
        for (case_pattern_tag, element_tag), values in load_collector.uniform_load_cases.items():
            if case_pattern_tag != pattern_tag:
                continue
            wx, wy, wz = values
            if ndm == 3:
                ops.eleLoad("-ele", element_tag, "-type", "-beamUniform", wy, wz, wx)
            else:
                ops.eleLoad("-ele", element_tag, "-type", "-beamUniform", wy, wx)


def _set_integrator(
    integrator_type: str, control_node: int, control_dof: int, increment: float
) -> None:
    if integrator_type == "DisplacementControl":
        ops.integrator("DisplacementControl", control_node, control_dof, increment)
    else:
        ops.integrator("LoadControl", increment)


def _analyze_with_fallback(
    primary_algorithm: str,
    recovered_with: set[str],
    diagnostics: _StepDiagnostics | None = None,
) -> bool:
    if diagnostics is not None:
        diagnostics.attempts += 1
    if ops.analyze(1) == 0:
        if diagnostics is not None:
            diagnostics.substeps += 1
        _record_test_iterations(diagnostics)
        return True
    for candidate in _FALLBACK_ALGORITHMS:
        if candidate == primary_algorithm:
            continue
        ops.algorithm(candidate)
        if diagnostics is not None:
            diagnostics.attempts += 1
        converged = ops.analyze(1) == 0
        ops.algorithm(primary_algorithm)
        if converged:
            recovered_with.add(candidate)
            if diagnostics is not None:
                diagnostics.substeps += 1
            _record_test_iterations(diagnostics)
            return True
    return False


def _advance_one_step(
    nominal_increment: float,
    *,
    integrator_type: str,
    control_node: int,
    control_dof: int,
    algorithm: str,
    recovered_with: set[str],
    max_bisections: int = _MAX_BISECTIONS,
    diagnostics: _StepDiagnostics | None = None,
) -> bool:
    """Cover one reporting step's worth of pseudo-time/displacement, retrying with
    algorithm fallback and (if that alone isn't enough) a halved increment - applied
    repeatedly, so a step that only converges at a quarter or eighth of the nominal
    size still completes instead of ending the whole curve early."""
    fraction_remaining = 1.0
    sub_fraction = 1.0
    depth = 0
    while fraction_remaining > 1.0e-9:
        step_fraction = min(sub_fraction, fraction_remaining)
        _set_integrator(integrator_type, control_node, control_dof, nominal_increment * step_fraction)
        if _analyze_with_fallback(algorithm, recovered_with, diagnostics):
            fraction_remaining -= step_fraction
            continue
        depth += 1
        if depth > max_bisections:
            return False
        if diagnostics is not None:
            diagnostics.bisections += 1
        sub_fraction = step_fraction / 2.0
    return True


def run_nonlinear_static_analysis(
    source: Path,
    *,
    control_node: int,
    control_dof: int = 1,
    num_steps: int = 10,
    tolerance: float = 1.0e-6,
    max_iterations: int = 25,
    algorithm: str = "Newton",
    test_type: str = "NormDispIncr",
    system: str = "BandGeneral",
    constraints_type: str = "Plain",
    numberer: str = "RCM",
    gravity_pattern: int | None = None,
    lateral_pattern: int | None = None,
    gravity_steps: int = 5,
    integrator_type: str = "LoadControl",
    target_displacement: float | None = None,
    max_bisections: int = _MAX_BISECTIONS,
    progress_callback: Callable[[int | None, str], None] | None = None,
) -> dict[str, Any]:
    """Build the model by executing ``source``, then push it in ``num_steps`` equal
    increments, tracking base shear vs. ``control_node``'s ``control_dof``
    displacement at every converged step for a load-displacement (pushover) curve.

    ``integrator_type="LoadControl"`` scales every active pattern by an equal load
    factor each step - it cannot trace a softening/post-peak branch, since that needs
    the *displacement* driving the analysis instead. ``"DisplacementControl"`` pushes
    ``control_node``/``control_dof`` by a fixed increment each step and solves for
    whatever load that takes, tracing the descending branch too.

    ``gravity_pattern``, if given, is applied on its own first (in ``gravity_steps``
    increments), frozen with ``loadConst``, and excluded from the main loop - so
    gravity is fully present throughout the push instead of ramping up alongside it,
    which real pushover procedure requires and a plastic material's path-dependence
    makes more than cosmetic.

    Retries a failed step with the other standard algorithms, then with a halved
    increment, before finally stopping the curve there and reporting why - the curve
    up to that point, and the last converged state, are still meaningful results.
    """
    def _report_progress(value: int | None, stage: str) -> None:
        if progress_callback is not None:
            progress_callback(value, stage)

    _report_progress(0, "Building the nonlinear OpenSees model...")
    # The section properties are only knowable from the element() call itself, and the
    # deflected shape between two nodes cannot be rebuilt without EI. Its own nested
    # ``element_loads`` (not a second, standalone ``ElementLoadCollector``) is what
    # records -beamUniform loads here — it already knows the model's real ndm (it
    # also wraps ``ops.model()``), whereas a standalone collector's ``eleLoad`` wrap
    # has no way to find that out and silently defaults to 2D, misreading a 3D call's
    # (Wy, Wz, Wx) as 2D's (Wy, Wx) - Wz read as Wx, Wx dropped entirely. That would
    # not just mislabel a value in the returned payload: ``_replay_patterns`` below
    # re-issues ``ops.eleLoad`` from exactly this collector's ``uniform_load_cases``
    # to restore the push pattern after the gravity-only phase, so a 3D model run
    # with ``gravity_pattern`` set would have actually pushed with the wrong
    # distributed load, not merely reported one.
    property_collector = ModelCommandCollector()
    property_collector.install()
    try:
        run_model_script(source)
    finally:
        property_collector.restore()
    load_collector = property_collector.element_loads
    _report_progress(5, "Model built; preparing nonlinear solution strategy...")

    node_tags = [int(tag) for tag in ops.getNodeTags()]
    element_tags = [int(tag) for tag in ops.getEleTags()]
    if not node_tags or not element_tags:
        raise RuntimeError(
            "해석할 모델이 비어 있습니다. 스크립트 끝에서 ops.wipe()로 모델을 지우고 "
            "있지 않은지 확인하세요."
        )
    if control_node not in node_tags:
        raise RuntimeError(f"CONTROL NODE {control_node}가 모델에 존재하지 않습니다.")
    if num_steps <= 0:
        raise RuntimeError("LOAD STEPS는 1 이상이어야 합니다.")
    if max_bisections < 0:
        raise RuntimeError("MAX BISECTIONS는 0 이상이어야 합니다.")
    supported_settings = {
        "INTEGRATOR": (integrator_type, {"LoadControl", "DisplacementControl"}),
        "ALGORITHM": (algorithm, set(_FALLBACK_ALGORITHMS)),
        "CONVERGENCE TEST": (
            test_type,
            {"NormDispIncr", "EnergyIncr", "NormUnbalance"},
        ),
        "SYSTEM": (system, {"BandGeneral", "UmfPack", "ProfileSPD"}),
        "CONSTRAINT HANDLER": (constraints_type, {"Plain", "Transformation"}),
        "NUMBERER": (numberer, {"RCM", "Plain", "AMD"}),
    }
    for label, (value, supported) in supported_settings.items():
        if value not in supported:
            raise RuntimeError(f"지원하지 않는 {label} 설정입니다: {value}")
    control_node_dof_count = len(ops.nodeDisp(control_node))
    if not 1 <= control_dof <= control_node_dof_count:
        raise RuntimeError(
            f"CONTROL DOF {control_dof}가 CONTROL NODE {control_node}의 자유도 범위"
            f"(1~{control_node_dof_count})를 벗어났습니다."
        )
    if integrator_type == "DisplacementControl" and not target_displacement:
        raise RuntimeError("DisplacementControl에는 0이 아닌 TARGET DISPLACEMENT 값이 필요합니다.")

    all_pattern_tags = _all_pattern_tags(property_collector, load_collector)
    if gravity_pattern is not None and gravity_pattern not in all_pattern_tags:
        raise RuntimeError(f"GRAVITY PATTERN {gravity_pattern}가 모델에 존재하지 않습니다.")
    if lateral_pattern is not None and lateral_pattern not in all_pattern_tags:
        raise RuntimeError(f"LATERAL PATTERN {lateral_pattern}가 모델에 존재하지 않습니다.")
    if lateral_pattern is not None and lateral_pattern == gravity_pattern:
        raise RuntimeError("GRAVITY PATTERN과 LATERAL PATTERN은 서로 달라야 합니다.")
    if gravity_pattern is not None and gravity_steps <= 0:
        raise RuntimeError("GRAVITY STEPS는 1 이상이어야 합니다.")

    fixed_nodes = [int(tag) for tag in ops.getFixedNodes()]
    # A model can, in principle, mix ndf across nodes (multiple ops.model() calls or
    # per-node overrides), so a fixed node's reaction vector is not guaranteed to be
    # as long as control_node's - skip any that are too short instead of indexing
    # past the end of the array.
    reaction_nodes = _support_reaction_nodes(node_tags, fixed_nodes, control_dof)

    def _base_shear() -> float:
        ops.reactions()
        # Reactions oppose the applied load (Newton's third law); base shear is read
        # as the resistance the structure develops, so the sign is flipped to grow
        # positive with the push instead of growing more negative.
        return -sum(float(ops.nodeReaction(tag)[control_dof - 1]) for tag in reaction_nodes)

    ops.wipeAnalysis()
    ops.constraints(constraints_type)
    ops.numberer(numberer)
    ops.system(system)
    ops.test(test_type, tolerance, max_iterations)
    ops.algorithm(algorithm)

    messages: list[str] = []
    baseline_base_shear = 0.0
    total_attempts = 0
    total_substeps = 0

    push_pattern_tags = (
        {lateral_pattern}
        if lateral_pattern is not None
        else all_pattern_tags - ({gravity_pattern} if gravity_pattern is not None else set())
    )
    if not push_pattern_tags:
        raise RuntimeError("푸시오버에 사용할 횡하중 패턴이 없습니다.")

    if gravity_pattern is not None:
        non_gravity_pattern_tags = all_pattern_tags - {gravity_pattern}
        _remove_patterns(non_gravity_pattern_tags)
        ops.integrator("LoadControl", 1.0 / gravity_steps)
        ops.analysis("Static")
        for step in range(1, gravity_steps + 1):
            gravity_diagnostics = _StepDiagnostics()
            recovered_with: set[str] = set()
            if not _advance_one_step(
                1.0 / gravity_steps,
                integrator_type="LoadControl",
                control_node=control_node,
                control_dof=control_dof,
                algorithm=algorithm,
                recovered_with=recovered_with,
                max_bisections=max_bisections,
                diagnostics=gravity_diagnostics,
            ):
                raise RuntimeError(
                    f"중력 하중(GRAVITY PATTERN {gravity_pattern}) 적용 중 {step}번째 스텝에서 "
                    "수렴하지 않았습니다. GRAVITY STEPS를 늘려보세요."
                )
            total_attempts += gravity_diagnostics.attempts
            total_substeps += gravity_diagnostics.substeps
            if recovered_with or gravity_diagnostics.bisections:
                methods = ", ".join(sorted(recovered_with)) or "step bisection"
                messages.append(
                    f"중력 단계 {step}은 {methods} 복구 전략으로 수렴했습니다."
                )
            _report_progress(
                5 + round(20 * step / gravity_steps),
                f"Gravity step {step}/{gravity_steps} converged",
            )
        ops.loadConst("-time", 0.0)
        baseline_base_shear = _base_shear()
        ndm = property_collector.ndm
        _replay_patterns(push_pattern_tags, ndm, property_collector, load_collector)
    elif lateral_pattern is not None:
        _remove_patterns(all_pattern_tags - push_pattern_tags)

    nominal_increment = (
        (target_displacement or 0.0) / num_steps
        if integrator_type == "DisplacementControl"
        else 1.0 / num_steps
    )
    # An integrator must exist before ops.analysis() is created, or OpenSees falls
    # back to its own default and warns about it - _advance_one_step redefines this
    # every substep anyway, so the initial value only has to be valid, not final.
    _set_integrator(integrator_type, control_node, control_dof, nominal_increment)
    ops.analysis("Static")

    curve: list[dict[str, Any]] = []
    recovered_steps: dict[int, set[str]] = {}
    failed_step: int | None = None
    pushover_progress_start = 25 if gravity_pattern is not None else 5
    pushover_progress_span = 100 - pushover_progress_start
    for step in range(1, num_steps + 1):
        recovered_with: set[str] = set()
        diagnostics = _StepDiagnostics()
        if not _advance_one_step(
            nominal_increment,
            integrator_type=integrator_type,
            control_node=control_node,
            control_dof=control_dof,
            algorithm=algorithm,
            recovered_with=recovered_with,
            max_bisections=max_bisections,
            diagnostics=diagnostics,
        ):
            total_attempts += diagnostics.attempts
            total_substeps += diagnostics.substeps
            failed_step = step
            messages.append(
                f"{step}번째 스텝에서 수렴하지 않았습니다 (총 {num_steps}스텝 중). "
                "그 이전까지 수렴한 결과만 표시됩니다."
            )
            _report_progress(
                pushover_progress_start
                + round(pushover_progress_span * (step - 1) / num_steps),
                f"Pushover stopped at step {step}/{num_steps}: not converged",
            )
            break
        total_attempts += diagnostics.attempts
        total_substeps += diagnostics.substeps
        if recovered_with or diagnostics.bisections:
            recovered_steps[step] = recovered_with
        base_shear = _base_shear() - baseline_base_shear
        displacement = float(ops.nodeDisp(control_node, control_dof))
        curve.append(
            {
                "step": step,
                "control_displacement": displacement,
                "base_shear": base_shear,
                "attempts": diagnostics.attempts,
                "substeps": diagnostics.substeps,
                "iterations": diagnostics.iterations,
                "recovered_with": sorted(recovered_with),
            }
        )
        _report_progress(
            pushover_progress_start + round(pushover_progress_span * step / num_steps),
            f"Pushover step {step}/{num_steps} converged",
        )

    if not curve:
        raise RuntimeError("첫 스텝부터 수렴하지 않았습니다. 해석 설정을 조정해 보세요.")

    if recovered_steps:
        step_list = ", ".join(str(step) for step in sorted(recovered_steps))
        messages.append(
            f"{step_list}번째 스텝은 기본 알고리즘으로 수렴하지 않아 대체 알고리즘 또는 "
            "축소된 증분으로 재시도해 수렴했습니다."
        )
    messages.extend(_model_nonlinearity_warnings(property_collector))
    messages.extend(_load_warnings(load_collector, element_tags))

    return {
        "status": "completed" if failed_step is None else "partial",
        "node_results": [
            {
                "node_tag": tag,
                "displacement": [float(value) for value in ops.nodeDisp(tag)],
                "reaction": [float(value) for value in ops.nodeReaction(tag)],
            }
            for tag in node_tags
        ],
        "element_results": [
            {
                "element_tag": tag,
                "local_forces": _local_forces(tag),
                "length": _element_length(tag),
                "uniform_load": list(load_collector.uniform_loads.get(tag, (0.0, 0.0))),
                "flexural_rigidity": _flexural_rigidity(property_collector, tag),
            }
            for tag in element_tags
        ],
        "load_displacement_curve": curve,
        "convergence": {
            "requested_steps": num_steps,
            "completed_steps": len(curve),
            "failed_step": failed_step,
            "total_attempts": total_attempts,
            "total_substeps": total_substeps,
            "recovered_steps": sorted(recovered_steps),
        },
        "messages": messages,
    }
