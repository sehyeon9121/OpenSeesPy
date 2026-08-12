"""OpenSeesPy model converted from ``라스트 모델.mgt``.

This file builds the model and load patterns only.  It intentionally contains no
``ops.analysis`` or ``ops.analyze`` command so that it can be imported by
OpenFrame and analysed with the application's settings.

Source-model basis
------------------
* MIDAS unit system: N, mm, s
* 41 nodes and 60 MIDAS elements
* Four dummy plate elements are replaced by in-plane rigid diaphragms
* 56 line elements remain: 44 beams/columns and 12 trusses
* Four 6 kg floor/roof masses (24 kg total)
* MIDAS elements 53--56 are the four vertical upper-belt members.  The MGT file
  assigns ordinary elastic MDF to them; it does not contain a nonlinear damper
  law.  They are therefore retained as elastic baseline members here and marked
  in ``DAMPER_CANDIDATE_ELEMENTS`` for a later calibrated replacement.

The gravity pattern and reference pushover pattern were not present as explicit
static loads in the MGT file.  They are added here for nonlinear-static use and
kept in separate patterns so the OpenFrame settings can distinguish them.
"""

import openseespy.opensees as ops

# OpenFrame reads this declaration and changes the imported-model display units.
OPENFRAME_UNITS = {"force": "N", "length": "mm", "time": "s"}


# -----------------------------------------------------------------------------
# User-editable analysis preparation
# -----------------------------------------------------------------------------

# False reproduces the MGT time-history case setting (P-Delta = NO).
# Change to True only when geometric nonlinearity is intentionally required.
USE_PDELTA = False

# The MGT has no explicit static gravity or pushover load records.  These two
# switches control the added OpenSees-only patterns described below.
INCLUDE_GRAVITY_PATTERN = True
INCLUDE_REFERENCE_PUSHOVER_PATTERN = True

# The reference pushover vector is an equal-mass, height-proportional X pattern.
# Its total is 1 N; displacement control will scale its load factor.
PUSHOVER_DIRECTION = "X"


# -----------------------------------------------------------------------------
# Geometry copied from *NODE (mm)
# -----------------------------------------------------------------------------

NODES = {
    1: (0.0, 0.0, 0.0),
    2: (150.0, 0.0, 0.0),
    3: (0.0, 150.0, 0.0),
    4: (150.0, 150.0, 0.0),
    5: (0.0, 0.0, 200.0),
    6: (150.0, 0.0, 200.0),
    7: (0.0, 150.0, 200.0),
    8: (150.0, 150.0, 200.0),
    9: (0.0, 0.0, 400.0),
    10: (150.0, 0.0, 400.0),
    11: (0.0, 150.0, 400.0),
    12: (150.0, 150.0, 400.0),
    13: (0.0, 0.0, 600.0),
    14: (150.0, 0.0, 600.0),
    15: (0.0, 150.0, 600.0),
    16: (150.0, 150.0, 600.0),
    17: (0.0, 0.0, 800.0),
    18: (150.0, 0.0, 800.0),
    19: (0.0, 150.0, 800.0),
    20: (150.0, 150.0, 800.0),
    21: (0.0, 0.0, 594.0),
    22: (150.0, 0.0, 594.0),
    23: (0.0, 150.0, 594.0),
    24: (150.0, 150.0, 594.0),
    25: (0.0, 0.0, 544.0),
    26: (150.0, 0.0, 544.0),
    27: (0.0, 150.0, 544.0),
    28: (150.0, 150.0, 544.0),
    29: (75.0, 75.0, 0.0),
    30: (75.0, 75.0, 200.0),
    31: (75.0, 75.0, 400.0),
    32: (75.0, 75.0, 600.0),
    33: (75.0, 75.0, 800.0),
    34: (0.0, 75.0, 594.0),
    35: (0.0, 75.0, 544.0),
    36: (75.0, 0.0, 594.0),
    37: (75.0, 0.0, 544.0),
    38: (150.0, 75.0, 594.0),
    39: (150.0, 75.0, 544.0),
    40: (75.0, 150.0, 594.0),
    41: (75.0, 150.0, 544.0),
}


# -----------------------------------------------------------------------------
# Material and section properties (N, mm)
# -----------------------------------------------------------------------------

E_MDF = 638.0
POISSON_RATIO = 0.30
G_MDF = E_MDF / (2.0 * (1.0 + POISSON_RATIO))

