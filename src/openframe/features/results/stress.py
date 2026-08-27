"""Elastic normal stress (σ) from member end forces and section properties.

Peak absolute fibre stress is what the Results Stress view colours by:

    σ = N/A ± M·c/I

with samples along the member when a 2D distributed load makes N/M vary
between the ends. Missing section data is skipped (no silent A=1 / I=1
defaults) so an unassigned member never invents a stress value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from openframe.core.domain import Element, ElementResult, StructuralModel
from openframe.features.results.diagrams import member_diagrams


def peak_member_stress(element: Element, result: ElementResult, *, ndm: int) -> float | None:
    """Largest |σ| on the member, or ``None`` when A (and I when needed) are absent."""
    area = _float_prop(element.properties, "A")
    if area is None or area <= 0.0:
        return None

    if "truss" in element.element_type.lower():
        axial = _truss_axial(result)
        if axial is None:
            return None
        return abs(axial / area)

    if ndm == 3:
        return _peak_stress_3d(element, result, area)
    return _peak_stress_2d(element, result, area)


def member_stress_magnitudes(
    model: StructuralModel, element_results: Mapping[int, ElementResult]
) -> dict[int, float]:
    """Per-element peak |σ|; members without usable section props are omitted."""
    magnitudes: dict[int, float] = {}
    for tag, element in model.elements.items():
        result = element_results.get(tag)
        if result is None:
            continue
        peak = peak_member_stress(element, result, ndm=model.ndm)
        if peak is None:
            continue
        magnitudes[tag] = peak
    return magnitudes


def _peak_stress_2d(element: Element, result: ElementResult, area: float) -> float | None:
    inertia = _float_prop(element.properties, "I")
    if inertia is None:
        inertia = _float_prop(element.properties, "Iz")
    if inertia is None or inertia <= 0.0:
        # Axial-only when bending stiffness is unavailable (still exact for N/A).
        axial = _truss_axial(result)
        return None if axial is None else abs(axial / area)

    half_depth = _section_half_depth(element.properties, inertia, area)
    if half_depth is None:
        return None

    try:
        axial_diagram, _shear_diagram, moment_diagram = member_diagrams(result)
    except ValueError:
        forces = (*result.local_forces, *((0.0,) * 6))[:6]
        samples = (
            (-forces[0], -forces[2]),
            (forces[3], forces[5]),
        )
        return max(abs(n / area) + abs(m) * half_depth / inertia for n, m in samples)

    return max(
        abs(axial_diagram.points[index].value / area)
        + abs(moment_diagram.points[index].value) * half_depth / inertia
        for index in range(len(axial_diagram.points))
    )


def _peak_stress_3d(element: Element, result: ElementResult, area: float) -> float | None:
    forces = (*result.local_forces, *((0.0,) * 12))[:12]
    # OpenSees 3D beam-column local end forces:
    # (N, Vy, Vz, T, My, Mz)_i then same order at j.
    axial = max(abs(forces[0]), abs(forces[6]))
    my = max(abs(forces[4]), abs(forces[10]))
    mz = max(abs(forces[5]), abs(forces[11]))

    iy = _float_prop(element.properties, "Iy")
    iz = _float_prop(element.properties, "Iz")
    if iy is None:
        iy = _float_prop(element.properties, "I")
    if iz is None:
        iz = iy

    cy = _section_half_size(element.properties, ("height", "dim_H", "H"), iy, area)
    cz = _section_half_size(element.properties, ("width", "dim_B", "B"), iz, area)

    bending = 0.0
    if iy is not None and iy > 0.0 and cy is not None:
        bending += my * cy / iy
    if iz is not None and iz > 0.0 and cz is not None:
        bending += mz * cz / iz

    # Moments without a usable fibre distance would under-report stress if we
    # returned N/A alone - omit the member until section geometry is assigned.
    if (my > 0.0 or mz > 0.0) and bending == 0.0:
        return None

    return axial / area + bending


def _truss_axial(result: ElementResult) -> float | None:
    forces = result.local_forces
    if len(forces) >= 2 and len(forces) < 6:
        # truss: (N_i, N_j) or similar short tuple
        return max((abs(value) for value in forces), default=0.0)
    if len(forces) >= 6:
        return max(abs(forces[0]), abs(forces[3] if len(forces) == 6 else forces[6]))
    if len(forces) == 0:
        return None
    return abs(forces[0])


def _section_half_depth(properties: Mapping[str, float | str], inertia: float, area: float) -> float | None:
    return _section_half_size(properties, ("height", "dim_H", "H"), inertia, area)


def _section_half_size(
    properties: Mapping[str, float | str],
    keys: tuple[str, ...],
    inertia: float | None,
    area: float,
) -> float | None:
    for key in keys:
        value = _float_prop(properties, key)
        if value is not None and value > 0.0:
            return value / 2.0
    # Equivalent rectangle: I = b h^3 / 12, A = b h → h = sqrt(12 I / A), c = h/2.
    if inertia is None or inertia <= 0.0 or area <= 0.0:
        return None
    return math.sqrt(3.0 * inertia / area)


def _float_prop(properties: Mapping[str, float | str], key: str) -> float | None:
    value = properties.get(key)
    if value is None or isinstance(value, str):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number
