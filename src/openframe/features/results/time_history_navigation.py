"""Shared time -> step-index mapping for Time History's Response History and
Animation views.

Both views must agree on what "the step nearest time T" means - this is the
one place that logic lives, so neither ever reconstructs a time via
``index * dt`` (a real record's steps are not always exactly evenly spaced,
and dt itself is only ever read from the recorded step times, never assumed).
"""

from bisect import bisect_left
from collections.abc import Sequence


def nearest_step_index(times: Sequence[float], target_time: float) -> int:
    """Index into ``times`` (ascending, as ``AnalysisResult.time_history``
    always is) whose stored time is closest to ``target_time``."""
    if not times:
        return 0
    index = bisect_left(times, target_time)
    if index <= 0:
        return 0
    if index >= len(times):
        return len(times) - 1
    before, after = times[index - 1], times[index]
    return index - 1 if (target_time - before) <= (after - target_time) else index
