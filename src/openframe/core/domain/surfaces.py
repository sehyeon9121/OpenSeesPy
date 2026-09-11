"""Shear-wall / slab (surface) members — authoring vs analysis mesh.

``Element`` is a two-node member (``node_i``, ``node_j``). A wall needs four
corners, a thickness and a mesh density; stuffing that into the beam type
would make every beam-only reader lie about connectivity.

``WallPanel`` is what the user authors. ``ShellQuad`` is what the rectangular
mesher derives from it. They are not the same object: regenerating a mesh
must be able to drop every ``ShellQuad`` (and every ``NodeOrigin.WALL_MESH``
node) without touching the panel the user still owns.

Not a surface, and not to be reused as one:

- ``FloorLoadEntry`` is a pressure on a polygon, tributed onto beams
  (``features/model/presentation/floor_tributary.py``).
- ``RigidDiaphragm`` is a kinematic floor constraint, not plate stiffness.

``ElementResult.local_forces`` is beam end forces (6 or 12 numbers). Shell
stresses do not stretch that tuple; they get their own result shape later.
This module stays Qt-free and OpenSees-free.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class WallPanel:
    """A rectangular planar wall the user edits.

    Corner winding is counter-clockwise when looking along the wall normal
    produced by ``(n2-n1) × (n4-n1)``:

    ::

        n4────────n3
        │          │
        │          │
        n1────────n2

    ``n1→n2`` is the wall's local x (width); ``n1→n4`` is local y (height).
    Every derived quad reuses this winding so ASDShellQ4 normals stay
    consistent across the mesh.
    """

    tag: int
    node_1: int
    node_2: int
    node_3: int
    node_4: int
    thickness: float
    nx: int
    ny: int
    elastic_modulus: float
    poisson_ratio: float
    density: float = 0.0
    rc_material: dict[str, float | str] = field(default_factory=dict)

    def corner_tags(self) -> tuple[int, int, int, int]:
        return (self.node_1, self.node_2, self.node_3, self.node_4)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.nx < 1 or self.ny < 1:
            errors.append(f"벽체 {self.tag}의 분할 수 nx, ny는 1 이상이어야 합니다.")
        if self.thickness <= 0.0:
            errors.append(f"벽체 {self.tag}의 두께는 0보다 커야 합니다.")
        if self.elastic_modulus <= 0.0:
            errors.append(f"벽체 {self.tag}의 탄성계수 E는 0보다 커야 합니다.")
        if not -1.0 < self.poisson_ratio < 0.5:
            errors.append(f"벽체 {self.tag}의 포아송비는 -1보다 크고 0.5보다 작아야 합니다.")
        if self.density < 0.0:
            errors.append(f"벽체 {self.tag}의 밀도는 음수일 수 없습니다.")
        if len(set(self.corner_tags())) != 4:
            errors.append(f"벽체 {self.tag}의 네 모서리 절점은 서로 달라야 합니다.")
        return errors


@dataclass(frozen=True, slots=True)
class ShellQuad:
    """One analysis quad derived from a ``WallPanel``.

    ``tag`` is the OpenSees element tag, allocated so it never collides with
    a beam/truss ``Element.tag``. ``wall_tag`` is the parent panel, used to
    drop and rebuild this quad on remesh without scanning geometry.
    """

    tag: int
    node_1: int
    node_2: int
    node_3: int
    node_4: int
    wall_tag: int

    def node_tags(self) -> tuple[int, int, int, int]:
        return (self.node_1, self.node_2, self.node_3, self.node_4)
