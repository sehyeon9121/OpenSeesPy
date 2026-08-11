"""Run a modal (eigenvalue) analysis for an OpenSeesPy source and collect mode shapes."""

import math
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script


def run_modal_analysis(source: Path, *, num_modes: int = 3) -> dict[str, Any]:
    """Build the model by executing ``source`` and solve for its lowest ``num_modes``
    natural modes.

    Unlike the static solvers, this needs real nodal mass - the script itself must
    define it (``ops.mass(...)``, or an element's own ``-mass``/``-cMass`` option).
    Without mass every DOF's generalized-eigenproblem term is zero, which has no
    physical natural frequency to find.
    """
    property_collector = ModelCommandCollector()
    property_collector.install()
    try:
        run_model_script(source)
    finally:
        property_collector.restore()

    node_tags = [int(tag) for tag in ops.getNodeTags()]
    if not node_tags:
        raise RuntimeError(
            "해석할 모델이 비어 있습니다. 스크립트 끝에서 ops.wipe()로 모델을 지우고 "
            "있지 않은지 확인하세요."
        )
    if num_modes <= 0:
        raise RuntimeError("계산할 모드 수는 1 이상이어야 합니다.")

    total_mass = sum(sum(abs(value) for value in ops.nodeMass(tag)) for tag in node_tags)
    if total_mass <= 0.0:
        raise RuntimeError(
            "절점 질량이 정의되어 있지 않습니다. 고유치 해석에는 ops.mass(...)로 "
            "정의된 질량이 필요합니다."
        )

    ops.wipeAnalysis()
    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("BandGeneral")
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 0.0)
    ops.analysis("Static")
    try:
        # The default solver is ARPACK-based and additionally requires the number of
        # Lanczos vectors to exceed the mode count while staying within the system
        # size - it fails outright on the small models this app typically builds
        # (e.g. asking for as many modes as there are free DOFs). A full/dense LAPACK
        # solve has no such constraint, so it is the fallback rather than the default:
        # it is markedly slower, which only matters once a model is big enough that
        # the default solver would have succeeded anyway.
        eigenvalues = ops.eigen(num_modes)
    except Exception:  # noqa: BLE001 - OpenSeesPy's own C++-backed exception types.
        try:
            eigenvalues = ops.eigen("-fullGenLapack", num_modes)
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(
                f"고유치 해석이 수렴하지 않았습니다: {error}. 모드 수를 줄이거나 질량/지점 "
                "조건을 확인하세요."
            ) from error

    mode_shapes: list[dict[str, Any]] = []
    for index, raw_eigenvalue in enumerate(eigenvalues, start=1):
        eigenvalue = float(raw_eigenvalue)
        if eigenvalue <= 0.0:
            # A near-zero or negative eigenvalue is a rigid-body/spurious mode (an
            # unrestrained or massless DOF), not a real vibration mode - sqrt() of it
            # is not a frequency, so it is skipped rather than reported as one.
            continue
        angular_frequency = math.sqrt(eigenvalue)
        frequency_hz = angular_frequency / (2.0 * math.pi)
        period = 1.0 / frequency_hz if frequency_hz > 0.0 else 0.0
        mode_shapes.append(
            {
                "mode_number": index,
                "eigenvalue": eigenvalue,
                "angular_frequency": angular_frequency,
                "frequency_hz": frequency_hz,
                "period": period,
                "node_results": [
                    {
                        "node_tag": tag,
                        "displacement": [float(v) for v in ops.nodeEigenvector(tag, index)],
                    }
                    for tag in node_tags
                ],
            }
        )

    if not mode_shapes:
        raise RuntimeError("유효한 고유모드를 찾지 못했습니다. 질량과 지점 조건을 확인하세요.")

    return {
        "status": "completed",
        "mode_shapes": mode_shapes,
        "messages": [],
    }
