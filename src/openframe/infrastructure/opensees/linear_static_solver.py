"""Run a linear static analysis for an OpenSeesPy source and collect results."""

import math
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.element_load_collector import ElementLoadCollector
from openframe.infrastructure.opensees.instability_diagnostic import (
    InstabilityDiagnosticService,
    instability_diagnostic_to_json,
)
from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script


def _local_forces(element_tag: int) -> list[float]:
    """Return end forces along the member's own axes.

    ``eleForce`` reports forces in global coordinates, which swaps N and V on any
    member that is not horizontal, so the local-axis response is used instead.
    Elements that do not implement it report no end forces rather than global ones
    being silently misread as local.

    A 2-node axial-only element (``truss``/``corotTruss``) reports an EMPTY
    ``"localForce"`` response (confirmed against a live OpenSeesPy run) even
    though it is perfectly well-defined - it only implements ``"axialForce"``.
    Falling back to that and padding into the same (Fxi, Fyi, Fxj, Fyj) shape
    a 2D frame element's local force already has mirrors the equivalent
    special-case in ``MaterialFreeStaticsSolver._collect``
    (``features/analysis/statics/solver.py``).
    """
    response = ops.eleResponse(element_tag, "localForce")
    if response:
        return [float(value) for value in response]
    axial = ops.eleResponse(element_tag, "axialForce")
    if not axial:
        return []
    force = float(axial[0])
    return [-force, 0.0, force, 0.0]


def _element_length(element_tag: int) -> float:
    """Return the member length, needed to evaluate forces between its two ends."""
    nodes = ops.eleNodes(element_tag)
    if len(nodes) < 2:
        return 0.0
    start = ops.nodeCoord(int(nodes[0]))
    end = ops.nodeCoord(int(nodes[1]))
    if len(start) < 2 or len(end) < 2:
        return 0.0
    deltas = [float(b) - float(a) for a, b in zip(start, end, strict=False)]
    return math.sqrt(sum(value * value for value in deltas))


def run_linear_static_analysis(
    source: Path,
    *,
    user_node_tags: set[int] | None = None,
    ndm: int | None = None,
) -> dict[str, Any]:
    """Build the model by executing ``source``, solve it, and return raw results.

    The script only builds: any analysis block it carries is suppressed, so the load
    patterns are applied exactly once, by the single static step below.

    On ``ops.analyze()`` failure the live domain is diagnosed by
    ``InstabilityDiagnosticService`` before ``ops.wipe()`` destroys it.  The
    result is returned (not raised) as ``{"status": "failed", ...}`` so the
    diagnostic data can travel through the subprocess JSON pipe.

    ``user_node_tags`` is the set of node tags that belong to the user's model
    (not auxiliary hinge dummies or ground anchors added by the script).  Pass
    ``None`` when the script does not add any auxiliary nodes - all domain tags
    are then used as the allow-list.  Avoid estimating the range from tag
    numbers; pass the set explicitly from the exporting StructuralModel.

    ``ndm`` is detected from the live domain when ``None``.
    """
    # The section properties are only knowable from the element() call itself, and the
    # deflected shape between two nodes cannot be rebuilt without EI. Its own nested
    # ``element_loads`` (not a second, standalone ``ElementLoadCollector``) is what
    # records -beamUniform loads here — it already knows the model's real ndm (it
    # also wraps ``ops.model()``), whereas a standalone collector's ``eleLoad`` wrap
    # has no way to find that out and silently defaults to 2D, misreading a 3D call's
    # (Wy, Wz, Wx) as 2D's (Wy, Wx) - Wz read as Wx, Wx dropped entirely.
    property_collector = ModelCommandCollector()
    property_collector.install()
    try:
        run_model_script(source)
    finally:
        property_collector.restore()
    load_collector = property_collector.element_loads

    node_tags = [int(tag) for tag in ops.getNodeTags()]
    element_tags = [int(tag) for tag in ops.getEleTags()]
    if not node_tags or not element_tags:
        raise RuntimeError(
            "해석할 모델이 비어 있습니다. 스크립트 끝에서 ops.wipe()로 모델을 지우고 "
            "있지 않은지 확인하세요."
        )

    ops.wipeAnalysis()
    ops.system("BandGeneral")
    ops.numberer("Plain")
    # Imported sources may contain MP constraints such as rigidDiaphragm,
    # equalDOF, or rigidLink.  PlainHandler only enforces homogeneous SP
    # constraints, which silently lets a diaphragm's retained and constrained
    # nodes move independently.  Transformation handles both ordinary fixities
    # and those source-defined MP constraints.
    ops.constraints("Transformation")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    if ops.analyze(1) != 0:
        return _handle_analyze_failure(user_node_tags, ndm, load_collector, element_tags)
    ops.reactions()

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
        "messages": _load_warnings(load_collector, element_tags),
    }


def _handle_analyze_failure(
    user_node_tags: set[int] | None,
    ndm: int | None,
    load_collector: ElementLoadCollector,
    element_tags: list[int],
) -> dict[str, Any]:
    """Run the instability diagnostic on the live domain after analyze() != 0.

    Returns a ``{"status": "failed", ...}`` dict so the failure and diagnostic
    travel through the subprocess JSON pipe intact.  Never raises - a
    diagnostic failure is recorded in the payload, not propagated.

    The diagnostic is intentionally run before any ops.wipe() call so the live
    domain is still present.  The caller must NOT call ops.wipe() before this.
    """
    error_msg = "선형정적해석이 수렴하지 않았습니다."
    diagnostic_json: dict[str, Any] | None = None
    try:
        diagnostic = InstabilityDiagnosticService().diagnose_live(
            user_node_tags_allow_list=user_node_tags,
            ndm=ndm,
        )
        diagnostic_json = instability_diagnostic_to_json(diagnostic)
    except Exception:  # noqa: BLE001 - diagnostic failure must not mask original error
        pass

    messages: list[str] = [f"정역학 계산에 실패했습니다: {error_msg}"]
    if (
        diagnostic_json is not None
        and diagnostic_json.get("diagnostic_success")
        and diagnostic_json.get("mechanism_count", 0) > 0
    ):
        messages.append(diagnostic_json["message"])
    else:
        messages.append("해석이 실패했지만 구조적 불안정 여부는 확인되지 않았습니다.")

    messages.extend(_load_warnings(load_collector, element_tags))

    return {
        "status": "failed",
        "messages": messages,
        "instability_diagnostic": diagnostic_json,
    }


def _flexural_rigidity(collector: ModelCommandCollector, element_tag: int) -> float:
    """Return EI, or 0.0 for elements whose section properties are not known."""
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
