"""A user-named load case (e.g. "LL_OFFICE"), distinct from ``LoadCaseKind``.

``LoadCaseKind`` (``core.domain.model``) is a small fixed enum of semantic
categories a *solver-facing* load (``NodalLoad``/``UniformElementLoad``)
tags itself with. It was deliberately never a free-form named list (see its
own docstring). The Loads tab UI needs actual named cases a student creates
("DL_SELF", "LL_OFFICE", "WX_POS", ...), each still classified under one of
those semantic kinds for coloring/combination purposes - ``LoadCase`` is
that pairing: a free name plus a ``LoadCaseKind``, managed independently of
any specific load.
"""

from dataclasses import dataclass

from openframe.core.domain.model import LoadCaseKind


@dataclass(frozen=True, slots=True)
class LoadCase:
    """One named load case a student defines in the Load Case Manager.

    ``id`` is the stable key other objects (``LoadEntry.case_id``,
    ``LoadCombination.factors``' eventual per-case keying) reference - kept
    separate from ``name`` so a rename never has to cascade through every
    load that already points at this case. Today ``id`` and ``name`` start
    identical (the case's name at creation time); only renaming makes them
    diverge.
    """

    id: str
    name: str
    kind: LoadCaseKind = LoadCaseKind.UNCLASSIFIED
    description: str = ""
