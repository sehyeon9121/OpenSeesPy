"""Run a modal (eigenvalue) analysis for an OpenSeesPy source and collect mode shapes."""

import math
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script

#: Direction labels in the order OpenSeesPy reports node results in, per ndf.
#: A model with fewer than 6 DOFs per node (2D) has no Z/RX/RY components at all.
_DIRECTION_LABELS_6 = ("X", "Y", "Z", "RX", "RY", "RZ")
_DIRECTION_LABELS_3 = ("X", "Y", "RZ")


def _direction_dof_index(direction: str, ndf: int) -> int | None:
    """Map a target-participation direction label to its index in the model's
    own per-node mass/eigenvector arrays, or ``None`` if that direction has no
    DOF in this model (e.g. "RZ" on a 2D truss with ndf=2)."""
    labels = _DIRECTION_LABELS_6 if ndf >= 6 else _DIRECTION_LABELS_3
    try:
        index = labels.index(direction)
    except ValueError:
        return None
    return index if index < ndf else None


def run_modal_analysis(
    source: Path,
    *,
    extraction_method: str = "fixed",
    num_modes: int = 10,
    target_participation: float = 90.0,
    target_directions: str = "",
    max_modes: int = 50,
) -> dict[str, Any]:
    """Build the model by executing ``source`` and solve for its natural modes.

    Two extraction methods are supported:

    - ``"fixed"`` (default): solve for exactly ``num_modes`` modes, regardless of
      how quickly cumulative mass participation reaches 100%.
    - ``"target"``: solve for up to ``max_modes`` modes, stopping as soon as every
      direction listed in ``target_directions`` (a comma-separated subset of
      "X", "Y", "Z", "RX", "RY", "RZ") has accumulated at least
      ``target_participation`` percent of that direction's total mass. A
      direction with no mass in this model (or no matching DOF, e.g. "RZ" on a
      2D truss) is skipped rather than blocking termination forever.

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
    is_target = extraction_method == "target"
    modes_to_solve = max_modes if is_target else num_modes
    if modes_to_solve <= 0:
        raise RuntimeError("계산할 모드 수는 1 이상이어야 합니다.")

    node_masses = {tag: [float(value) for value in ops.nodeMass(tag)] for tag in node_tags}
    total_mass = sum(sum(abs(value) for value in masses) for masses in node_masses.values())
    if total_mass <= 0.0:
        raise RuntimeError(
            "절점 질량이 정의되어 있지 않습니다. 고유치 해석에는 ops.mass(...)로 "
            "정의된 질량이 필요합니다."
        )
    ndf = max((len(masses) for masses in node_masses.values()), default=0)
    #: Total mass lumped in each DOF direction, independent of mode - the
    #: denominator every mode's effective modal mass is measured against.
    total_mass_per_dof = [
        sum(masses[dof] if dof < len(masses) else 0.0 for masses in node_masses.values())
        for dof in range(ndf)
    ]

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
        eigenvalues = ops.eigen(modes_to_solve)
    except Exception:  # noqa: BLE001 - OpenSeesPy's own C++-backed exception types.
        try:
            eigenvalues = ops.eigen("-fullGenLapack", modes_to_solve)
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(
                f"고유치 해석이 수렴하지 않았습니다: {error}. 모드 수를 줄이거나 질량/지점 "
                "조건을 확인하세요."
            ) from error

    # Directions the "target" method must satisfy before it stops adding modes -
    # a direction with no mass in this model (or no matching DOF at all) can
    # never accumulate participation, so it is dropped here rather than
    # forcing every run out to max_modes.
    target_dof_indices = []
    if is_target:
        for direction in (part.strip() for part in target_directions.split(",")):
            if not direction:
                continue
            dof_index = _direction_dof_index(direction, ndf)
            if dof_index is not None and total_mass_per_dof[dof_index] > 0.0:
                target_dof_indices.append(dof_index)
    target_fraction = target_participation / 100.0

    mode_shapes: list[dict[str, Any]] = []
    cumulative_ratio = [0.0] * ndf
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
        node_eigenvectors = {
            tag: [float(v) for v in ops.nodeEigenvector(tag, index)] for tag in node_tags
        }
        ratios = _mass_participation_ratios(
            node_masses, node_eigenvectors, ndf, total_mass_per_dof
        )
        for dof in range(ndf):
            cumulative_ratio[dof] += ratios[dof]
        mode_shapes.append(
            {
                "mode_number": index,
                "eigenvalue": eigenvalue,
                "angular_frequency": angular_frequency,
                "frequency_hz": frequency_hz,
                "period": period,
                "node_results": [
                    {"node_tag": tag, "displacement": vector}
                    for tag, vector in node_eigenvectors.items()
                ],
                "mass_participation_ratio": ratios,
            }
        )
        if (
            is_target
            and target_dof_indices
            and all(cumulative_ratio[dof] >= target_fraction for dof in target_dof_indices)
        ):
            break

    if not mode_shapes:
        raise RuntimeError("유효한 고유모드를 찾지 못했습니다. 질량과 지점 조건을 확인하세요.")

    messages: list[str] = []
    if (
        is_target
        and target_dof_indices
        and not all(cumulative_ratio[dof] >= target_fraction for dof in target_dof_indices)
    ):
        messages.append(
            f"최대 모드 수({max_modes})까지 계산했지만 목표 질량참여율"
            f"({target_participation:g}%)에 도달하지 못했습니다."
        )

    return {
        "status": "completed",
        "mode_shapes": mode_shapes,
        "messages": messages,
    }


def _mass_participation_ratios(
    node_masses: dict[int, list[float]],
    node_eigenvectors: dict[int, list[float]],
    ndf: int,
    total_mass_per_dof: list[float],
) -> list[float]:
    """Fraction of each DOF direction's total mass this mode's effective modal
    mass accounts for.

    Computed straight from the lumped mass matrix and the raw eigenvector rather
    than assumed from how ``ops.eigen`` happens to normalize it (mass-normalized
    vs. unit-max-entry differs by solver/version), so the result stays correct
    either way:  generalized modal mass ``m* = phi^T * M * phi``, participation
    factor ``L_d = phi_d^T * M_d`` per direction, effective mass ``L_d^2 / m*``.
    """
    modal_mass = 0.0
    participation = [0.0] * ndf
    for tag, masses in node_masses.items():
        vector = node_eigenvectors.get(tag, [])
        for dof in range(ndf):
            mass = masses[dof] if dof < len(masses) else 0.0
            value = vector[dof] if dof < len(vector) else 0.0
            modal_mass += mass * value * value
            participation[dof] += mass * value
    if modal_mass <= 0.0:
        return [0.0] * ndf
    ratios = []
    for dof in range(ndf):
        total = total_mass_per_dof[dof]
        if total <= 0.0:
            ratios.append(0.0)
            continue
        effective_mass = participation[dof] ** 2 / modal_mass
        ratios.append(effective_mass / total)
    return ratios
