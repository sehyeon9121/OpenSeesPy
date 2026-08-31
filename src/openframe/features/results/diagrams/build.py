"""Build per-element force diagrams from raw local end forces."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from openframe.core.domain import ElementResult
from openframe.features.results.diagrams import axial, moment, shear
from openframe.features.results.diagrams.base import (
    DiagramKind,
    DiagramPoint,
    MemberDiagram,
)

# 2D beam-column end forces along the member's local axes:
# (N_i, V_i, M_i, N_j, V_j, M_j). These are the forces the element exerts on its nodes,
# so they must be converted to internal forces read continuously from end i to end j.
# Verified against textbook cases (cantilever with tip load; simply supported beam with a
# central point load, where M = PL/4 sagging and V = +P/2 then -P/2):
#   axial   N = -N_i = +N_j   (tension positive)
#   shear   V = +V_i = -V_j
#   moment  M = -M_i = +M_j   (sagging positive)
_LOCAL_FORCE_COUNT = 6
#: OpenSees 3D elasticBeamColumn ``localForce``: (N, Vy, Vz, T, My, Mz) at i, then j.
_LOCAL_FORCE_COUNT_3D = 12

# With a distributed load the internal forces are rebuilt from equilibrium along the
# member, not just interpolated between the two end values, or a span maximum between
# the ends would be missed entirely. The load varies linearly from w_i at end i to w_j
# at end j (w_i == w_j is the plain uniform case), so with w(s) = w_i + (w_j-w_i)*s/L:
#   N(x) = -N_i - integral of wx(s) ds, 0..x  = -N_i - wx_i*x - (wx_j-wx_i)*x^2/(2L)
#   V(x) =  V_i + integral of wy(s) ds, 0..x  =  V_i + wy_i*x + (wy_j-wy_i)*x^2/(2L)
#   M(x) = -M_i + integral of V(s) ds, 0..x   = -M_i + V_i*x + wy_i*x^2/2 + (wy_j-wy_i)*x^3/(6L)
# Verified three ways for the uniform case wy_i==wy_j (a UDL beam, M=wL^2/8 at midspan;
# a UDL cantilever, M=-wL^2/2 at the fixed end) and independently re-derived with sympy
# for the general linear case (reduces exactly to the uniform formulas when w_i==w_j).
_SPAN_SAMPLES = 20


def member_diagrams(element: ElementResult) -> tuple[MemberDiagram, MemberDiagram, MemberDiagram]:
    forces = element.local_forces
    if len(forces) != _LOCAL_FORCE_COUNT:
        raise ValueError(
            f"부재 {element.element_tag}: 2D elasticBeamColumn 형식의 단부력(6개 값)이 아닙니다."
        )
    axial_i, shear_i, moment_i, axial_j, shear_j, moment_j = forces
    load_x_i, load_y_i, load_x_j, load_y_j = element.uniform_load
    length = element.length

    if (
        load_x_i == 0.0
        and load_y_i == 0.0
        and load_x_j == 0.0
        and load_y_j == 0.0
    ) or length <= 0.0:
        return (
            axial.from_end_forces(element.element_tag, -axial_i, axial_j),
            shear.from_end_forces(element.element_tag, shear_i, -shear_j),
            moment.from_end_forces(element.element_tag, -moment_i, moment_j),
        )

    slope_x = (load_x_j - load_x_i) / length
    slope_y = (load_y_j - load_y_i) / length
    positions = _sample_positions(shear_i, load_y_i, slope_y, length)
    return (
        _sampled(
            element.element_tag,
            DiagramKind.AXIAL,
            positions,
            lambda x: -axial_i - load_x_i * x - slope_x * x * x / 2.0,
            length,
        ),
        _sampled(
            element.element_tag,
            DiagramKind.SHEAR,
            positions,
            lambda x: shear_i + load_y_i * x + slope_y * x * x / 2.0,
            length,
        ),
        _sampled(
            element.element_tag,
            DiagramKind.MOMENT,
            positions,
            lambda x: -moment_i + shear_i * x + load_y_i * x * x / 2.0 + slope_y * x ** 3 / 6.0,
            length,
        ),
    )


@dataclass(frozen=True, slots=True)
class MemberDiagrams3D:
    """Internal N / Vy / Vz / My / Mz along a 3D beam-column, same sign
    convention as the 2D ``member_diagrams`` pair (tension, sagging positive).

    Torsion is omitted on purpose: the result viewport's three force buttons
    are still N / V / M, and a 3D T diagram would need its own control.
    """

    axial: MemberDiagram
    shear_y: MemberDiagram
    shear_z: MemberDiagram
    moment_y: MemberDiagram
    moment_z: MemberDiagram


def member_diagrams_3d(element: ElementResult) -> MemberDiagrams3D:
    """Internal N/V/M along a 3D beam-column from OpenSees ``localForce``.

    N, Vy, Vz, Mz use the same end-force flip as the 2D 6-tuple (tension and
    sagging positive; hogging Mz at a fixed end is negative). My cannot use
    that same flip. OpenSees' 3D equilibrium is ``dMz/dx = Vy`` but
    ``dMy/dx = -Vz`` (right-hand pair: a tip load in -local y produces
    ``Mz_i = +PL``, the analogous load in -local z produces ``My_i = -PL``).
    Flipping My the way Mz is flipped would make hogging in the x-z plane
    read as sagging and draw the tension-side ribbon on the compression
    face. So My is ``+My_i = -My_j``.

    3D ``ElementResult.uniform_load`` is still the 2D ``(wx, wy, wx_j, wy_j)``
    tuple - there is no wz to rebuild a Vz/My parabola from - so this only
    interpolates the two ends. That is exact for nodal-load-only members,
    which is every 3D model the material-free solver currently emits.
    """
    forces = element.local_forces
    if len(forces) != _LOCAL_FORCE_COUNT_3D:
        raise ValueError(
            f"부재 {element.element_tag}: 3D elasticBeamColumn 형식의 단부력"
            f"({_LOCAL_FORCE_COUNT_3D}개 값)이 아닙니다."
        )
    (
        axial_i,
        shear_y_i,
        shear_z_i,
        _torsion_i,
        moment_y_i,
        moment_z_i,
        axial_j,
        shear_y_j,
        shear_z_j,
        _torsion_j,
        moment_y_j,
        moment_z_j,
    ) = forces
    tag = element.element_tag
    return MemberDiagrams3D(
        axial=axial.from_end_forces(tag, -axial_i, axial_j),
        shear_y=shear.from_end_forces(tag, shear_y_i, -shear_y_j),
        shear_z=shear.from_end_forces(tag, shear_z_i, -shear_z_j),
        moment_y=moment.from_end_forces(tag, moment_y_i, -moment_y_j),
        moment_z=moment.from_end_forces(tag, -moment_z_i, moment_z_j),
    )


def max_abs_value(diagrams: Iterable[MemberDiagram]) -> float:
    values = [point.value for diagram in diagrams for point in diagram.points]
    return max((abs(value) for value in values), default=0.0)


def _sample_positions(
    shear_i: float, load_y_i: float, slope_y: float, length: float
) -> tuple[float, ...]:
    """Evenly spaced positions plus the exact station(s) where the moment turns.

    Sampling alone can straddle the parabola's (or, for a trapezoidal load, cubic's)
    vertex and under-report the peak, so the stationary point(s) of M(x) - where the
    shear V(x) = shear_i + load_y_i*x + slope_y*x^2/2 crosses zero - are added when
    they lie inside the member. A uniform load makes V(x) linear (slope_y == 0, one
    root, solved directly to avoid dividing by zero in the quadratic formula); a
    trapezoidal load makes it quadratic, so up to two roots can fall inside the span.
    """
    positions = [index / _SPAN_SAMPLES for index in range(_SPAN_SAMPLES + 1)]
    for turning_point in _shear_zero_crossings(shear_i, load_y_i, slope_y):
        if 0.0 < turning_point < length:
            positions.append(turning_point / length)
    return tuple(sorted(set(positions)))


def _shear_zero_crossings(shear_i: float, load_y_i: float, slope_y: float) -> tuple[float, ...]:
    if slope_y == 0.0:
        if load_y_i == 0.0:
            return ()
        return (-shear_i / load_y_i,)
    # slope_y/2 * x^2 + load_y_i * x + shear_i = 0
    a = slope_y / 2.0
    b = load_y_i
    c = shear_i
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0.0:
        return ()
    root = discriminant ** 0.5
    return ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a))


def _sampled(
    element_tag: int,
    kind: DiagramKind,
    positions: tuple[float, ...],
    value_at: Callable[[float], float],
    length: float,
) -> MemberDiagram:
    return MemberDiagram(
        element_tag,
        kind,
        tuple(DiagramPoint(position, value_at(position * length)) for position in positions),
    )
