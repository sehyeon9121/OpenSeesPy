"""Determinate 2D portal frame matching the supplied problem.

Units are kN and m.  The load locations D and C are real nodes so the AFD,
SFD, and BMD change at the same locations as the reference solution::

    E(3) -------- C(4) -------- F(5)
     |              | 80 kN ↓     |
     |→ 35 kN       |              |
    D(2)                           |
     |                             |
    A(1)                          B(6)

A is modeled as a pin and B as a vertical roller.  Only the two blue applied
loads are defined below; the red arrows in the problem image are reactions
that should be obtained by running the analysis, not additional nodal loads.
"""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

node_a = 1
node_d = 2
node_e = 3
node_c = 4
node_f = 5
node_b = 6

ops.node(node_a, 0.0, 0.0)
ops.node(node_d, 0.0, 2.0)
ops.node(node_e, 0.0, 4.0)
ops.node(node_c, 3.5, 4.0)
ops.node(node_f, 7.0, 4.0)
ops.node(node_b, 7.0, 0.0)

ops.fix(node_a, 1, 1, 0)  # A: pin
ops.fix(node_b, 0, 1, 0)  # B: vertical roller

area = 0.02
elastic_modulus = 200_000_000.0
moment_of_inertia = 8.0e-5
ops.geomTransf("Linear", 1)
ops.element(
    "elasticBeamColumn", 1, node_a, node_d, area, elastic_modulus, moment_of_inertia, 1
)
ops.element(
    "elasticBeamColumn", 2, node_d, node_e, area, elastic_modulus, moment_of_inertia, 1
)
ops.element(
    "elasticBeamColumn", 3, node_e, node_c, area, elastic_modulus, moment_of_inertia, 1
)
ops.element(
    "elasticBeamColumn", 4, node_c, node_f, area, elastic_modulus, moment_of_inertia, 1
)
# Members follow the order the frame is traversed by hand (A up, across, then down to B).
# A member's i->j direction sets its local axes, and therefore which side its A.F.D and
# S.F.D are plotted on, so traversing this way reproduces the reference figure: compression
# is drawn inside the frame on both columns.
ops.element(
    "elasticBeamColumn", 5, node_f, node_b, area, elastic_modulus, moment_of_inertia, 1
)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(node_d, 35.0, 0.0, 0.0)
ops.load(node_c, 0.0, -80.0, 0.0)
