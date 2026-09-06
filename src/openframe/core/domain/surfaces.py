"""Reserved for shear-wall / slab (surface) members.

``Element`` is a two-node member (``node_i``, ``node_j``). A wall or slab
needs a loop of nodes and a thickness; stuffing that into the beam type
would make every beam-only reader lie about connectivity. This module is
where that domain type will live - Qt-free and OpenSees-free, like the rest
of ``core.domain``.

Not a surface, and not to be reused as one:

- ``FloorLoadEntry`` is a pressure on a polygon, tributed onto beams
  (``features/model/presentation/floor_tributary.py``).
- ``RigidDiaphragm`` is a kinematic floor constraint, not plate stiffness.

Do not invent node counts, OpenSees element names, or section fields here
until the modeling/solver requirements are specified. ``StructuralModel``
gains a collection of these only at that point; existing beam models stay
``elements: dict[int, Element]`` exactly as they are.
"""
