"""A named building floor level (Story Manager) - purely organizational
metadata on top of whatever nodes the student already drew at that
elevation. Turning ``rigid_diaphragm`` on is what actually changes analysis
behaviour (see ``core.domain.model.RigidDiaphragm``, applied by
``canvas_model_build.py``/``solver.py``); the story itself never moves or
owns geometry.
"""

from dataclasses import dataclass

#: Nodes within this many model-length-units of a story's elevation count as
#: "at" that story. Story Manager grouping and the rectangular wall mesher's
#: horizontal seeds share this number so a floor label and a mesh row cannot
#: disagree about whether a Z is on that storey. Forgiving enough for grid
#: float noise, tight enough that two real floors are never merged.
STORY_Z_TOLERANCE = 1.0e-6


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
