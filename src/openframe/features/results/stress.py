"""Elastic normal stress (σ) from member end forces and section properties.

Peak absolute fibre stress is what the Results Stress view colours by:

    σ = N/A ± M·c/I

with samples along the member when a 2D distributed load makes N/M vary
between the ends. Missing section data is skipped (no silent A=1 / I=1
defaults) so an unassigned member never invents a stress value.

The result table uses the same ``fibre_stress`` helper as the contour so the
two surfaces cannot drift onto different formulas.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from openframe.core.domain import Element, ElementResult, StructuralModel
from openframe.features.results.diagrams import member_diagrams


def fibre_stress(
    element: Element,
    *,
    axial_force: float,
    moment: float = 0.0,
    moment_y: float = 0.0,
    moment_z: float = 0.0,
    ndm: int = 2,
) -> float | None:
    """Signed extreme-fibre normal stress, or ``None`` if section data is missing.

    A truss (``element_type`` contains ``"truss"``) is always ``σ = N/A`` and
    ignores moments. A frame is ``σ = N/A ± M·c/I`` (3D: both ``My`` and
    ``Mz``). The magnitude equals the contour's ``|N/A| + |M|c/I`` at the same
    station; the sign is the extreme fibre's sign so a table cell can still
    show tension vs compression when there is no bending.

    Moments without a usable I (or fibre distance) return ``None`` rather than
    silently dropping to ``N/A`` - that under-report would look like a real
    stress. Axial-only (all moments zero) still returns ``N/A`` without I,
    because I is not required for that case.
    """
    area = _float_prop(element.properties, "A")
    if area is None or area <= 0.0:
        return None

    if "truss" in element.element_type.lower():
        return axial_force / area

    if ndm == 3:
        return _frame_fibre_stress_3d(
            element, area, axial_force, moment_y, moment_z
        )
    return _frame_fibre_stress_2d(element, area, axial_force, moment)


def peak_member_stress(element: Element, result: ElementResult, *, ndm: int) -> float | None:
    """Largest |σ| on the member, or ``None`` when A (and I when needed) are absent."""
    if "truss" in element.element_type.lower():
        axial = _truss_axial(result)
        if axial is None:
            return None
        value = fibre_stress(element, axial_force=axial, ndm=ndm)
        return None if value is None else abs(value)

    if ndm == 3:
        return _peak_stress_3d(element, result)
    return _peak_stress_2d(element, result)


def member_end_stress(
    element: Element, result: ElementResult, *, end: str, ndm: int
) -> float | None:
    """Signed extreme-fibre stress at end ``"i"`` or ``"j"``.

    Uses the same ``fibre_stress`` policy as the contour. End forces are the
    raw local-force components the result table already shows, so the σ column
    is derived from the N/M in that row rather than a second conversion.
    """
    if "truss" in element.element_type.lower():
        axial = _truss_end_axial(result, end)
        if axial is None:
            return None
        return fibre_stress(element, axial_force=axial, ndm=ndm)

    if ndm == 3:
        forces = (*result.local_forces, *((0.0,) * 12))[:12]
        if end == "j":
            return fibre_stress(
                element,
                axial_force=forces[6],
                moment_y=forces[10],
                moment_z=forces[11],
                ndm=3,
            )
        return fibre_stress(
            element,
            axial_force=forces[0],
            moment_y=forces[4],
            moment_z=forces[5],
            ndm=3,
        )

    forces = (*result.local_forces, *((0.0,) * 6))[:6]
    if end == "j":
        return fibre_stress(element, axial_force=forces[3], moment=forces[5], ndm=2)
    return fibre_stress(element, axial_force=forces[0], moment=forces[2], ndm=2)


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


def _frame_fibre_stress_2d(
    element: Element, area: float, axial_force: float, moment: float
) -> float | None:
    inertia = _float_prop(element.properties, "I")
    if inertia is None:
        inertia = _float_prop(element.properties, "Iz")
    if abs(moment) > 0.0 and (inertia is None or inertia <= 0.0):
        return None
    if inertia is None or inertia <= 0.0:
        return axial_force / area
    half_depth = _section_half_depth(element.properties, inertia, area)
    if half_depth is None:
        return None
    return _extreme_fibre(axial_force / area, abs(moment) * half_depth / inertia)


def _frame_fibre_stress_3d(
    element: Element,
    area: float,
    axial_force: float,
    moment_y: float,
    moment_z: float,
) -> float | None:
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
        bending += abs(moment_y) * cy / iy
    if iz is not None and iz > 0.0 and cz is not None:
        bending += abs(moment_z) * cz / iz

    if (abs(moment_y) > 0.0 or abs(moment_z) > 0.0) and bending == 0.0:
        return None
    return _extreme_fibre(axial_force / area, bending)


def _extreme_fibre(axial: float, bending: float) -> float:
    """The fibre with larger |σ|; equals ``axial`` when there is no bending.

    ``max(|a+b|, |a-b|) == |a| + |b|``, which is the contour magnitude.
    """
    tension_side = axial + bending
    compression_side = axial - bending
    if abs(tension_side) >= abs(compression_side):
        return tension_side
    return compression_side


def _peak_stress_2d(element: Element, result: ElementResult) -> float | None:
    peaks: list[float] = []
    for axial_force, moment in _axial_moment_samples_2d(result):
        value = fibre_stress(element, axial_force=axial_force, moment=moment, ndm=2)
        if value is None:
            return None
        peaks.append(abs(value))
    if not peaks:
        return None
    return max(peaks)


def _axial_moment_samples_2d(result: ElementResult) -> tuple[tuple[float, float], ...]:
    try:
        axial_diagram, _shear_diagram, moment_diagram = member_diagrams(result)
    except ValueError:
        forces = (*result.local_forces, *((0.0,) * 6))[:6]
        return ((-forces[0], -forces[2]), (forces[3], forces[5]))
    return tuple(
        (axial_diagram.points[index].value, moment_diagram.points[index].value)
        for index in range(len(axial_diagram.points))
    )


def _peak_stress_3d(element: Element, result: ElementResult) -> float | None:
    i_stress = member_end_stress(element, result, end="i", ndm=3)
    j_stress = member_end_stress(element, result, end="j", ndm=3)
    if i_stress is None or j_stress is None:
        return None
    return max(abs(i_stress), abs(j_stress))


def _truss_axial(result: ElementResult) -> float | None:
    forces = result.local_forces
    if len(forces) >= 2 and len(forces) < 6:
        return max((abs(value) for value in forces), default=0.0)
    if len(forces) >= 6:
        return max(abs(forces[0]), abs(forces[3] if len(forces) == 6 else forces[6]))
    if len(forces) == 0:
        return None
    return abs(forces[0])


def _truss_end_axial(result: ElementResult, end: str) -> float | None:
    forces = result.local_forces
    if not forces:
        return None
    if end == "j":
        if len(forces) >= 12:
            return forces[6]
        if len(forces) >= 6:
            return forces[3]
        if len(forces) >= 2:
            return forces[1]
        return forces[0]
    return forces[0]


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
