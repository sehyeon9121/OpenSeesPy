"""Official OpenSees two-story steel moment-frame pushover benchmark.

This is a model-only OpenSeesPy translation of Laura Eads' 2010 Tcl example,
``Pushover_concentrated.tcl``.  Geometry, section properties, element and node
tags, gravity loads, lateral loads, and Modified Ibarra-Krawinkler hinge
parameters are retained from the official example.  Tcl-only display procedures,
recorders, eigenvalue reporting, and analysis commands are intentionally omitted:
OpenFrame owns the analysis stage after importing this file.

Units
-----
kip, inch, second

Recommended OpenFrame nonlinear-static settings
------------------------------------------------
* Gravity pattern: 101; gravity steps: 10
* Lateral pattern: 200
* Integrator: DisplacementControl
* Control node / DOF: 13 / 1 (roof horizontal displacement)
* Target displacement: 32.4 in (10 percent roof drift)
* Load steps: 3240 (0.01 in nominal increment)
* Constraint handler: Plain (matches the Tcl reference)
* Numberer / system: RCM / BandGeneral
* Test / tolerance / iterations: NormUnbalance / 1.0e-6 / 400
* Algorithm: Newton

Reference
---------
https://opensees.ist.berkeley.edu/wiki/index.php?title=Pushover_Analysis_of_2-Story_Moment_Frame

``Bilin`` is retained rather than replaced with the newer ``IMKBilin`` material
because this file is a numerical-reproduction benchmark.  OpenSees prints a
deprecation warning for Bilin, but changing the constitutive model would no longer
be a direct translation of the published reference.
"""

from __future__ import annotations

import openseespy.opensees as ops

OPENFRAME_UNITS = {"force": "kip", "length": "in", "time": "s"}

# Explicit load categories are read by OpenFrame without executing this mapping.
OPENFRAME_LOAD_CASES = {101: "DEAD", 200: "SEISMIC"}


def _rot_spring_2d_modik(
    element_tag: int,
    retained_node: int,
    constrained_node: int,
    stiffness: float,
    hardening_positive: float,
    hardening_negative: float,
    yield_moment_positive: float,
    yield_moment_negative: float,
    lambda_strength: float,
    lambda_unloading: float,
    lambda_accelerated: float,
    lambda_post_capping: float,
    exponent_strength: float,
    exponent_unloading: float,
    exponent_accelerated: float,
    exponent_post_capping: float,
    plastic_rotation_positive: float,
    plastic_rotation_negative: float,
    post_capping_rotation_positive: float,
    post_capping_rotation_negative: float,
    residual_ratio_positive: float,
    residual_ratio_negative: float,
    ultimate_rotation_positive: float,
    ultimate_rotation_negative: float,
    deterioration_rate_positive: float,
    deterioration_rate_negative: float,
) -> None:
    """Python equivalent of the official rotSpring2DModIKModel.tcl procedure."""
    ops.uniaxialMaterial(
        "Bilin",
        element_tag,
        stiffness,
        hardening_positive,
        hardening_negative,
        yield_moment_positive,
        yield_moment_negative,
        lambda_strength,
        lambda_unloading,
        lambda_accelerated,
        lambda_post_capping,
        exponent_strength,
        exponent_unloading,
        exponent_accelerated,
        exponent_post_capping,
        plastic_rotation_positive,
        plastic_rotation_negative,
        post_capping_rotation_positive,
        post_capping_rotation_negative,
        residual_ratio_positive,
        residual_ratio_negative,
        ultimate_rotation_positive,
        ultimate_rotation_negative,
        deterioration_rate_positive,
        deterioration_rate_negative,
    )
    # OpenSees zeroLength directions use 6 for rotation about global Z.
    ops.element(
        "zeroLength",
        element_tag,
        retained_node,
        constrained_node,
        "-mat",
        element_tag,
        "-dir",
        6,
    )
    ops.equalDOF(retained_node, constrained_node, 1, 2)


def _rot_leaning_column(
    element_tag: int, retained_node: int, constrained_node: int
) -> None:
    """Python equivalent of rotLeaningCol.tcl's near-zero rotational spring."""
    ops.uniaxialMaterial("Elastic", element_tag, 1.0e-9)
    ops.element(
        "zeroLength",
        element_tag,
        retained_node,
        constrained_node,
        "-mat",
        element_tag,
        "-dir",
        6,
    )
    ops.equalDOF(retained_node, constrained_node, 1, 2)


