"""Opt-in Quick3D viewport performance instrumentation.

Enabled only when ``OPENFRAME_QUICK3D_PERF=1`` is set in the environment or
:func:`enable_quick3d_perf` is called explicitly.  Normal runs stay silent.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

_PERF_ENV = "OPENFRAME_QUICK3D_PERF"


def perf_enabled() -> bool:
    return os.environ.get(_PERF_ENV, "").lower() in {"1", "true", "yes"}


def enable_quick3d_perf(enabled: bool = True) -> None:
    if enabled:
        os.environ[_PERF_ENV] = "1"
    else:
        os.environ.pop(_PERF_ENV, None)


@dataclass
class Quick3DPerfCounters:
    """Aggregate counters for one profiling session."""

    scene_rebuilds: int = 0
    topology_rebuilds: int = 0
    geometry_updates: int = 0
    selection_updates: int = 0
    preview_updates: int = 0
    loads_updates: int = 0
    visibility_updates: int = 0
    set_model_calls: int = 0
    set_model_incremental: int = 0
    set_model_full: int = 0
    incremental_fallbacks: int = 0
    signal_emits: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    scoped_ms: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    last_delegate_counts: dict[str, int] = field(default_factory=dict)
    last_list_identities: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.scene_rebuilds = 0
        self.topology_rebuilds = 0
        self.geometry_updates = 0
        self.selection_updates = 0
        self.preview_updates = 0
        self.loads_updates = 0
        self.visibility_updates = 0
        self.set_model_calls = 0
        self.set_model_incremental = 0
        self.set_model_full = 0
        self.build_model_calls = 0
        self.incremental_fallbacks = 0
        self.signal_emits.clear()
        self.scoped_ms.clear()
        self.last_delegate_counts.clear()
        self.last_list_identities.clear()

    def summary_lines(self) -> list[str]:
        lines = [
            f"set_model calls={self.set_model_calls} "
            f"(incremental={self.set_model_incremental}, full={self.set_model_full})",
            f"build_model calls={self.build_model_calls} incremental_fallbacks={self.incremental_fallbacks}",
            f"topology_rebuilds={self.topology_rebuilds} scene_rebuilds={self.scene_rebuilds} "
            f"geometry_updates={self.geometry_updates} selection_updates={self.selection_updates} "
            f"preview_updates={self.preview_updates}",
        ]
        if self.last_list_identities:
            parts = ", ".join(
                f"{name}={value}" for name, value in sorted(self.last_list_identities.items())
            )
            lines.append(f"list_identities: {parts}")
        if self.last_delegate_counts:
            parts = ", ".join(
                f"{name}={count}" for name, count in sorted(self.last_delegate_counts.items())
            )
            lines.append(f"delegate_counts: {parts}")
        if self.signal_emits:
            parts = ", ".join(
                f"{name}={count}" for name, count in sorted(self.signal_emits.items())
            )
            lines.append(f"signal_emits: {parts}")
        if self.scoped_ms:
            parts = ", ".join(
                f"{name}={ms:.2f}ms" for name, ms in sorted(self.scoped_ms.items())
            )
            lines.append(f"scoped_time: {parts}")
        return lines


class Quick3DPerfRecorder:
    def __init__(self) -> None:
        self.counters = Quick3DPerfCounters()

    @contextmanager
    def scope(self, name: str) -> Iterator[None]:
        if not perf_enabled():
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.counters.scoped_ms[name] += elapsed_ms

    def record_signal(self, name: str) -> None:
        if perf_enabled():
            self.counters.signal_emits[name] += 1

    def record_delegate_counts(self, counts: dict[str, int]) -> None:
        if perf_enabled():
            self.counters.last_delegate_counts = dict(counts)

    def record_list_identities(self, identities: dict[str, int]) -> None:
        if perf_enabled():
            self.counters.last_list_identities = dict(identities)

    def record_incremental_fallback(self, reason: str) -> None:
        if perf_enabled():
            self.counters.incremental_fallbacks += 1
            self.counters.scoped_ms[f"fallback:{reason}"] += 0.0

    def log_summary(self) -> None:
        if not perf_enabled():
            return
        for line in self.counters.summary_lines():
            print(f"[Quick3D perf] {line}")


_GLOBAL_RECORDER = Quick3DPerfRecorder()


def perf_recorder() -> Quick3DPerfRecorder:
    return _GLOBAL_RECORDER
