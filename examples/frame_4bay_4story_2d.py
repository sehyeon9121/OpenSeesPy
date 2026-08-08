"""Four-bay, four-story 2D elastic moment-resisting frame.

Model only: this file deliberately contains no solver, analysis, or analyze
commands. Units are kN and m so the values can be reproduced directly in MIDAS.

Geometry
--------
* Four 6.0 m bays (total width 24.0 m)
* Four 3.5 m stories (total height 14.0 m)
* Fixed column bases

Loads
-----
* 20 kN/m downward uniform load on every beam
* Story lateral forces of 20, 40, 60, and 80 kN in global +X
  (each total is divided equally between the five joints on that floor)
"""

import openseespy.opensees as ops

# -----------------------------------------------------------------------------
# Model and geometry (kN, m)
# -----------------------------------------------------------------------------
ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

NUM_BAYS = 4
NUM_STORIES = 4
BAY_WIDTH = 6.0
STORY_HEIGHT = 3.5


def node_tag(level: int, grid_x: int) -> int:
    """Return a readable node tag: level 0 -> 1..5, level 1 -> 11..15, etc."""
    return level * 10 + grid_x + 1


for level in range(NUM_STORIES + 1):
    elevation = level * STORY_HEIGHT
    for grid_x in range(NUM_BAYS + 1):
        ops.node(node_tag(level, grid_x), grid_x * BAY_WIDTH, elevation)

for grid_x in range(NUM_BAYS + 1):
    ops.fix(node_tag(0, grid_x), 1, 1, 1)


# -----------------------------------------------------------------------------
# Elastic concrete member properties
# -----------------------------------------------------------------------------
ELASTIC_MODULUS = 25_000_000.0  # 25 GPa = 25,000,000 kN/m2

COLUMN_WIDTH = 0.50
COLUMN_DEPTH = 0.50
COLUMN_AREA = COLUMN_WIDTH * COLUMN_DEPTH
COLUMN_IZ = COLUMN_WIDTH * COLUMN_DEPTH**3 / 12.0

BEAM_WIDTH = 0.35
BEAM_DEPTH = 0.60
BEAM_AREA = BEAM_WIDTH * BEAM_DEPTH
BEAM_IZ = BEAM_WIDTH * BEAM_DEPTH**3 / 12.0

ops.geomTransf("Linear", 1)

element_tag = 1
column_tags: list[int] = []
beam_tags: list[int] = []

# Columns are split at every floor joint.
for story in range(1, NUM_STORIES + 1):
    for grid_x in range(NUM_BAYS + 1):
        i_node = node_tag(story - 1, grid_x)
        j_node = node_tag(story, grid_x)
        ops.element(
            "elasticBeamColumn",
            element_tag,
            i_node,
            j_node,
            COLUMN_AREA,
            ELASTIC_MODULUS,
            COLUMN_IZ,
            1,
        )
        column_tags.append(element_tag)
        element_tag += 1

# Beams run from left to right on every elevated floor.
for story in range(1, NUM_STORIES + 1):
    for bay in range(NUM_BAYS):
        i_node = node_tag(story, bay)
        j_node = node_tag(story, bay + 1)
        ops.element(
            "elasticBeamColumn",
            element_tag,
            i_node,
            j_node,
            BEAM_AREA,
            ELASTIC_MODULUS,
            BEAM_IZ,
            1,
        )
        beam_tags.append(element_tag)
        element_tag += 1


# -----------------------------------------------------------------------------
# Load patterns only -- no analysis is configured or executed below.
# -----------------------------------------------------------------------------
BEAM_LINE_LOAD = 20.0  # kN/m, downward

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
for tag in beam_tags:
    # For a left-to-right 2D beam, local -Y is vertically downward.
    ops.eleLoad("-ele", tag, "-type", "-beamUniform", -BEAM_LINE_LOAD)

STORY_LATERAL_FORCES = (20.0, 40.0, 60.0, 80.0)  # kN total at each floor

ops.timeSeries("Linear", 2)
ops.pattern("Plain", 2, 2)
for story, floor_force in enumerate(STORY_LATERAL_FORCES, start=1):
    joint_force = floor_force / (NUM_BAYS + 1)
    for grid_x in range(NUM_BAYS + 1):
        ops.load(node_tag(story, grid_x), joint_force, 0.0, 0.0)


# Intentionally omitted:
# ops.system(...), ops.constraints(...), ops.numberer(...), ops.test(...),
# ops.algorithm(...), ops.integrator(...), ops.analysis(...), and ops.analyze(...)