def _modified_hardening_ratio(
    n: float,
    yield_moment: float,
    capping_to_yield_ratio: float,
    spring_stiffness: float,
    plastic_rotation: float,
) -> float:
    member_ratio = (
        (n + 1.0)
        * yield_moment
        * (capping_to_yield_ratio - 1.0)
        / (spring_stiffness * plastic_rotation)
    )
    return member_ratio / (1.0 + n * (1.0 - member_ratio))


ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

# Building geometry.
N_STORIES = 2
W_BAY = 30.0 * 12.0
H_STORY_1 = 15.0 * 12.0
H_STORY_TYPICAL = 12.0 * 12.0
H_BUILDING = H_STORY_1 + (N_STORIES - 1) * H_STORY_TYPICAL

PIER_1 = 0.0
PIER_2 = PIER_1 + W_BAY
PIER_3 = PIER_2 + W_BAY
FLOOR_1 = 0.0
FLOOR_2 = FLOOR_1 + H_STORY_1
FLOOR_3 = FLOOR_2 + H_STORY_TYPICAL
PLASTIC_HINGE_OFFSET = 0.0

# Lumped floor masses from the reference model.
GRAVITY_ACCELERATION = 386.2
FLOOR_2_WEIGHT = 535.0
FLOOR_3_WEIGHT = 525.0
NODAL_MASS_2 = (FLOOR_2_WEIGHT / GRAVITY_ACCELERATION) / 2.0
NODAL_MASS_3 = (FLOOR_3_WEIGHT / GRAVITY_ACCELERATION) / 2.0
NEGLIGIBLE_MASS = 1.0e-9

# Beam-column joints and leaning-column nodes.
ops.node(11, PIER_1, FLOOR_1)
ops.node(21, PIER_2, FLOOR_1)
ops.node(31, PIER_3, FLOOR_1)
ops.node(12, PIER_1, FLOOR_2, "-mass", NODAL_MASS_2, NEGLIGIBLE_MASS, NEGLIGIBLE_MASS)
ops.node(22, PIER_2, FLOOR_2, "-mass", NODAL_MASS_2, NEGLIGIBLE_MASS, NEGLIGIBLE_MASS)
ops.node(32, PIER_3, FLOOR_2)
ops.node(13, PIER_1, FLOOR_3, "-mass", NODAL_MASS_3, NEGLIGIBLE_MASS, NEGLIGIBLE_MASS)
ops.node(23, PIER_2, FLOOR_3, "-mass", NODAL_MASS_3, NEGLIGIBLE_MASS, NEGLIGIBLE_MASS)
ops.node(33, PIER_3, FLOOR_3)

# Additional coincident nodes for concentrated rotational springs.
for node_tag, x, y in (
    (117, PIER_1, FLOOR_1),
    (217, PIER_2, FLOOR_1),
    (126, PIER_1, FLOOR_2),
    (226, PIER_2, FLOOR_2),
    (326, PIER_3, FLOOR_2),
    (127, PIER_1, FLOOR_2),
    (227, PIER_2, FLOOR_2),
    (327, PIER_3, FLOOR_2),
    (136, PIER_1, FLOOR_3),
    (236, PIER_2, FLOOR_3),
    (336, PIER_3, FLOOR_3),
    (122, PIER_1 + PLASTIC_HINGE_OFFSET, FLOOR_2),
    (223, PIER_2 - PLASTIC_HINGE_OFFSET, FLOOR_2),
    (132, PIER_1 + PLASTIC_HINGE_OFFSET, FLOOR_3),
    (233, PIER_2 - PLASTIC_HINGE_OFFSET, FLOOR_3),
):
    ops.node(node_tag, x, y)

# Rigid-diaphragm horizontal constraints and supports.
ops.equalDOF(12, 22, 1)
ops.equalDOF(12, 32, 1)
ops.equalDOF(13, 23, 1)
ops.equalDOF(13, 33, 1)
ops.fix(11, 1, 1, 1)
ops.fix(21, 1, 1, 1)
ops.fix(31, 1, 1, 0)

# Steel and member properties from the Tcl benchmark.
STEEL_E = 29_000.0
COLUMN_AREA = 38.5  # W24x131
COLUMN_INERTIA = 4_020.0
COLUMN_YIELD_MOMENT = 20_350.0
BEAM_AREA = 30.0  # W27x102
BEAM_INERTIA = 3_620.0
BEAM_YIELD_MOMENT = 10_938.0
STIFFNESS_MULTIPLIER = 10.0

