"""Run an incremental nonlinear static (pushover) analysis for an OpenSeesPy source."""

import math
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


def _analyze_with_fallback(primary_algorithm: str, recovered_with: set[str]) -> bool:
    if ops.analyze(1) == 0:
        return True
    for candidate in _FALLBACK_ALGORITHMS:
        if candidate == primary_algorithm:
            continue
        ops.algorithm(candidate)
        converged = ops.analyze(1) == 0
        ops.algorithm(primary_algorithm)
        if converged:
            recovered_with.add(candidate)
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
        if _analyze_with_fallback(algorithm, recovered_with):
            fraction_remaining -= step_fraction
            continue
        depth += 1
        if depth > _MAX_BISECTIONS:
            return False
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
    gravity_pattern: int | None = None,
    gravity_steps: int = 5,
    integrator_type: str = "LoadControl",
    target_displacement: float | None = None,
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
    load_collector = ElementLoadCollector()
    # The section properties are only knowable from the element() call itself, and the
    # deflected shape between two nodes cannot be rebuilt without EI.
    property_collector = ModelCommandCollector()
    load_collector.install()
    property_collector.install()
    try:
        run_model_script(source)
    finally:
        load_collector.restore()
        property_collector.restore()

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
    if gravity_pattern is not None and gravity_steps <= 0:
        raise RuntimeError("GRAVITY STEPS는 1 이상이어야 합니다.")

    fixed_nodes = [int(tag) for tag in ops.getFixedNodes()]
    # A model can, in principle, mix ndf across nodes (multiple ops.model() calls or
    # per-node overrides), so a fixed node's reaction vector is not guaranteed to be
    # as long as control_node's - skip any that are too short instead of indexing
    # past the end of the array.
    reaction_nodes = [
        tag for tag in fixed_nodes if len(ops.nodeReaction(tag)) >= control_dof
    ]

    def _base_shear() -> float:
        ops.reactions()
        # Reactions oppose the applied load (Newton's third law); base shear is read
        # as the resistance the structure develops, so the sign is flipped to grow
        # positive with the push instead of growing more negative.
        return -sum(float(ops.nodeReaction(tag)[control_dof - 1]) for tag in reaction_nodes)

    ops.wipeAnalysis()
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system(system)
    ops.test(test_type, tolerance, max_iterations)
    ops.algorithm(algorithm)

    messages: list[str] = []
    baseline_base_shear = 0.0

    if gravity_pattern is not None:
        lateral_pattern_tags = all_pattern_tags - {gravity_pattern}
        _remove_patterns(lateral_pattern_tags)
        ops.integrator("LoadControl", 1.0 / gravity_steps)
        ops.analysis("Static")
        for step in range(1, gravity_steps + 1):
            if ops.analyze(1) != 0:
                raise RuntimeError(
                    f"중력 하중(GRAVITY PATTERN {gravity_pattern}) 적용 중 {step}번째 스텝에서 "
                    "수렴하지 않았습니다. GRAVITY STEPS를 늘려보세요."
                )
        ops.loadConst("-time", 0.0)
        baseline_base_shear = _base_shear()
        ndm = property_collector.ndm
        _replay_patterns(lateral_pattern_tags, ndm, property_collector, load_collector)

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

    curve: list[dict[str, float | int]] = []
    recovered_steps: dict[int, set[str]] = {}
    for step in range(1, num_steps + 1):
        recovered_with: set[str] = set()
        if not _advance_one_step(
            nominal_increment,
            integrator_type=integrator_type,
            control_node=control_node,
            control_dof=control_dof,
            algorithm=algorithm,
            recovered_with=recovered_with,
        ):
            messages.append(
                f"{step}번째 스텝에서 수렴하지 않았습니다 (총 {num_steps}스텝 중). "
                "그 이전까지 수렴한 결과만 표시됩니다."
            )
            break
        if recovered_with:
            recovered_steps[step] = recovered_with
        base_shear = _base_shear() - baseline_base_shear
        displacement = float(ops.nodeDisp(control_node, control_dof))
        curve.append(
            {"step": step, "control_displacement": displacement, "base_shear": base_shear}
        )

    if not curve:
        raise RuntimeError("첫 스텝부터 수렴하지 않았습니다. 해석 설정을 조정해 보세요.")

    if recovered_steps:
        step_list = ", ".join(str(step) for step in sorted(recovered_steps))
        messages.append(
            f"{step_list}번째 스텝은 기본 알고리즘으로 수렴하지 않아 대체 알고리즘 또는 "
            "축소된 증분으로 재시도해 수렴했습니다."
        )
    messages.extend(_load_warnings(load_collector, element_tags))

    return {
        "status": "completed",
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
        "messages": messages,
    }
