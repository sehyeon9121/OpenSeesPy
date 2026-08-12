"""4-story, 1-bay 2D steel moment frame for time-history analysis examples.

Model only: no analysis commands. The time-history solver
(``time_history_solver.py``) builds its own transient analysis (constraints,
numberer, integrator, Rayleigh damping from ``ops.eigen``) around whatever
model script it is given, so this file only needs geometry, steel section
properties, and lumped floor mass.

Geometry
--------
* One 6.0 m bay
* Four 3.5 m stories (total height 14.0 m)
* Fixed column bases

Steel sections (nominal H-shape properties, illustrative - not a checked
design)
--------------------------------------------------------------------------
* Columns: H-300x300x10/15
* Beams:   H-400x200x8/13
* E = 200,000,000 kN/m^2 (200 GPa)

Mass
----
Lumped translational mass only (Ux, Uy - no rotational mass, standard
practice) at every floor node, split evenly between the two columns on that
floor. 20.0 kN*s^2/m per node is equivalent to a 392.4 kN seismic weight per
floor (m = W/g, g = 9.81 m/s^2).

To run a time history against this model, pair it with a ground-motion
record such as the bundled Kobe .AT2 file at
``src/openframe/infrastructure/ground_motions/data/RSN1116_KOBE_SHI-UP.AT2``.
"""

import openseespy.opensees as ops

OPENFRAME_UNITS = {"force": "kN", "length": "m", "time": "s"}

ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)

NUM_STORIES = 4
BAY_WIDTH = 6.0
STORY_HEIGHT = 3.5


def node_tag(level: int, grid_x: int) -> int:
    """Return a readable node tag: level 0 -> 1..2, level 1 -> 11..12, etc."""
    return level * 10 + grid_x + 1


for level in range(NUM_STORIES + 1):
    elevation = level * STORY_HEIGHT
    for grid_x in range(2):
        ops.node(node_tag(level, grid_x), grid_x * BAY_WIDTH, elevation)

for grid_x in range(2):
    ops.fix(node_tag(0, grid_x), 1, 1, 1)


# -----------------------------------------------------------------------------
# Lumped floor mass (translational only)
# -----------------------------------------------------------------------------
MASS_PER_NODE = 20.0  # kN*s^2/m, equivalent to a 392.4 kN seismic weight/floor

for level in range(1, NUM_STORIES + 1):
    for grid_x in range(2):
        ops.mass(node_tag(level, grid_x), MASS_PER_NODE, MASS_PER_NODE, 0.0)


# -----------------------------------------------------------------------------
# Steel member properties (kN, m)
# -----------------------------------------------------------------------------
ELASTIC_MODULUS = 200_000_000.0  # 200 GPa = 200,000,000 kN/m^2

COLUMN_AREA = 0.01198  # H-300x300x10/15, m^2
COLUMN_IZ = 2.02e-4  # m^4

BEAM_AREA = 0.008337  # H-400x200x8/13, m^2
BEAM_IZ = 2.37e-4  # m^4

ops.geomTransf("Linear", 1)

element_tag = 1
column_tags: list[int] = []
beam_tags: list[int] = []

# Columns are split at every floor joint.
for story in range(1, NUM_STORIES + 1):
    for grid_x in range(2):
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

# One beam per floor.
for story in range(1, NUM_STORIES + 1):
    i_node = node_tag(story, 0)
    j_node = node_tag(story, 1)
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
