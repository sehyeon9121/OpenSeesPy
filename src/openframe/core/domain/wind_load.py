"""Static wind load - the KDS 41-12-style design wind pressure procedure
(``p = qz * Gf * Cp``, the same structure ASCE 7's Directional Procedure
uses for a regular, low/mid-rise building's Main Wind-Force Resisting
System).

Same philosophy as ``seismic_load.py``: no code lookup table is embedded
(exposure category height factor Kz, basic wind speed by region, gust
factor by structure dynamics) - every one of those is a direct input. To
sidestep a second, unit-system-shaped risk (the physics form of velocity
pressure, ``qz = 0.5 * air_density * Kz * Kzt * Kd * V^2``, needs the app's
own force/length^2 unit system reconciled against a physical constant in
kg/m^3), the user instead supplies the *reference design velocity pressure*
``q0`` directly, already expressed in the model's own stress unit (computed
however they like, from that formula or a code table) - Kz per story then
only ever scales that reference value, a plain dimensionless ratio with no
unit-conversion risk at all.
"""

from dataclasses import dataclass

__all__ = [
    "WindLoadParameters",
    "story_tributary_heights",
    "wind_force_by_story",
    "wind_pressure",
]


@dataclass(frozen=True, slots=True)
class WindLoadParameters:
    """``q0`` (reference design velocity pressure, model's own stress
    unit), ``gust_factor`` (Gf), ``pressure_coefficient`` (Cp - net,
    windward+leeward combined, for a simple enclosed building), and
    ``exposed_width`` (the building's own plan width perpendicular to the
    wind direction, model's own length unit) - every one a direct,
    user-supplied value (see this module's own docstring)."""

    reference_pressure: float
    gust_factor: float
    pressure_coefficient: float
    exposed_width: float


def wind_pressure(reference_pressure: float, kz: float, gust_factor: float, pressure_coefficient: float) -> float:
    """p = q0 * Kz * Gf * Cp - the design wind pressure at one story."""
    return reference_pressure * kz * gust_factor * pressure_coefficient


def story_tributary_heights(story_elevations: dict[str, float]) -> dict[str, float]:
    """Half the span down to the story below plus half the span up to the
    story above, for each story - the standard tributary-height split for a
    wind load applied story-by-story. The lowest story gets no contribution
    below itself (nothing bounds it there unless the model has its own
    story at that lower elevation too - e.g. one at grade), and the highest
    gets none above (the roof line) - both ends bounded by themselves,
    symmetric treatment, no invented "ground story"."""
    ordered = sorted(story_elevations.items(), key=lambda item: item[1])
    heights: dict[str, float] = {}
    for index, (story_id, elevation) in enumerate(ordered):
        lower = ordered[index - 1][1] if index > 0 else elevation
        upper = ordered[index + 1][1] if index < len(ordered) - 1 else elevation
        heights[story_id] = (elevation - lower) / 2.0 + (upper - elevation) / 2.0
    return heights


def wind_force_by_story(
    parameters: WindLoadParameters,
    story_kz: dict[str, float],
    story_elevations: dict[str, float],
) -> dict[str, float]:
    """Force per story: ``F = p(story) * exposed_width * tributary_height``.

    ``story_kz`` and ``story_elevations`` should share the same keys (a
    story missing from ``story_kz`` simply gets no force - the caller
    decides what "no Kz entered yet" should default to, this module never
    guesses one)."""
    heights = story_tributary_heights(story_elevations)
    forces: dict[str, float] = {}
    for story_id, kz in story_kz.items():
        pressure = wind_pressure(
            parameters.reference_pressure, kz, parameters.gust_factor, parameters.pressure_coefficient
        )
        forces[story_id] = pressure * parameters.exposed_width * heights.get(story_id, 0.0)
    return forces
