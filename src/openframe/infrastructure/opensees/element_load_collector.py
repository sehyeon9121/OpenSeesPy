"""Record the distributed element loads a script applies.

OpenSees offers no way to read ``eleLoad`` back once it has been applied, but the
values are needed to reconstruct the internal forces between a member's two ends.
The command is therefore observed while the model script runs.
"""

from collections.abc import Callable
from typing import Any

import openseespy.opensees as ops

_UNIFORM = "-beamUniform"


class ElementLoadCollector:
    """Capture ``-beamUniform`` loads, keyed by element tag, in local axes."""

    def __init__(self) -> None:
        # element tag -> (wx, wy) along the member's own axes.
        self.uniform_loads: dict[int, tuple[float, float]] = {}
        # Elements carrying a load pattern this reconstruction cannot represent.
        self.unsupported: set[int] = set()
        self._original: Callable[..., Any] | None = None

    def install(self) -> None:
        if self._original is not None:
            return
        self._original = ops.eleLoad
        original = self._original

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            try:
                self.record(args)
            except (ValueError, IndexError, TypeError):
                # A load we cannot parse must never break the analysis itself.
                pass
            return result

        ops.eleLoad = wrapped

    def restore(self) -> None:
        if self._original is not None:
            ops.eleLoad = self._original
            self._original = None

    def record(self, args: tuple[Any, ...]) -> None:
        """Record one raw ``ops.eleLoad`` argument tuple."""
        tags = _element_tags(args)
        if not tags:
            return

        load_type, values = _load_type_and_values(args)
        if load_type != _UNIFORM:
            self.unsupported.update(tags)
            return

        # 2D form is (Wy, Wx) with Wx optional; both are along the member's local axes.
        wy = float(values[0]) if len(values) > 0 else 0.0
        wx = float(values[1]) if len(values) > 1 else 0.0
        for tag in tags:
            previous_x, previous_y = self.uniform_loads.get(tag, (0.0, 0.0))
            self.uniform_loads[tag] = (previous_x + wx, previous_y + wy)


def _element_tags(args: tuple[Any, ...]) -> list[int]:
    if "-ele" in args:
        return [int(value) for value in _values_after(args, "-ele")]
    if "-range" in args:
        bounds = [int(value) for value in _values_after(args, "-range")]
        if len(bounds) >= 2:
            return list(range(bounds[0], bounds[1] + 1))
    return []


def _load_type_and_values(args: tuple[Any, ...]) -> tuple[str, list[float]]:
    if "-type" not in args:
        return "", []
    index = args.index("-type") + 1
    if index >= len(args):
        return "", []
    load_type = str(args[index])
    values = [float(value) for value in args[index + 1 :] if isinstance(value, (int, float))]
    return load_type, values


def _values_after(args: tuple[Any, ...], flag: str) -> list[float]:
    values: list[float] = []
    for value in args[args.index(flag) + 1 :]:
        if isinstance(value, str):
            break
        values.append(value)
    return values