# A [mm2], J/Iy/Iz [mm4].  Values follow the MIDAS DB/User shapes and the
# existing MIDAS-match reference in examples/mdf_hs_clean.
SECTIONS = {
    1: {"name": "1F", "A": 192.0, "J": 6533.3, "Iy": 6304.0, "Iz": 3936.0},
    2: {"name": "2F", "A": 144.0, "J": 2916.0, "Iy": 1728.0, "Iz": 1728.0},
    3: {"name": "3F", "A": 120.0, "J": 1984.0, "Iy": 1440.0, "Iz": 1000.0},
    4: {"name": "4F", "A": 48.0, "J": 311.0, "Iy": 144.0, "Iz": 256.0},
    5: {"name": "BEAM", "A": 24.0, "J": 75.1, "Iy": 32.0, "Iz": 72.0},
    6: {"name": "CORE", "A": 280.0, "J": 23328.0, "Iy": 16320.0, "Iz": 16320.0},
}


# (element tag, i-node, j-node, section tag), copied from MIDAS BEAM records.
VERTICAL_BEAMS = [
    (1, 5, 1, 1),
    (2, 6, 2, 1),
    (3, 7, 3, 1),
    (4, 8, 4, 1),
    (5, 10, 6, 2),
    (6, 12, 8, 2),
    (7, 11, 7, 2),
    (8, 9, 5, 2),
    (9, 16, 24, 3),
    (10, 14, 22, 3),
    (11, 13, 21, 3),
    (12, 15, 23, 3),
    (13, 18, 14, 4),
    (14, 17, 13, 4),
    (15, 20, 16, 4),
    (16, 19, 15, 4),
    (21, 33, 32, 6),
    (22, 32, 31, 6),
    (23, 31, 30, 6),
    (24, 30, 29, 6),
    (26, 23, 27, 3),
    (27, 21, 25, 3),
    (29, 27, 11, 3),
    (30, 25, 9, 3),
    (32, 22, 26, 3),
    (34, 26, 10, 3),
    (36, 24, 28, 3),
    (38, 28, 12, 3),
]

HORIZONTAL_BEAMS = [
    (65, 24, 40, 5),
    (66, 40, 23, 5),
    (67, 28, 41, 5),
    (68, 41, 27, 5),
    (69, 23, 34, 5),
    (70, 34, 21, 5),
    (71, 27, 35, 5),
    (72, 35, 25, 5),
    (73, 21, 36, 5),
    (74, 36, 22, 5),
    (75, 25, 37, 5),
    (76, 37, 26, 5),
    (77, 22, 38, 5),
    (78, 38, 24, 5),
    (79, 26, 39, 5),
    (80, 39, 28, 5),
]

# (element tag, i-node, j-node, section tag), copied from MIDAS TRUSS records.
TRUSSES = [
    (53, 34, 35, 5),
    (54, 38, 39, 5),
    (55, 36, 37, 5),
    (56, 40, 41, 5),
    (57, 23, 35, 5),
    (58, 21, 35, 5),
    (59, 21, 37, 5),
    (60, 22, 37, 5),
    (61, 22, 39, 5),
    (62, 24, 39, 5),
    (63, 24, 41, 5),
    (64, 23, 41, 5),
]

# Inferred physical damper locations.  The MGT itself does not label them as
# dampers and supplies no C, alpha, Fy, K0, or hysteresis parameters.
DAMPER_CANDIDATE_ELEMENTS = (53, 54, 55, 56)


# -----------------------------------------------------------------------------
# Build model -- no analysis commands below
# -----------------------------------------------------------------------------

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)

for node_tag, coordinates in NODES.items():
    ops.node(node_tag, *coordinates)

# MIDAS *CONSTRAINT: base/cored base fixed, floor centre nodes UZ fixed.
for node_tag in (1, 2, 3, 4, 29):
    ops.fix(node_tag, 1, 1, 1, 1, 1, 1)
for node_tag in (30, 31, 32, 33):
    ops.fix(node_tag, 0, 0, 1, 0, 0, 0)

transformation = "PDelta" if USE_PDELTA else "Linear"
ops.geomTransf(transformation, 1, 1.0, 0.0, 0.0)  # vertical members
ops.geomTransf(transformation, 2, 0.0, 0.0, 1.0)  # horizontal members

