"""A named building floor level (Story Manager) - purely organizational
metadata on top of whatever nodes the student already drew at that
elevation. Turning ``rigid_diaphragm`` on is what actually changes analysis
behaviour (see ``core.domain.model.RigidDiaphragm``, applied by
``canvas_model_build.py``/``solver.py``); the story itself never moves or
owns geometry.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Story:
    """``id``/``name`` split mirrors ``LoadCase``'s own (id stable across a
    rename, name display-only). ``elevation`` is the story's Z coordinate -
    nodes are matched to it by proximity (see ``nodes_at_story``), not by
    reference, so moving a node after the fact re-groups it automatically."""

    id: str
    name: str
    elevation: float
    rigid_diaphragm: bool = False
