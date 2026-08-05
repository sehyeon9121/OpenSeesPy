"""3D 4-bay x 4-bay, 4-story frame matching Desktop/1.mgt.

Model and loads only. No analysis command is included.

Comparison conditions (kN, m)
--------------------------------
* Plan: 4 bays at 6.0 m in global X and global Y
* Height: 4 stories at 3.5 m
* Bases: all 25 base nodes fully fixed
* Material: MIDAS KCI-2012 C24 elastic modulus, E = 25.791 GPa
* Columns: 0.50 m x 0.50 m
* Beams: 0.35 m wide x 0.60 m deep
* Loads: global +X nodal loads only on the five nodes of the X=0 exterior frame
  - Story 1: 4 kN at each of 5 nodes (20 kN story total)
  - Story 2: 8 kN at each of 5 nodes (40 kN story total)
  - Story 3: 12 kN at each of 5 nodes (60 kN story total)
  - Story 4: 16 kN at each of 5 nodes (80 kN story total)
* No self-weight and no beam distributed load
* No slab or rigid diaphragm
"""

import openseespy.opensees as ops

ops.wipe()
ops.model("basic", "-ndm", 3, "-ndf", 6)

# Geometry
NUM_BAYS_X = 4
NUM_BAYS_Y = 4
NUM_STORIES = 4
BAY_WIDTH_X = 6.0
BAY_WIDTH_Y = 6.0
STORY_HEIGHT = 3.5


def node_tag(level: int, grid_x: int, grid_y: int) -> int:
    return level * 100 + grid_y * 10 + grid_x + 1


for level in range(NUM_STORIES + 1):
    for grid_y in range(NUM_BAYS_Y + 1):
        for grid_x in range(NUM_BAYS_X + 1):
            ops.node(
                node_tag(level, grid_x, grid_y),
                grid_x * BAY_WIDTH_X,
                grid_y * BAY_WIDTH_Y,
                level * STORY_HEIGHT,
            )

for grid_y in range(NUM_BAYS_Y + 1):
    for grid_x in range(NUM_BAYS_X + 1):
        ops.fix(node_tag(0, grid_x, grid_y), 1, 1, 1, 1, 1, 1)


# MIDAS KCI-2012 C24 elastic material
ELASTIC_MODULUS = 25_791_000.0  # kN/m2 = 25,791 MPa
POISSON_RATIO = 0.20
SHEAR_MODULUS = ELASTIC_MODULUS / (2.0 * (1.0 + POISSON_RATIO))

# 0.50 m x 0.50 m square columns
COLUMN_WIDTH = 0.50
COLUMN_DEPTH = 0.50
COLUMN_AREA = COLUMN_WIDTH * COLUMN_DEPTH
COLUMN_IY = COLUMN_DEPTH * COLUMN_WIDTH**3 / 12.0
COLUMN_IZ = COLUMN_WIDTH * COLUMN_DEPTH**3 / 12.0
COLUMN_J = 0.1406 * COLUMN_WIDTH**4

# 0.35 m wide x 0.60 m deep beams
BEAM_WIDTH = 0.35
BEAM_DEPTH = 0.60
BEAM_AREA = BEAM_WIDTH * BEAM_DEPTH
BEAM_IY = BEAM_WIDTH * BEAM_DEPTH**3 / 12.0
BEAM_IZ = BEAM_DEPTH * BEAM_WIDTH**3 / 12.0
BEAM_J = BEAM_WIDTH * BEAM_DEPTH**3 * (
    1.0 / 3.0
    - 0.21 * (BEAM_WIDTH / BEAM_DEPTH) * (1.0 - BEAM_WIDTH**4 / (12.0 * BEAM_DEPTH**4))
)

# Local-axis orientation: beam local Z is global Z.
ops.geomTransf("Linear", 1, 1.0, 0.0, 0.0)  # columns
ops.geomTransf("Linear", 2, 0.0, 0.0, 1.0)  # beams

element_tag = 1

# 100 columns
for story in range(1, NUM_STORIES + 1):
    for grid_y in range(NUM_BAYS_Y + 1):
        for grid_x in range(NUM_BAYS_X + 1):
            ops.element(
                "elasticBeamColumn",
                element_tag,
                node_tag(story - 1, grid_x, grid_y),
                node_tag(story, grid_x, grid_y),
                COLUMN_AREA,
                ELASTIC_MODULUS,
                SHEAR_MODULUS,
                COLUMN_J,
                COLUMN_IY,
                COLUMN_IZ,
                1,
            )
            element_tag += 1

# 80 beams in global X
for story in range(1, NUM_STORIES + 1):
    for grid_y in range(NUM_BAYS_Y + 1):
        for bay_x in range(NUM_BAYS_X):
            ops.element(
                "elasticBeamColumn",
                element_tag,
                node_tag(story, bay_x, grid_y),
                node_tag(story, bay_x + 1, grid_y),
                BEAM_AREA,
                ELASTIC_MODULUS,
                SHEAR_MODULUS,
                BEAM_J,
                BEAM_IY,
                BEAM_IZ,
                2,
            )
            element_tag += 1

# 80 beams in global Y
for story in range(1, NUM_STORIES + 1):
    for grid_x in range(NUM_BAYS_X + 1):
        for bay_y in range(NUM_BAYS_Y):
            ops.element(
                "elasticBeamColumn",
                element_tag,
                node_tag(story, grid_x, bay_y),
                node_tag(story, grid_x, bay_y + 1),
                BEAM_AREA,
                ELASTIC_MODULUS,
                SHEAR_MODULUS,
                BEAM_J,
                BEAM_IY,
                BEAM_IZ,
                2,
            )
            element_tag += 1


# One MIDAS-equivalent static load case: loads only on the X=0 exterior frame.
LOAD_PER_NODE_BY_STORY = (4.0, 8.0, 12.0, 16.0)  # kN in global +X

ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
for story, load_per_node in enumerate(LOAD_PER_NODE_BY_STORY, start=1):
    for grid_y in range(NUM_BAYS_Y + 1):
        ops.load(
            node_tag(story, 0, grid_y),
            load_per_node,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        )


# Intentionally omitted: system, constraints, numberer, algorithm, integrator,
# analysis, analyze, self-weight, and element-load commands.
