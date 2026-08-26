"""Run a response spectrum analysis for an OpenSeesPy source.

Unlike modal analysis (``modal_solver.py``), this needs member forces and
reactions, not just mode shapes - so each retained mode's equivalent static
force is actually solved for (a real ``ops.analyze(1)`` per mode per
direction, reusing the same domain the eigen solve just ran on, since
``run_model_script`` never calls ``ops.wipe()``), then every response
quantity (displacement/reaction/local force component) is combined via SRSS
- first conceptually across modes within one direction, then across
directions. In practice these two SRSS stages collapse into a single flat
SRSS over every (mode, direction) value, since
``sqrt(sum(sqrt(sum(x_i**2))**2 for each direction)) == sqrt(sum(x_i**2 for
every i))`` - the code still keeps a per-direction accumulation step (rather
than one flat sum) so a future CQC modal combination (which does *not*
collapse this way, since it introduces cross-mode correlation terms) can
replace just that inner step without restructuring the direction loop.

Every combined value is >= 0 - SRSS destroys sign - so a design check must
still apply the result as +/- itself; see ``response_spectrum_settings`` in
the returned payload for what SETUP/Result Tables echo back as a disclaimer.
"""

import math
from itertools import pairwise
from pathlib import Path
from typing import Any

import openseespy.opensees as ops

from openframe.core.domain.units import acceleration_to_model_unit_factor
from openframe.infrastructure.opensees.linear_static_solver import (
    _element_length,
    _flexural_rigidity,
    _local_forces,
)
from openframe.infrastructure.opensees.model_collector import ModelCommandCollector
from openframe.infrastructure.opensees.script_execution import run_model_script

_DIRECTION_DOF_INDEX = {"X": 0, "Y": 1, "Z": 2}
#: Load-pattern tags this solver mints for its own per-mode equivalent-static
#: solves - offset far past anything an imported script would plausibly
#: define itself, the same defensive-tag-space convention this app already
#: uses elsewhere (e.g. the trapezoidal-load discretizer's own tag offsets).
_PATTERN_TAG_BASE = 900_000_000


