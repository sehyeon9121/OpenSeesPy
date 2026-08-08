"""Three-truss hardening-material pushover, from the OpenSeesPy docs' nonlinearTruss
example (https://openseespydoc.readthedocs.io/en/latest/src/nonlinearTruss.html).

Model only: no analyze()/plotting - RESULTS > "Nonlinear Static" pushes node 4 in
equal load increments and plots base shear vs. its horizontal displacement.

Note this model declares ndf=2 (translation only, no rotational DOF - typical for a
pure truss), unlike the 2D frame examples elsewhere in this folder that use ndf=3.

Geometry
--------
* Nodes 1-3 (all fixed) on the ground line, node 4 (free) above them at (48, 144).
* Three truss members connect each fixed node to node 4.

Material
--------
* Hardening: E=29000, yield stress sY=36, isotropic hardening modulus 0 (kinematic
  only), kinematic hardening modulus = alpha/(1-alpha)*E with alpha=0.05.

Load
----
* Px=160 applied at node 4 in the horizontal (UX) direction, split into load-
  controlled steps by the app.
"""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 2)

A = 4.0
E = 29000.0
ALPHA = 0.05
SY = 36.0
PX = 160.0
PY = 0.0

ops.node(1, 0.0, 0.0)
ops.node(2, 72.0, 0.0)
ops.node(3, 168.0, 0.0)
ops.node(4, 48.0, 144.0)

ops.fix(1, 1, 1)
ops.fix(2, 1, 1)
ops.fix(3, 1, 1)

ops.uniaxialMaterial("Hardening", 1, E, SY, 0.0, ALPHA / (1 - ALPHA) * E)

ops.element("Truss", 1, 1, 4, A, 1)
ops.element("Truss", 2, 2, 4, A, 1)
ops.element("Truss", 3, 3, 4, A, 1)

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.load(4, PX, PY)
