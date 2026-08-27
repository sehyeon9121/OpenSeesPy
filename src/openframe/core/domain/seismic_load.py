"""Equivalent Static (linear static) seismic load - the KDS 41-17-style
Equivalent Lateral Force (ELF) procedure, the same structure ASCE 7's
Chapter 12 ELF uses (KDS 41-17's 등가정적해석법 was harmonized from it).

Deliberately does **not** embed any code lookup table (site coefficients
Fa/Fv by site class and Ss/S1 range, the response-modification coefficient R
by structural system, or an approximate-period Ct/x table by structure
type) - those vary by code edition and a wrong hard-coded value would be a
silent, hard-to-notice safety-critical error. Every one of those is a
required *input* here (``fa``/``fv``/``r``/``period``); this module only
automates the arithmetic a code already fully specifies as a formula, not
the table lookups a code specifies as data an engineer looks up themselves.

Every function is pure (no OpenSeesPy, no Qt) and independently testable
against a hand calculation, matching this codebase's other domain-formula
modules (see ``section_properties.py``).
"""

import math
from dataclasses import dataclass

from openframe.core.domain.model import StructuralModel

__all__ = [
    "SeismicLoadParameters",
    "StoryWeight",
    "design_spectral_accelerations",
    "distribute_seismic_force_by_height",
    "distribution_exponent",
    "equivalent_lateral_force",
    "lumped_node_weights",
    "seismic_response_coefficient",
]


@dataclass(frozen=True, slots=True)
class SeismicLoadParameters:
    """Every code-specified coefficient the Equivalent Lateral Force
    procedure needs, all user-supplied (see this module's own docstring for
    why). ``ss``/``s1`` are the mapped short-period/1-second spectral
    accelerations (as a fraction of g); ``fa``/``fv`` the site coefficients;
    ``r`` the response modification coefficient; ``ie`` the seismic
    importance factor; ``period`` the building's fundamental period T
    (seconds) - a modal analysis result is the natural source for this in an
    app that already has one."""

    ss: float
    s1: float
    fa: float
    fv: float
    r: float
    ie: float
    period: float


@dataclass(frozen=True, slots=True)
class StoryWeight:
    """One story's seismic weight ``wx`` (force units, not mass - see
    ``lumped_node_weights``) at height ``height`` above the model's base,
    for the vertical (``Fx = Cvx * V``) distribution."""

    height: float
    weight: float


def design_spectral_accelerations(ss: float, fa: float, s1: float, fv: float) -> tuple[float, float]:
    """(SDS, SD1) - the design (2/3 of maximum considered earthquake)
    spectral response accelerations."""
    return (2.0 / 3.0) * fa * ss, (2.0 / 3.0) * fv * s1


def seismic_response_coefficient(
    *, sds: float, sd1: float, s1: float, r: float, ie: float, period: float
) -> float:
    """Cs, the seismic response coefficient (base shear V = Cs * W).

    ``Cs = SDS / (R/Ie)``, capped by ``SD1 / (T * (R/Ie))`` for T > 0, and
    floored at ``max(0.044*SDS*Ie, 0.01)`` - raised further to
    ``0.5*S1/(R/Ie)`` when S1 >= 0.6 (the code's own "near-source, high S1"
    minimum). ``r`` and ``ie`` must be positive - the ratio R/Ie is the
    structure's own ductility/importance reduction, never zero or negative
    for a real building.
    """
    if r <= 0.0:
        raise ValueError("응답수정계수 R은 0보다 커야 합니다.")
    if ie <= 0.0:
        raise ValueError("중요도계수 Ie는 0보다 커야 합니다.")
    r_over_ie = r / ie
    coefficient = sds / r_over_ie
    if period > 0.0:
        coefficient = min(coefficient, sd1 / (period * r_over_ie))
    minimum = max(0.044 * sds * ie, 0.01)
    if s1 >= 0.6:
        minimum = max(minimum, 0.5 * s1 / r_over_ie)
    return max(coefficient, minimum)


def distribution_exponent(period: float) -> float:
    """k, the vertical distribution exponent - 1.0 for T <= 0.5s (linear),
    2.0 for T >= 2.5s (parabolic), linearly interpolated in between."""
    if period <= 0.5:
        return 1.0
    if period >= 2.5:
        return 2.0
    return 1.0 + (period - 0.5) / 2.0


def distribute_seismic_force_by_height(
    base_shear: float, stories: dict[str, StoryWeight], k: float
) -> dict[str, float]:
    """Fx per story: ``Cvx = wx*hx^k / sum(wi*hi^k)``, ``Fx = Cvx * V``.

    A story at or below the base (height <= 0) contributes nothing to the
    distribution (its own Fx is 0) - height is only ever meaningful measured
    up from the base the seismic force pushes the structure relative to.
    """
    weighted = {
        story_id: story.weight * max(story.height, 0.0) ** k for story_id, story in stories.items()
    }
    denominator = sum(weighted.values())
    if denominator <= 0.0:
        return {story_id: 0.0 for story_id in stories}
    return {
        story_id: base_shear * weight_term / denominator for story_id, weight_term in weighted.items()
    }


def equivalent_lateral_force(
    parameters: SeismicLoadParameters, total_weight: float, stories: dict[str, StoryWeight]
) -> tuple[float, float, dict[str, float]]:
    """Full ELF procedure in one call: returns ``(Cs, V, {story_id: Fx})``.

    ``total_weight`` (W) and each story's own weight in ``stories`` should
    both come from the same source (``lumped_node_weights``, summed) so V
    and sum(Fx) are exactly consistent (equilibrium: sum(Fx) == V).
    """
    sds, sd1 = design_spectral_accelerations(
        parameters.ss, parameters.fa, parameters.s1, parameters.fv
    )
    cs = seismic_response_coefficient(
        sds=sds,
        sd1=sd1,
        s1=parameters.s1,
        r=parameters.r,
        ie=parameters.ie,
        period=parameters.period,
    )
    base_shear = cs * total_weight
    k = distribution_exponent(parameters.period)
    story_forces = distribute_seismic_force_by_height(base_shear, stories, k)
    return cs, base_shear, story_forces


def lumped_node_weights(model: StructuralModel) -> dict[int, float]:
    """Half of each element's own weight (``density * A * length``) to each
    of its two end nodes - the same lumping convention
    ``ModalStaticsSolver._apply_mass`` uses for mass, except this is already
    a *weight* (this app's "density" property is a unit weight, force per
    volume - see ``canvas_model_build.py``'s ``_self_weight_local`` for the
    same convention), so there is no ``/ g`` here: Wx in ``Fx = Cvx*V`` is a
    weight, not a mass.
    """
    weights: dict[int, float] = {}
    for element in model.elements.values():
        try:
            density = float(element.properties["density"])
            area = float(element.properties["A"])
        except (KeyError, TypeError, ValueError):
            continue
        if density == 0.0 or area == 0.0:
            continue
        start = model.nodes[element.node_i]
        end = model.nodes[element.node_j]
        length = math.sqrt(
            (end.x - start.x) ** 2 + (end.y - start.y) ** 2 + (end.z - start.z) ** 2
        )
        if length <= 0.0:
            continue
        half_weight = density * area * length / 2.0
        weights[element.node_i] = weights.get(element.node_i, 0.0) + half_weight
        weights[element.node_j] = weights.get(element.node_j, 0.0) + half_weight
    return weights