def _interpolate(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation, clamped at the table's own ends - a mode period
    outside the entered spectrum's range uses the nearest edge value rather
    than extrapolating."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for index in range(1, len(xs)):
        if x <= xs[index]:
            x0, x1 = xs[index - 1], xs[index]
            y0, y1 = ys[index - 1], ys[index]
            fraction = (x - x0) / (x1 - x0) if x1 != x0 else 0.0
            return y0 + (y1 - y0) * fraction
    return ys[-1]


def run_response_spectrum_analysis(
    source: Path,
    *,
    periods: list[float],
    spectral_accelerations: list[float],
    acceleration_unit: str = "g",
    num_modes: int = 10,
    directions: tuple[str, ...] = ("X", "Y"),
    model_length_unit: str = "m",
) -> dict[str, Any]:
    if len(periods) < 2 or len(periods) != len(spectral_accelerations):
        raise RuntimeError("스펙트럼 표에는 서로 다른 주기의 (주기, Sa) 쌍이 2개 이상 필요합니다.")
    pairs = sorted(zip(periods, spectral_accelerations, strict=True))
    sorted_periods = [pair[0] for pair in pairs]
    if any(b <= a for a, b in pairwise(sorted_periods)):
        raise RuntimeError("스펙트럼 표의 주기 값이 중복됩니다 - 모든 주기가 서로 달라야 합니다.")
    sorted_sa = [pair[1] for pair in pairs]
    unit_factor = acceleration_to_model_unit_factor(acceleration_unit, model_length_unit)

    property_collector = ModelCommandCollector()
    property_collector.install()
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
    node_masses = {tag: [float(value) for value in ops.nodeMass(tag)] for tag in node_tags}
    ndf = max((len(masses) for masses in node_masses.values()), default=0)
    total_mass = sum(sum(abs(value) for value in masses) for masses in node_masses.values())
    if total_mass <= 0.0:
        raise RuntimeError(
            "절점 질량이 정의되어 있지 않습니다. 응답스펙트럼 해석에는 ops.mass(...)로 "
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
        eigenvalues = ops.eigen(num_modes)
    except Exception:  # noqa: BLE001 - OpenSeesPy's own C++-backed exception types.
        try:
            eigenvalues = ops.eigen("-fullGenLapack", num_modes)
        except Exception as error:
            raise RuntimeError(
                f"고유치 해석이 수렴하지 않았습니다: {error}. 모드 수를 줄이거나 질량/지점 "
                "조건을 확인하세요."
            ) from error

    modes: list[dict[str, Any]] = []
    for index, raw_eigenvalue in enumerate(eigenvalues, start=1):
        eigenvalue = float(raw_eigenvalue)
        if eigenvalue <= 0.0:
            continue  # rigid-body/spurious mode, same filter modal_solver.py uses.
        angular_frequency = math.sqrt(eigenvalue)
        frequency_hz = angular_frequency / (2.0 * math.pi)
        period = 1.0 / frequency_hz if frequency_hz > 0.0 else 0.0
        eigenvectors = {tag: [float(v) for v in ops.nodeEigenvector(tag, index)] for tag in node_tags}
        modes.append({"mode_number": index, "period": period, "eigenvectors": eigenvectors})
    if not modes:
        raise RuntimeError("유효한 고유모드를 찾지 못했습니다. 질량과 지점 조건을 확인하세요.")

    used_directions = [
        direction
        for direction in directions
        if _DIRECTION_DOF_INDEX.get(direction, ndf) < ndf
    ]
    if not used_directions:
        raise RuntimeError("유효한 가진 방향이 없습니다(모델의 자유도 개수를 확인하세요).")

    node_disp_sq: dict[int, list[float]] = {tag: [0.0] * ndf for tag in node_tags}
    node_reaction_sq: dict[int, list[float]] = {tag: [0.0] * ndf for tag in node_tags}
    element_force_sq: dict[int, list[float]] = {}
    element_length: dict[int, float] = {}
    next_pattern_tag = _PATTERN_TAG_BASE

    for direction in used_directions:
        dof = _DIRECTION_DOF_INDEX[direction]
        direction_disp_sq = {tag: [0.0] * ndf for tag in node_tags}
        direction_reaction_sq = {tag: [0.0] * ndf for tag in node_tags}
        direction_force_sq: dict[int, list[float]] = {}

        for mode in modes:
            eigenvectors = mode["eigenvectors"]
            participation = 0.0
            modal_mass = 0.0
            for tag, masses in node_masses.items():
                mass = masses[dof] if dof < len(masses) else 0.0
                vector = eigenvectors.get(tag, [])
                value = vector[dof] if dof < len(vector) else 0.0
                participation += mass * value
                modal_mass += mass * value * value
            if modal_mass <= 0.0:
                continue  # this direction has no mass to excite in this mode.
            gamma = participation / modal_mass
            spectral_acceleration = _interpolate(sorted_periods, sorted_sa, mode["period"]) * unit_factor

            next_pattern_tag += 1
            pattern_tag = next_pattern_tag
            ops.timeSeries("Linear", pattern_tag)
            ops.pattern("Plain", pattern_tag, pattern_tag)
            applied_load = False
            for tag, masses in node_masses.items():
                mass = masses[dof] if dof < len(masses) else 0.0
                vector = eigenvectors.get(tag, [])
                value = vector[dof] if dof < len(vector) else 0.0
                force = gamma * mass * value * spectral_acceleration
                if force == 0.0:
                    continue
                load_values = [0.0] * ndf
                load_values[dof] = force
                ops.load(tag, *load_values)
                applied_load = True
            if not applied_load:
                ops.remove("loadPattern", pattern_tag)
                continue

            ops.wipeAnalysis()
            # Pseudo-time is a domain-wide concept, not per-pattern - without
            # resetting it to 0 before every mode's solve, each subsequent
            # mode's "Linear" TimeSeries (whose factor is the *absolute*
            # pseudo-time, not the increment just taken) would scale that
            # mode's own load by however many modes came before it,
            # silently inflating every mode after the first.
            ops.setTime(0.0)
            ops.constraints("Transformation")
            ops.numberer("RCM")
            ops.system("BandGeneral")
            ops.algorithm("Linear")
            ops.integrator("LoadControl", 1.0)
            ops.analysis("Static")
            if ops.analyze(1) != 0:
                ops.remove("loadPattern", pattern_tag)
                raise RuntimeError(
                    f"{direction}방향 {mode['mode_number']}차 모드의 등가정적하중 해석이 "
                    "수렴하지 않았습니다."
                )
            ops.reactions()

            for tag in node_tags:
                displacement = ops.nodeDisp(tag)
                reaction = ops.nodeReaction(tag)
                for component in range(ndf):
                    disp_value = float(displacement[component]) if component < len(displacement) else 0.0
                    reaction_value = float(reaction[component]) if component < len(reaction) else 0.0
                    direction_disp_sq[tag][component] += disp_value * disp_value
                    direction_reaction_sq[tag][component] += reaction_value * reaction_value
            for tag in element_tags:
                local_forces = _local_forces(tag)
                if tag not in element_length:
                    element_length[tag] = _element_length(tag)
                squares = direction_force_sq.setdefault(tag, [0.0] * len(local_forces))
                for component, value in enumerate(local_forces):
                    squares[component] += float(value) * float(value)

            ops.remove("loadPattern", pattern_tag)

        for tag in node_tags:
            for component in range(ndf):
                node_disp_sq[tag][component] += direction_disp_sq[tag][component]
                node_reaction_sq[tag][component] += direction_reaction_sq[tag][component]
        for tag, squares in direction_force_sq.items():
            totals = element_force_sq.setdefault(tag, [0.0] * len(squares))
            for component, value in enumerate(squares):
                totals[component] += value

    return {
        "status": "completed",
        "node_results": [
            {
                "node_tag": tag,
                "displacement": [math.sqrt(value) for value in node_disp_sq[tag]],
                "reaction": [math.sqrt(value) for value in node_reaction_sq[tag]],
            }
            for tag in node_tags
        ],
        "element_results": [
            {
                "element_tag": tag,
                "local_forces": [math.sqrt(value) for value in element_force_sq.get(tag, [])],
                "length": element_length.get(tag, 0.0),
                "uniform_load": [0.0, 0.0],
                "flexural_rigidity": _flexural_rigidity(property_collector, tag),
            }
            for tag in element_tags
        ],
        "response_spectrum_settings": {
            "num_modes": len(modes),
            "directions": list(used_directions),
            "combination_method": "SRSS",
            "periods": sorted_periods,
            "spectral_accelerations": sorted_sa,
            "acceleration_unit": acceleration_unit,
        },
        "messages": [
            "SRSS로 결합된 값은 부호가 없습니다 - 설계 시 +/-로 적용하세요."
        ],
    }
