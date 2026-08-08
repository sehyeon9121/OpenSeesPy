"""Four-by-four-bay, four-story 3D elastic moment-resisting frame.

Model only: this file deliberately contains no solver, analysis, or analyze
commands. Units are kN and m so the values can be reproduced directly in MIDAS.

Geometry
--------
* Four 6.0 m bays in global X and four 6.0 m bays in global Y
* Four 3.5 m stories in global Z
* 5 x 5 columns at every floor and fixed column bases
* Beams connect every adjacent grid point in both plan directions

Loads
-----
* 20 kN/m downward uniform load on every X- and Y-direction beam
* Story lateral forces of 100, 200, 300, and 400 kN in global +X
  (each total is divided equally between the 25 joints on that floor)

No slab or rigid diaphragm is included, keeping the model a pure space frame.
"""

import openseespy.opensees as ops

# -----------------------------------------------------------------------------
# Model and geometry (kN, m)
# -----------------------------------------------------------------------------
ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)

NUM_BAYS_X = 4
NUM_BAYS_Y = 4
NUM_STORIES = 4
BAY_WIDTH_X = 6.0
BAY_WIDTH_Y = 6.0
STORY_HEIGHT = 3.5


def node_tag(level: int, grid_x: int, grid_y: int) -> int:
    """Return a readable unique tag for a level and plan-grid position."""
    return level * 100 + grid_y * 10 + grid_x + 1


for level in range(NUM_STORIES + 1):
    z_coord = level * STORY_HEIGHT
    for grid_y in range(NUM_BAYS_Y + 1):
        y_coord = grid_y * BAY_WIDTH_Y
        for grid_x in range(NUM_BAYS_X + 1):
            x_coord = grid_x * BAY_WIDTH_X
            ops.node(node_tag(level, grid_x, grid_y), x_coord, y_coord, z_coord)

for grid_y in range(NUM_BAYS_Y + 1):
    for grid_x in range(NUM_BAYS_X + 1):
        ops.fix(node_tag(0, grid_x, grid_y), 1, 1, 1, 1, 1, 1)


# -----------------------------------------------------------------------------
# Elastic concrete member properties
# -----------------------------------------------------------------------------
ELASTIC_MODULUS = 25_000_000.0  # 25 GPa = 25,000,000 kN/m2
POISSON_RATIO = 0.20
SHEAR_MODULUS = ELASTIC_MODULUS / (2.0 * (1.0 + POISSON_RATIO))

COLUMN_WIDTH = 0.50
COLUMN_DEPTH = 0.50
COLUMN_AREA = COLUMN_WIDTH * COLUMN_DEPTH
COLUMN_IY = COLUMN_DEPTH * COLUMN_WIDTH**3 / 12.0
COLUMN_IZ = COLUMN_WIDTH * COLUMN_DEPTH**3 / 12.0
COLUMN_J = 0.1406 * COLUMN_WIDTH**4  # Saint-Venant torsion constant for a square

BEAM_WIDTH = 0.35
BEAM_DEPTH = 0.60
BEAM_AREA = BEAM_WIDTH * BEAM_DEPTH
BEAM_IY = BEAM_WIDTH * BEAM_DEPTH**3 / 12.0  # strong axis; local Z is vertical
BEAM_IZ = BEAM_DEPTH * BEAM_WIDTH**3 / 12.0
BEAM_J = BEAM_WIDTH * BEAM_DEPTH**3 * (
    1.0 / 3.0
    - 0.21 * (BEAM_WIDTH / BEAM_DEPTH) * (1.0 - BEAM_WIDTH**4 / (12.0 * BEAM_DEPTH**4))
)

# vecxz defines each member's local x-z plane. Beam local Z is global Z, so a
# negative local-Z element load is a global downward gravity load.
ops.geomTransf("Linear", 1, 1.0, 0.0, 0.0)  # vertical columns
ops.geomTransf("Linear", 2, 0.0, 0.0, 1.0)  # horizontal X/Y beams

element_tag = 1
column_tags: list[int] = []
beam_x_tags: list[int] = []
beam_y_tags: list[int] = []

# Columns
for story in range(1, NUM_STORIES + 1):
    for grid_y in range(NUM_BAYS_Y + 1):
        for grid_x in range(NUM_BAYS_X + 1):
            i_node = node_tag(story - 1, grid_x, grid_y)
            j_node = node_tag(story, grid_x, grid_y)
            ops.element(
                "elasticBeamColumn",
                element_tag,
                i_node,
                j_node,
                COLUMN_AREA,
                ELASTIC_MODULUS,
                SHEAR_MODULUS,
                COLUMN_J,
                COLUMN_IY,
                COLUMN_IZ,
                1,
            )
            column_tags.append(element_tag)
            element_tag += 1

# X-direction beams
for story in range(1, NUM_STORIES + 1):
    for grid_y in range(NUM_BAYS_Y + 1):
        for bay_x in range(NUM_BAYS_X):
            i_node = node_tag(story, bay_x, grid_y)
            j_node = node_tag(story, bay_x + 1, grid_y)
            ops.element(
                "elasticBeamColumn",
                element_tag,
                i_node,
                j_node,
                BEAM_AREA,
                ELASTIC_MODULUS,
                SHEAR_MODULUS,
                BEAM_J,
                BEAM_IY,
                BEAM_IZ,
                2,
            )
            beam_x_tags.append(element_tag)
            element_tag += 1

# Y-direction beams
for story in range(1, NUM_STORIES + 1):
    for grid_x in range(NUM_BAYS_X + 1):
        for bay_y in range(NUM_BAYS_Y):
            i_node = node_tag(story, grid_x, bay_y)
            j_node = node_tag(story, grid_x, bay_y + 1)
            ops.element(
                "elasticBeamColumn",
                element_tag,
                i_node,
                j_node,
                BEAM_AREA,
                ELASTIC_MODULUS,
                SHEAR_MODULUS,
                BEAM_J,
                BEAM_IY,
                BEAM_IZ,
                2,
            )
            beam_y_tags.append(element_tag)
            element_tag += 1


# -----------------------------------------------------------------------------
# Load patterns only -- no analysis is configured or executed below.
# -----------------------------------------------------------------------------
BEAM_LINE_LOAD = 20.0  # kN/m, global downward through member local -Z

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
for tag in beam_x_tags + beam_y_tags:
    # 3D elastic beam uniform-load order: Wy, Wz, Wx.
    ops.eleLoad("-ele", tag, "-type", "-beamUniform", 0.0, -BEAM_LINE_LOAD, 0.0)

STORY_LATERAL_FORCES = (100.0, 200.0, 300.0, 400.0)  # kN total at each floor
JOINTS_PER_FLOOR = (NUM_BAYS_X + 1) * (NUM_BAYS_Y + 1)

ops.timeSeries("Linear", 2)
ops.pattern("Plain", 2, 2)
for story, floor_force in enumerate(STORY_LATERAL_FORCES, start=1):
    joint_force = floor_force / JOINTS_PER_FLOOR
    for grid_y in range(NUM_BAYS_Y + 1):
        for grid_x in range(NUM_BAYS_X + 1):
            ops.load(
                node_tag(story, grid_x, grid_y),
                joint_force,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )


# Intentionally omitted:
# ops.system(...), ops.constraints(...), ops.numberer(...), ops.test(...),
# ops.algorithm(...), ops.integrator(...), ops.analysis(...), and ops.analyze(...)
