"""Minimal 3D elastic cantilever for import, projection and solver checks."""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)

ops.node(1, 0.0, 0.0, 0.0)
ops.node(2, 0.0, 0.0, 3.0)
ops.fix(1, 1, 1, 1, 1, 1, 1)

area = 0.02
elastic_modulus = 200_000_000.0
shear_modulus = 76_900_000.0
torsional_constant = 1.6e-4
inertia_y = 8.0e-5
inertia_z = 8.0e-5

# The local x-axis follows the member; this vector fixes the local x-z plane.
ops.geomTransf("Linear", 1, 0.0, 1.0, 0.0)
ops.element(
    "elasticBeamColumn",
    1,
    1,
    2,
    area,
    elastic_modulus,
    shear_modulus,
    torsional_constant,
    inertia_y,
    inertia_z,
    1,
)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(2, 10.0, -5.0, -20.0, 0.0, 0.0, 0.0)
