"""Support-symbol gallery for fixed, pinned and roller boundary conditions."""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

for tag, x in enumerate((0.0, 3.0, 6.0, 9.0), start=1):
    ops.node(tag, x, 0.0)

ops.fix(1, 1, 1, 1)  # Fixed support
ops.fix(2, 1, 1, 0)  # Pinned support: rotation is free
ops.fix(3, 0, 1, 0)  # Vertical roller: horizontal movement is free
ops.fix(4, 1, 0, 0)  # Horizontal roller: vertical movement is free

ops.geomTransf("Linear", 1)
for element_tag, node_i, node_j in ((1, 1, 2), (2, 2, 3), (3, 3, 4)):
    ops.element(
        "elasticBeamColumn",
        element_tag,
        node_i,
        node_j,
        0.02,
        200_000_000.0,
        8.0e-5,
        1,
    )

