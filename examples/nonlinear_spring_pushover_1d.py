"""Single-DOF yielding spring for the nonlinear static (pushover) analysis feature.

Model only: no analysis/analyze commands - RESULTS > "Nonlinear Static" pushes this
past yield in equal load increments and plots base shear vs. node 2's displacement.

Geometry
--------
* Node 1 (fixed) at x=0, node 2 (free) at x=1

Material
--------
* Steel01 bilinear spring: Fy=100, E0=1000 (initial stiffness), b=0.02 (post-yield
  stiffness ratio = 20). A hand check: below Fy the curve should trace slope 1000;
  above it, slope 20.

Load
----
* 150 (well past Fy=100) applied at node 2, split into load-controlled steps by the
  app so the curve traces both the elastic and post-yield branches.
"""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 1, "-ndf", 1)

ops.node(1, 0.0)
ops.node(2, 1.0)
ops.fix(1, 1)

FY = 100.0
E0 = 1000.0
POST_YIELD_RATIO = 0.02
ops.uniaxialMaterial("Steel01", 1, FY, E0, POST_YIELD_RATIO)
ops.element("zeroLength", 1, 1, 2, "-mat", 1, "-dir", 1)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(2, 150.0)
