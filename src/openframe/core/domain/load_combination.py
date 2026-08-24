"""A named combination of load cases, each scaled by its own factor.

Deliberately simple for now - no ADD/ENVELOPE distinction, no code-based
auto-generation (KBC/ASCE load combination tables) the way MIDAS offers. A
student enters the cases and factors themselves (e.g. 1.2*DEAD + 1.6*LIVE);
each case is one of the fixed ``LoadCaseKind`` categories the canvas already
lets a load carry (see ``core.domain.model.LoadCaseKind``), not a free-form
named case list.
"""

from dataclasses import dataclass, field

from openframe.core.domain.model import LoadCaseKind


@dataclass(frozen=True, slots=True)
class LoadCombination:
    """One named combination, e.g. "1.2DL + 1.6LL" as ``factors={DEAD: 1.2,
    LIVE: 1.6}``. A case absent from ``factors`` contributes nothing.

    ``LoadCaseKind.UNCLASSIFIED`` (the default for a load nobody has tagged
    with a case yet) is deliberately never combined - a load a student never
    assigned a case to should not silently show up scaled into a combination
    just because some combination happens to give UNCLASSIFIED a factor.
    """

    name: str
    factors: dict[LoadCaseKind, float] = field(default_factory=dict)

    def factor_for(self, case: LoadCaseKind) -> float:
        if case is LoadCaseKind.UNCLASSIFIED:
            return 0.0
        return self.factors.get(case, 0.0)
