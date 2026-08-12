"""50 m-span Schwedler dome -- functional check that OpenSeesPy is working correctly.

Units are kN and m throughout, matching the other 3D examples in this folder.

Geometry
--------
* Span (plan diameter) 50.0 m, rise 10.0 m -> spherical radius R = 36.25 m,
  computed from R = (half_span^2 + rise^2) / (2 * rise).
* 8 latitude rings between the apex and the support ring, 20 meridians
  (circumferential divisions) -> 161 nodes total (1 apex + 8 x 20 ring nodes).
* Classic Schwedler bracing: meridional members (apex-to-ring1, then
  ring-to-ring), closed ring (hoop) members at every latitude including the
  support ring, and single diagonals per trapezoidal panel with direction
  alternated ring-to-ring so the bracing is not a one-way spiral.
* All members are truss elements (axial-force-only space truss), which is
  how Schwedler domes actually behave and carry load.

Material / sections (recommended for a 50 m-span steel dome)
--------------------------------------------------------------
* Steel S235, E = 210,000,000 kN/m^2, unit weight 77.0 kN/m^3.
* Circular hollow sections (CHS) -- equal stiffness in every direction, the
  standard choice for space-truss members:
    - Meridians (largest axial forces, funnel load down to the supports):
      CHS 219.1x10
    - Rings (hoop tension/compression, smaller than meridional forces):
      CHS 101.6x8
    - Diagonals (bracing/stability, smallest forces):
      CHS 76.1x4

Loads
-----
* Self-weight: computed exactly from each member's section area, length and
  the steel unit weight, then lumped half-and-half to its end nodes.
* A uniform snow load of 0.5 kN/m^2 on the dome's plan projection
  (pi * 25^2 m^2), distributed equally over every free (non-support) node --
  a simplified lumping, not a rigorous tributary-area calculation.

Run from the project root:

    python examples/schwedler_dome_3d.py
"""

from __future__ import annotations

import math

import openseespy.opensees as ops

# -----------------------------------------------------------------------------
# Dome geometry (kN, m)
# -----------------------------------------------------------------------------
SPAN = 50.0
RISE = 10.0
HALF_SPAN = SPAN / 2.0
NUM_RINGS = 8  # latitude rings between the apex and the support ring
NUM_MERIDIANS = 20  # circumferential divisions

SPHERE_RADIUS = (HALF_SPAN**2 + RISE**2) / (2.0 * RISE)
PHI_MAX = math.asin(HALF_SPAN / SPHERE_RADIUS)  # angle from vertical at the support ring
Z_OFFSET = SPHERE_RADIUS - RISE  # so the apex sits at z = RISE and the base ring at z = 0

APEX_TAG = 1


def node_tag(ring: int, seg: int) -> int:
    """Ring 0 is the apex (a single node); rings 1..NUM_RINGS carry NUM_MERIDIANS nodes."""
    if ring == 0:
        return APEX_TAG
    return APEX_TAG + (ring - 1) * NUM_MERIDIANS + (seg % NUM_MERIDIANS) + 1


def ring_node_coords(ring: int, seg: int) -> tuple[float, float, float]:
    phi = PHI_MAX * ring / NUM_RINGS
    theta = 2.0 * math.pi * seg / NUM_MERIDIANS
    x = SPHERE_RADIUS * math.sin(phi) * math.cos(theta)
    y = SPHERE_RADIUS * math.sin(phi) * math.sin(theta)
    z = SPHERE_RADIUS * math.cos(phi) - Z_OFFSET
    return x, y, z


# -----------------------------------------------------------------------------
# Material and CHS section properties
# -----------------------------------------------------------------------------
ELASTIC_MODULUS = 210_000_000.0  # kN/m^2 (210 GPa), S235 steel
STEEL_UNIT_WEIGHT = 77.0  # kN/m^3


def chs_area(outer_diameter_mm: float, thickness_mm: float) -> float:
    """Cross-sectional area of a circular hollow section, returned in m^2."""
    inner_diameter_mm = outer_diameter_mm - 2.0 * thickness_mm
    area_mm2 = math.pi / 4.0 * (outer_diameter_mm**2 - inner_diameter_mm**2)
    return area_mm2 * 1.0e-6


AREA_MERIDIAN = chs_area(219.1, 10.0)  # CHS 219.1x10
AREA_RING = chs_area(101.6, 8.0)  # CHS 101.6x8
AREA_DIAGONAL = chs_area(76.1, 4.0)  # CHS 76.1x4

STEEL_MATERIAL_TAG = 1

# -----------------------------------------------------------------------------
# Build the model
# -----------------------------------------------------------------------------
ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 3)  # space truss: translations only

ops.node(APEX_TAG, 0.0, 0.0, RISE)
for ring in range(1, NUM_RINGS + 1):
    for seg in range(NUM_MERIDIANS):
        ops.node(node_tag(ring, seg), *ring_node_coords(ring, seg))