COLUMN_INERTIA_MODIFIED = COLUMN_INERTIA * (
    STIFFNESS_MULTIPLIER + 1.0
) / STIFFNESS_MULTIPLIER
BEAM_INERTIA_MODIFIED = BEAM_INERTIA * (
    STIFFNESS_MULTIPLIER + 1.0
) / STIFFNESS_MULTIPLIER
COLUMN_SPRING_STIFFNESS_1 = (
    STIFFNESS_MULTIPLIER
    * 6.0
    * STEEL_E
    * COLUMN_INERTIA_MODIFIED
    / H_STORY_1
)
COLUMN_SPRING_STIFFNESS_2 = (
    STIFFNESS_MULTIPLIER
    * 6.0
    * STEEL_E
    * COLUMN_INERTIA_MODIFIED
    / H_STORY_TYPICAL
)
BEAM_SPRING_STIFFNESS = (
    STIFFNESS_MULTIPLIER * 6.0 * STEEL_E * BEAM_INERTIA_MODIFIED / W_BAY
)

PDELTA_TRANSFORMATION = 1
ops.geomTransf("PDelta", PDELTA_TRANSFORMATION)

# Elastic frame members between the concentrated hinges.
for element_tag, node_i, node_j in (
    (111, 117, 126),
    (121, 217, 226),
    (112, 127, 136),
    (122, 227, 236),
):
    ops.element(
        "elasticBeamColumn",
        element_tag,
        node_i,
        node_j,
        COLUMN_AREA,
        STEEL_E,
        COLUMN_INERTIA_MODIFIED,
        PDELTA_TRANSFORMATION,
    )

for element_tag, node_i, node_j in ((212, 122, 223), (222, 132, 233)):
    ops.element(
        "elasticBeamColumn",
        element_tag,
        node_i,
        node_j,
        BEAM_AREA,
        STEEL_E,
        BEAM_INERTIA_MODIFIED,
        PDELTA_TRANSFORMATION,
    )

# Leaning column and axially rigid truss links used for the P-Delta effect.
TRUSS_MATERIAL = 600
RIGID_AREA = 1_000.0
RIGID_INERTIA = 100_000.0
ops.uniaxialMaterial("Elastic", TRUSS_MATERIAL, STEEL_E)
ops.element("truss", 622, 22, 32, RIGID_AREA, TRUSS_MATERIAL)
ops.element("truss", 623, 23, 33, RIGID_AREA, TRUSS_MATERIAL)
ops.element(
    "elasticBeamColumn",
    731,
    31,
    326,
    RIGID_AREA,
    STEEL_E,
    RIGID_INERTIA,
    PDELTA_TRANSFORMATION,
)
ops.element(
    "elasticBeamColumn",
    732,
    327,
    336,
    RIGID_AREA,
    STEEL_E,
    RIGID_INERTIA,
    PDELTA_TRANSFORMATION,
)

# Modified Ibarra-Krawinkler spring parameters.  Cyclic deterioration is disabled
# in the official monotonic benchmark by assigning very large lambda values.
CAPPING_TO_YIELD_RATIO = 1.05
LAMBDA_STRENGTH = 1_000.0
LAMBDA_UNLOADING = 1_000.0
LAMBDA_ACCELERATED = 1_000.0
LAMBDA_POST_CAPPING = 1_000.0
EXPONENT_STRENGTH = 1.0
EXPONENT_UNLOADING = 1.0
EXPONENT_ACCELERATED = 1.0
EXPONENT_POST_CAPPING = 1.0
COLUMN_PLASTIC_ROTATION = 0.025
COLUMN_POST_CAPPING_ROTATION = 0.3
RESIDUAL_RATIO = 0.4
ULTIMATE_ROTATION = 0.4
DETERIORATION_RATE = 1.0


def _add_symmetric_modik_spring(
    element_tag: int,
    retained_node: int,
    constrained_node: int,
    stiffness: float,
    hardening_ratio: float,
    yield_moment: float,
    plastic_rotation: float,
    post_capping_rotation: float,
) -> None:
    _rot_spring_2d_modik(
        element_tag,
        retained_node,
        constrained_node,
        stiffness,
        hardening_ratio,
        hardening_ratio,
        yield_moment,
        -yield_moment,
        LAMBDA_STRENGTH,
        LAMBDA_UNLOADING,
        LAMBDA_ACCELERATED,
        LAMBDA_POST_CAPPING,
        EXPONENT_STRENGTH,
        EXPONENT_UNLOADING,
        EXPONENT_ACCELERATED,
        EXPONENT_POST_CAPPING,
        plastic_rotation,
        plastic_rotation,
        post_capping_rotation,
        post_capping_rotation,
        RESIDUAL_RATIO,
        RESIDUAL_RATIO,
        ULTIMATE_ROTATION,
        ULTIMATE_ROTATION,
        DETERIORATION_RATE,
        DETERIORATION_RATE,
    )