for element_tag, node_i, node_j, section_tag in VERTICAL_BEAMS:
    section = SECTIONS[section_tag]
    ops.element(
        "elasticBeamColumn",
        element_tag,
        node_i,
        node_j,
        section["A"],
        E_MDF,
        G_MDF,
        section["J"],
        section["Iy"],
        section["Iz"],
        1,
    )

for element_tag, node_i, node_j, section_tag in HORIZONTAL_BEAMS:
    section = SECTIONS[section_tag]
    ops.element(
        "elasticBeamColumn",
        element_tag,
        node_i,
        node_j,
        section["A"],
        E_MDF,
        G_MDF,
        section["J"],
        section["Iy"],
        section["Iz"],
        2,
    )

ops.uniaxialMaterial("Elastic", 1, E_MDF)
for element_tag, node_i, node_j, section_tag in TRUSSES:
    ops.element("Truss", element_tag, node_i, node_j, SECTIONS[section_tag]["A"], 1)

# MIDAS dummy plates 17--20 are omitted.  Story diaphragm=YES is reproduced at
# z=200, 400, 600, 800.  perpDirn=3 ties only UX, UY and RZ in the XY plane.
DIAPHRAGMS = {
    30: (5, 6, 7, 8),
    31: (9, 10, 11, 12),
    32: (13, 14, 15, 16),
    33: (17, 18, 19, 20),
}
for master_node, retained_nodes in DIAPHRAGMS.items():
    ops.rigidDiaphragm(3, master_node, *retained_nodes)

# In N-mm-s, 6 kg = 0.006 N*s2/mm.  MIDAS stores 58.84 in *NODALMASS because
# that text value is the 6 kg force-equivalent under its N-based unit system.
FLOOR_MASS_KG = 6.0
FLOOR_MASS_CONSISTENT = FLOOR_MASS_KG / 1000.0
FLOOR_MASTER_NODES = (30, 31, 32, 33)
for master_node in FLOOR_MASTER_NODES:
    ops.mass(master_node, FLOOR_MASS_CONSISTENT, FLOOR_MASS_CONSISTENT, 0.0, 0.0, 0.0, 0.0)

# OpenSees-only gravity pattern.  Each 6 kg floor/roof weight is distributed to
# its four corner nodes because a rigidDiaphragm does not tie vertical UZ.
GRAVITY_ACCELERATION_M_S2 = 9.806
FLOOR_WEIGHT_N = FLOOR_MASS_KG * GRAVITY_ACCELERATION_M_S2
GRAVITY_TIME_SERIES = 101
GRAVITY_PATTERN = 101
FLOOR_CORNERS = (
    (5, 6, 7, 8),
    (9, 10, 11, 12),
    (13, 14, 15, 16),
    (17, 18, 19, 20),
)
if INCLUDE_GRAVITY_PATTERN:
    ops.timeSeries("Constant", GRAVITY_TIME_SERIES)
    ops.pattern("Plain", GRAVITY_PATTERN, GRAVITY_TIME_SERIES)
    corner_weight = -FLOOR_WEIGHT_N / 4.0
    for floor_nodes in FLOOR_CORNERS:
        for node_tag in floor_nodes:
            ops.load(node_tag, 0.0, 0.0, corner_weight, 0.0, 0.0, 0.0)

# OpenSees-only reference lateral pattern: Fi is proportional to floor height.
# The vector [0.1, 0.2, 0.3, 0.4] has a 1 N total and is intentionally separate
# from gravity.  It is a load shape, not a claimed MIDAS static load case.
PUSHOVER_TIME_SERIES = 201
PUSHOVER_PATTERN = 201
PUSHOVER_WEIGHTS = (0.1, 0.2, 0.3, 0.4)
if INCLUDE_REFERENCE_PUSHOVER_PATTERN:
    ops.timeSeries("Linear", PUSHOVER_TIME_SERIES)
    ops.pattern("Plain", PUSHOVER_PATTERN, PUSHOVER_TIME_SERIES)
    for master_node, reference_force in zip(FLOOR_MASTER_NODES, PUSHOVER_WEIGHTS):
        if PUSHOVER_DIRECTION.upper() == "X":
            ops.load(master_node, reference_force, 0.0, 0.0, 0.0, 0.0, 0.0)
        elif PUSHOVER_DIRECTION.upper() == "Y":
            ops.load(master_node, 0.0, reference_force, 0.0, 0.0, 0.0, 0.0)
        else:
            raise ValueError("PUSHOVER_DIRECTION must be 'X' or 'Y'.")
