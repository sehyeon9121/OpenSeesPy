"""Contract for external design-code material databases."""

from typing import Protocol

from openframe.core.domain.materials import MaterialDefinition, MaterialFamily


class MaterialCatalog(Protocol):
    def search(
        self,
        query: str = "",
        family: MaterialFamily | None = None,
    ) -> tuple[MaterialDefinition, ...]: ...
