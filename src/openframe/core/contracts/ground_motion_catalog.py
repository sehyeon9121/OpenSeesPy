"""Contract for listing and loading ground-motion acceleration records."""

from typing import Protocol

from openframe.core.domain import GroundMotionRecord


class GroundMotionCatalog(Protocol):
    def list_records(self) -> tuple[GroundMotionRecord, ...]: ...

    def load_series(self, record: GroundMotionRecord) -> tuple[float, ...]: ...
