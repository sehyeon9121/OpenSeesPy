"""Contract for converting an external model source to the domain model."""

from pathlib import Path
from typing import Protocol

from openframe.core.domain import StructuralModel


class ModelImporter(Protocol):
    def load(self, source: Path) -> StructuralModel: ...

