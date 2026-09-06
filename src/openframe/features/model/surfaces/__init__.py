"""MODEL-side surface members (shear walls, slabs): geometry, not widgets.

Outline → mesh, connectivity, and round-trip fields belong here, the same
way ``features/model/drawing/`` owns snapping without importing Qt. Draw
tools, property panels, and the work-tree rows stay in
``features/model/presentation/``.

This is 3D modeling. The 2D canvas is a line-member drawing; it does not
grow a wall/slab editor.

Must not import PySide6 or OpenSeesPy. The solver reads ``core.domain``
after ``canvas_model_build`` (or the equivalent surface builder) has
produced it.
"""
