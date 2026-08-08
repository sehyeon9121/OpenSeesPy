"""DEV / DIAGNOSTIC ONLY -- not one of the project's Phase-listed scripts.

Smoke test: does the geometry/topology generator feed OpenSeesPy correctly?

This is NOT the Phase 2 analysis package (that needs its own file separation
per the project's stated principles: model_builder.py, opensees_adapter.py,
boundary_conditions.py, loads.py, ...). It is NOT a real timber design case.
Every non-geometric input is a placeholder, reused only because it is already
an approved, documented number -- not because it is the target design:

- Material: S235 steel, taken as-is from the approved reference validation
  model (see docs/validation_reference.md).
- Sections: the same three reference CHS tubes (RO219.1x10 / RO101.6x8 /
  RO76.1x4), for the same reason.
- Load: a flat -1 kN placeholder at every non-support node, not a computed
  self-weight/snow/wind load.

Purpose: confirm that (a) every node/member the project's own generator
produces reaches OpenSees without error, (b) node/element counts match on
both sides, (c) the analysis converges, and (d) global equilibrium holds
(sum of reactions balances the applied load).

Run from the project root:

    python scripts/dev_opensees_smoke_test.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openseespy.opensees as ops

from schwedler_dome.core.enums import MemberType
from schwedler_dome.core.geometry import generate_nodes
from schwedler_dome.core.models import DomeParameters
from schwedler_dome.core.sections import circular_hollow_section_properties
from schwedler_dome.core.topology import generate_members

# --------------------------------------------------------------------------- #
# 1. Generate the model with the project's own code (this is what we're checking)
# --------------------------------------------------------------------------- #
parameters = DomeParameters(diameter=50.0, rise=10.0, n_meridians=20, n_meridional_divisions=8)
nodes = generate_nodes(parameters)
section_ids = {
    MemberType.MERIDIAN: "RO219.1x10",
    MemberType.RING: "RO101.6x8",
    MemberType.DIAGONAL: "RO76.1x4",
}
members = generate_members(parameters, nodes, section_ids)
nodes_by_id = {n.id: n for n in nodes}

E = 210.0e9  # placeholder: S235, reused from the reference validation model
NU = 0.30
G = E / (2.0 * (1.0 + NU))
SECTION_PROPS = {
    "RO219.1x10": circular_hollow_section_properties(0.2191, 0.010),
    "RO101.6x8": circular_hollow_section_properties(0.1016, 0.008),
    "RO76.1x4": circular_hollow_section_properties(0.0761, 0.004),
}
PLACEHOLDER_LOAD_Z = -1000.0  # N, arbitrary and uniform -- not a real load case

print(f"python-side: {len(nodes)} nodes, {len(members)} members generated")

# --------------------------------------------------------------------------- #
# 2. Build the OpenSeesPy model from that data, nothing else
# --------------------------------------------------------------------------- #
ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)

for n in nodes:
    ops.node(n.id, n.x, n.y, n.z)
for n in nodes:
    if n.is_support:
        ops.fix(n.id, 1, 1, 1, 1, 1, 1)

transf_cache: dict[tuple[float, float, float], int] = {}


def transform_tag_for(dx_local: np.ndarray) -> int:
    """Pick a vecxz reference vector and return the cached geomTransf tag."""
    global_z = np.array([0.0, 0.0, 1.0])
    ref = np.array([1.0, 0.0, 0.0]) if abs(np.dot(dx_local, global_z)) > 0.99 else global_z
    key = tuple(round(v, 6) for v in ref)
    if key not in transf_cache:
        tag = len(transf_cache) + 1
        ops.geomTransf("Linear", tag, *ref)
        transf_cache[key] = tag
    return transf_cache[key]


for m in members:
    start, end = nodes_by_id[m.start_node], nodes_by_id[m.end_node]
    direction = np.array([end.x - start.x, end.y - start.y, end.z - start.z])
    direction = direction / np.linalg.norm(direction)
    transf_tag = transform_tag_for(direction)
    props = SECTION_PROPS[m.section_id]
    ops.element(
        "elasticBeamColumn",
        m.id,
        m.start_node,
        m.end_node,
        props.area,
        E,
        G,
        props.torsional_constant,
        props.moment_of_inertia_y,
        props.moment_of_inertia_z,
        transf_tag,
    )

print(f"opensees-side: {len(ops.getNodeTags())} nodes, {len(ops.getEleTags())} elements built")

# --------------------------------------------------------------------------- #
# 3. Placeholder load + linear static analysis
# --------------------------------------------------------------------------- #
ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
loaded_node_count = 0
for n in nodes:
    if not n.is_support:
        ops.load(n.id, 0.0, 0.0, PLACEHOLDER_LOAD_Z, 0.0, 0.0, 0.0)
        loaded_node_count += 1

ops.system("BandSPD")
ops.numberer("RCM")
ops.constraints("Plain")
ops.integrator("LoadControl", 1.0)
ops.algorithm("Linear")
ops.analysis("Static")
status = ops.analyze(1)
print(f"analyze() status = {status} (0 = converged)")

# --------------------------------------------------------------------------- #
# 4. Results: max displacement + equilibrium check
# --------------------------------------------------------------------------- #
disp_z = {n.id: ops.nodeDisp(n.id, 3) for n in nodes}
max_node = min(disp_z, key=lambda nid: disp_z[nid])
max_uz = disp_z[max_node]
horiz = {n.id: math.hypot(ops.nodeDisp(n.id, 1), ops.nodeDisp(n.id, 2)) for n in nodes}
max_h_node = max(horiz, key=lambda nid: horiz[nid])

ops.reactions()
reaction_sum_z = sum(ops.nodeReaction(n.id, 3) for n in nodes if n.is_support)
applied_sum_z = PLACEHOLDER_LOAD_Z * loaded_node_count

print()
print(
    f"max vertical displacement   : {max_uz * 1000:.3f} mm  at node {max_node} "
    f"(ring_index={nodes_by_id[max_node].ring_index})"
)
print(f"max horizontal displacement : {horiz[max_h_node] * 1000:.3f} mm  at node {max_h_node}")
print()
print(f"sum of applied Fz  : {applied_sum_z:.1f} N")
print(f"sum of reaction Fz : {reaction_sum_z:.1f} N")
print(f"equilibrium residual (should be ~0): {reaction_sum_z + applied_sum_z:.6f} N")

# --------------------------------------------------------------------------- #
# 5. Deformed-shape plot
# --------------------------------------------------------------------------- #
SCALE = 200.0
fig = plt.figure(figsize=(11, 9))
ax = fig.add_subplot(111, projection="3d")
for m in members:
    a, b = nodes_by_id[m.start_node], nodes_by_id[m.end_node]
    ax.plot([a.x, b.x], [a.y, b.y], [a.z, b.z], color="0.8", linewidth=0.6)
for m in members:
    a, b = nodes_by_id[m.start_node], nodes_by_id[m.end_node]
    ax_, ay, az = (
        a.x + ops.nodeDisp(a.id, 1) * SCALE,
        a.y + ops.nodeDisp(a.id, 2) * SCALE,
        a.z + ops.nodeDisp(a.id, 3) * SCALE,
    )
    bx, by, bz = (
        b.x + ops.nodeDisp(b.id, 1) * SCALE,
        b.y + ops.nodeDisp(b.id, 2) * SCALE,
        b.z + ops.nodeDisp(b.id, 3) * SCALE,
    )
    ax.plot([ax_, bx], [ay, by], [az, bz], color="#dc2626", linewidth=0.8)
ax.set_box_aspect((1, 1, 0.5))
ax.set_title(
    f"OpenSees smoke test -- undeformed (grey) vs deformed x{SCALE:.0f} (red)\n"
    f"max vertical disp = {max_uz * 1000:.2f} mm, placeholder load only"
)
ax.view_init(elev=22, azim=35)
plt.tight_layout()
output_path = PROJECT_ROOT / "results" / "dev_opensees_smoke_test.png"
plt.savefig(output_path, dpi=150)
print()
print(f"saved deformed-shape plot to {output_path}")