support_tags: list[int] = []
for seg in range(NUM_MERIDIANS):
    tag = node_tag(NUM_RINGS, seg)
    ops.fix(tag, 1, 1, 1)
    support_tags.append(tag)

ops.uniaxialMaterial("Elastic", STEEL_MATERIAL_TAG, ELASTIC_MODULUS)

node_coords: dict[int, tuple[float, float, float]] = {APEX_TAG: (0.0, 0.0, RISE)}
for ring in range(1, NUM_RINGS + 1):
    for seg in range(NUM_MERIDIANS):
        node_coords[node_tag(ring, seg)] = ring_node_coords(ring, seg)

element_tag = 1
meridian_tags: list[int] = []
ring_tags: list[int] = []
diagonal_tags: list[int] = []
member_ends: dict[int, tuple[int, int]] = {}
member_area: dict[int, float] = {}


def add_truss(i_node: int, j_node: int, area: float, group: list[int]) -> None:
    global element_tag
    ops.element("Truss", element_tag, i_node, j_node, area, STEEL_MATERIAL_TAG)
    group.append(element_tag)
    member_ends[element_tag] = (i_node, j_node)
    member_area[element_tag] = area
    element_tag += 1


# Meridional members: apex -> ring 1, then ring i -> ring i+1
for seg in range(NUM_MERIDIANS):
    add_truss(APEX_TAG, node_tag(1, seg), AREA_MERIDIAN, meridian_tags)
for ring in range(1, NUM_RINGS):
    for seg in range(NUM_MERIDIANS):
        add_truss(node_tag(ring, seg), node_tag(ring + 1, seg), AREA_MERIDIAN, meridian_tags)

# Ring (hoop) members at every latitude, including the support ring
for ring in range(1, NUM_RINGS + 1):
    for seg in range(NUM_MERIDIANS):
        add_truss(node_tag(ring, seg), node_tag(ring, seg + 1), AREA_RING, ring_tags)

# Diagonals: one per trapezoidal panel, direction alternated ring-to-ring
for ring in range(1, NUM_RINGS):
    step = 1 if ring % 2 == 1 else -1
    for seg in range(NUM_MERIDIANS):
        add_truss(
            node_tag(ring, seg),
            node_tag(ring + 1, seg + step),
            AREA_DIAGONAL,
            diagonal_tags,
        )

# -----------------------------------------------------------------------------
# Loads: exact self-weight (lumped) + simplified uniform snow load
# -----------------------------------------------------------------------------
self_weight_fz: dict[int, float] = {tag: 0.0 for tag in node_coords}
for tag, (i_node, j_node) in member_ends.items():
    xi, yi, zi = node_coords[i_node]
    xj, yj, zj = node_coords[j_node]
    length = math.dist((xi, yi, zi), (xj, yj, zj))
    weight = STEEL_UNIT_WEIGHT * member_area[tag] * length
    self_weight_fz[i_node] -= weight / 2.0
    self_weight_fz[j_node] -= weight / 2.0

SNOW_PRESSURE = 0.5  # kN/m^2 on the plan projection
free_nodes = [tag for tag in node_coords if tag not in support_tags]
snow_total = SNOW_PRESSURE * math.pi * HALF_SPAN**2
snow_per_node = snow_total / len(free_nodes)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
total_applied_fz = 0.0
for tag in node_coords:
    fz = self_weight_fz[tag]
    if tag in free_nodes:
        fz -= snow_per_node
    if fz != 0.0:
        ops.load(tag, 0.0, 0.0, fz)
    total_applied_fz += fz

# -----------------------------------------------------------------------------
# Linear static analysis
# -----------------------------------------------------------------------------
ops.system("BandSPD")
ops.numberer("RCM")
ops.constraints("Plain")
ops.integrator("LoadControl", 1.0)
ops.algorithm("Linear")
ops.analysis("Static")
status = ops.analyze(1)

# -----------------------------------------------------------------------------
# Verification output
# -----------------------------------------------------------------------------
print(f"nodes   : {len(ops.getNodeTags())} (python-side {len(node_coords)})")
print(f"elements: {len(ops.getEleTags())} (python-side {len(member_ends)})")
print(f"analyze() status = {status} (0 = converged)")

disp_z = {tag: ops.nodeDisp(tag, 3) for tag in node_coords}
max_node = min(disp_z, key=lambda t: disp_z[t])
print(f"max vertical displacement: {disp_z[max_node] * 1000:.3f} mm at node {max_node}")
print(f"apex vertical displacement: {disp_z[APEX_TAG] * 1000:.3f} mm")

ops.reactions()
reaction_fz = sum(ops.nodeReaction(tag, 3) for tag in support_tags)
print()
print(f"sum applied Fz  : {total_applied_fz:.4f} kN")
print(f"sum reaction Fz : {reaction_fz:.4f} kN")
print(f"equilibrium residual (should be ~0): {reaction_fz + total_applied_fz:.6f} kN")
