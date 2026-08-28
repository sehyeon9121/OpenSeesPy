"""Record the distributed element loads a script applies.

OpenSees offers no way to read ``eleLoad`` back once it has been applied, but the
values are needed to reconstruct the internal forces between a member's two ends.
The command is therefore observed while the model script runs.
"""

from collections.abc import Callable
from typing import Any

import openseespy.opensees as ops

_UNIFORM = "-beamUniform"
_POINT = "-beamPoint"


class ElementLoadCollector:
    """Capture ``-beamUniform`` loads, keyed by element tag, in local axes."""

    def __init__(self) -> None:
        # element tag -> (wx, wy) along the member's own axes.
        self.uniform_loads: dict[int, tuple[float, float]] = {}
        # 3D form retains the second transverse component: (wx, wy, wz).
        self.uniform_loads_3d: dict[int, tuple[float, float, float]] = {}
        # Preserve individual OpenSees load patterns for model-browser display.
        self.uniform_load_cases: dict[
            tuple[int | None, int], tuple[float, float, float]
        ] = {}
        #: Every ``-beamPoint`` call, one entry per call (not summed the way
        #: uniform loads are - a member can carry several point loads at
        #: different stations, which cannot be collapsed into one tuple the
        #: way "one w(x) per element" can). Local axes, in OpenSeesPy's own
        #: ``(Py, Pz, xL, N)``/``(Py, xL, N)`` argument order regardless of
        #: source - added for buckling_solver.py's reference-load support
        #: (see its own module docstring); no other consumer reads this yet.
        #: Still added to ``unsupported`` below unchanged - a point load is
        #: still not reconstructed into a member-force diagram, only usable
        #: as a reference-load magnitude/reapplication source.
        self.point_load_cases: list[dict[str, Any]] = []
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

    def record(
        self, args: tuple[Any, ...], ndm: int = 2, pattern_tag: int | None = None
    ) -> None:
        """Record one raw ``ops.eleLoad`` argument tuple."""
        tags = _element_tags(args)
        if not tags:
            return

        load_type, values = _load_type_and_values(args)
        if load_type == _POINT:
            self.unsupported.update(tags)
            parsed = _parse_point_load(values, ndm)
            if parsed is not None:
                py, pz, position, n = parsed
                for tag in tags:
                    self.point_load_cases.append(
                        {
                            "element_tag": tag,
                            "pattern_tag": pattern_tag,
                            "py": py,
                            "pz": pz,
                            "position": position,
                            "n": n,
                        }
                    )
            return
        if load_type != _UNIFORM:
            self.unsupported.update(tags)
            return

        if ndm == 3:
            # 3D OpenSees form is (Wy, Wz, Wx), with Wx optional.
            wy = float(values[0]) if len(values) > 0 else 0.0
            wz = float(values[1]) if len(values) > 1 else 0.0
            wx = float(values[2]) if len(values) > 2 else 0.0
            for tag in tags:
                old_x, old_y, old_z = self.uniform_loads_3d.get(tag, (0.0, 0.0, 0.0))
                self.uniform_loads_3d[tag] = (old_x + wx, old_y + wy, old_z + wz)
                self._record_case(pattern_tag, tag, wx, wy, wz)
            return

        # 2D form is (Wy, Wx) with Wx optional; both are along local axes.
        wy = float(values[0]) if len(values) > 0 else 0.0
        wx = float(values[1]) if len(values) > 1 else 0.0
        for tag in tags:
            previous_x, previous_y = self.uniform_loads.get(tag, (0.0, 0.0))
            self.uniform_loads[tag] = (previous_x + wx, previous_y + wy)
            self._record_case(pattern_tag, tag, wx, wy, 0.0)

    def _record_case(
        self,
        pattern_tag: int | None,
        element_tag: int,
        wx: float,
        wy: float,
        wz: float,
    ) -> None:
        key = (pattern_tag, element_tag)
        old_x, old_y, old_z = self.uniform_load_cases.get(key, (0.0, 0.0, 0.0))
        self.uniform_load_cases[key] = (old_x + wx, old_y + wy, old_z + wz)


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


def _parse_point_load(
    values: list[float], ndm: int
) -> tuple[float, float, float, float] | None:
    """``(Py, Pz, xL, N)`` from a raw ``-beamPoint`` value list, in
    OpenSeesPy's own real argument order - ``(Py, Pz, xL, N)`` for 3D,
    ``(Py, xL, N)`` for 2D (no out-of-plane ``Pz`` component; reported as
    0.0). ``N`` defaults to 0.0 when omitted (OpenSeesPy's own optional
    trailing argument)."""
    if ndm == 3:
        if len(values) < 3:
            return None
        py, pz, position = values[0], values[1], values[2]
        n = values[3] if len(values) > 3 else 0.0
        return py, pz, position, n
    if len(values) < 2:
        return None
    py, position = values[0], values[1]
    n = values[2] if len(values) > 2 else 0.0
    return py, 0.0, position, n


def _values_after(args: tuple[Any, ...], flag: str) -> list[float]:
    values: list[float] = []
    for value in args[args.index(flag) + 1 :]:
        if isinstance(value, str):
            break
        values.append(value)
    return values
