"""Small 3D nonlinear cantilever for OpenFrame Studio verification.

Units are kN and m.  The model has six DOFs per node, a 3D P-Delta
transformation, gravity loading, and independent bilinear base hinges about the
global X and Y axes.  It is intentionally small enough that the pushover curve
can be checked quickly before moving on to a full 3D building.
"""

import openseespy.opensees as ops

OPENFRAME_UNITS = {"force": "kN", "length": "m", "time": "s"}

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)

# Node 1 is the fixed foundation.  Node 10 is coincident with it so the two
# rotational springs can sit between the foundation and the elastic column.
ops.node(1, 0.0, 0.0, 0.0)
ops.node(10, 0.0, 0.0, 0.0)
ops.node(20, 0.0, 0.0, 3.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)

# Tie translations and rotation about the vertical member axis.  Rotations RX
# and RY remain connected by the nonlinear zeroLength element below.
ops.equalDOF(1, 10, 1, 2, 3, 6)

# Bilinear moment-rotation hinges: My=120 kN-m, K0=40,000 kN-m/rad,
# post-yield stiffness ratio b=0.02.  Directions 4 and 5 are RX and RY.
ops.uniaxialMaterial("Steel01", 101, 120.0, 40_000.0, 0.02)
ops.uniaxialMaterial("Steel01", 102, 120.0, 40_000.0, 0.02)
ops.element("zeroLength", 101, 1, 10, "-mat", 101, 102, "-dir", 4, 5)

# Elastic 3D column.  The nonlinear response is concentrated in the two base
# springs; the PDelta transformation includes second-order geometric effects.
area = 0.02
elastic_modulus = 200_000_000.0
shear_modulus = 76_900_000.0
torsional_constant = 1.6e-4
inertia_y = 8.0e-5
inertia_z = 8.0e-5
ops.geomTransf("PDelta", 1, 0.0, 1.0, 0.0)
ops.element(
    "elasticBeamColumn",
    201,
    10,
    20,
    area,
    elastic_modulus,
    shear_modulus,
    torsional_constant,
    inertia_y,
    inertia_z,
    1,
)

# Pattern 101: gravity, to be applied first and then held constant.
ops.timeSeries("Linear", 101)
ops.pattern("Plain", 101, 101)
ops.load(20, 0.0, 0.0, -500.0, 0.0, 0.0, 0.0)

# Pattern 201: simultaneous diagonal X/Y lateral push.  UX at node 20 is the
# suggested control response; UY is solved concurrently, exercising and yielding
# both 3D bending hinges.
ops.timeSeries("Linear", 201)
ops.pattern("Plain", 201, 201)
ops.load(20, 100.0, 100.0, 0.0, 0.0, 0.0, 0.0)