COLUMN_HARDENING_1 = _modified_hardening_ratio(
    STIFFNESS_MULTIPLIER,
    COLUMN_YIELD_MOMENT,
    CAPPING_TO_YIELD_RATIO,
    COLUMN_SPRING_STIFFNESS_1,
    COLUMN_PLASTIC_ROTATION,
)
for element_tag, retained_node, constrained_node in (
    (3111, 11, 117),
    (3211, 21, 217),
    (3112, 12, 126),
    (3212, 22, 226),
):
    _add_symmetric_modik_spring(
        element_tag,
        retained_node,
        constrained_node,
        COLUMN_SPRING_STIFFNESS_1,
        COLUMN_HARDENING_1,
        COLUMN_YIELD_MOMENT,
        COLUMN_PLASTIC_ROTATION,
        COLUMN_POST_CAPPING_ROTATION,
    )

COLUMN_HARDENING_2 = _modified_hardening_ratio(
    STIFFNESS_MULTIPLIER,
    COLUMN_YIELD_MOMENT,
    CAPPING_TO_YIELD_RATIO,
    COLUMN_SPRING_STIFFNESS_2,
    COLUMN_PLASTIC_ROTATION,
)
for element_tag, retained_node, constrained_node in (
    (3121, 12, 127),
    (3221, 22, 227),
    (3122, 13, 136),
    (3222, 23, 236),
):
    _add_symmetric_modik_spring(
        element_tag,
        retained_node,
        constrained_node,
        COLUMN_SPRING_STIFFNESS_2,
        COLUMN_HARDENING_2,
        COLUMN_YIELD_MOMENT,
        COLUMN_PLASTIC_ROTATION,
        COLUMN_POST_CAPPING_ROTATION,
    )

BEAM_PLASTIC_ROTATION = 0.02
BEAM_POST_CAPPING_ROTATION = 0.16
BEAM_HARDENING = _modified_hardening_ratio(
    STIFFNESS_MULTIPLIER,
    BEAM_YIELD_MOMENT,
    CAPPING_TO_YIELD_RATIO,
    BEAM_SPRING_STIFFNESS,
    BEAM_PLASTIC_ROTATION,
)
for element_tag, retained_node, constrained_node in (
    (4121, 12, 122),
    (4122, 22, 223),
    (4131, 13, 132),
    (4132, 23, 233),
):
    _add_symmetric_modik_spring(
        element_tag,
        retained_node,
        constrained_node,
        BEAM_SPRING_STIFFNESS,
        BEAM_HARDENING,
        BEAM_YIELD_MOMENT,
        BEAM_PLASTIC_ROTATION,
        BEAM_POST_CAPPING_ROTATION,
    )

_rot_leaning_column(5312, 32, 326)
_rot_leaning_column(5321, 32, 327)
_rot_leaning_column(5322, 33, 336)

# Pattern 101: reference gravity load distribution.
ops.timeSeries("Constant", 101)
ops.pattern("Plain", 101, 101)
LEANING_LOAD_2 = -398.02
LEANING_LOAD_3 = -391.31
FRAME_LOAD_2 = 0.5 * (-FLOOR_2_WEIGHT - LEANING_LOAD_2)
FRAME_LOAD_3 = 0.5 * (-FLOOR_3_WEIGHT - LEANING_LOAD_3)
ops.load(32, 0.0, LEANING_LOAD_2, 0.0)
ops.load(33, 0.0, LEANING_LOAD_3, 0.0)
ops.load(12, 0.0, FRAME_LOAD_2, 0.0)
ops.load(22, 0.0, FRAME_LOAD_2, 0.0)
ops.load(13, 0.0, FRAME_LOAD_3, 0.0)
ops.load(23, 0.0, FRAME_LOAD_3, 0.0)

# Pattern 200: ASCE 7-10 lateral distribution from the reference model.
ops.timeSeries("Linear", 200)
ops.pattern("Plain", 200, 200)
LATERAL_LOAD_2 = 16.255
LATERAL_LOAD_3 = 31.636
ops.load(12, LATERAL_LOAD_2, 0.0, 0.0)
ops.load(22, LATERAL_LOAD_2, 0.0, 0.0)
ops.load(13, LATERAL_LOAD_3, 0.0, 0.0)
ops.load(23, LATERAL_LOAD_3, 0.0, 0.0)
