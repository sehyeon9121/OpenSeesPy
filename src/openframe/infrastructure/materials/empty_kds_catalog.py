"""Placeholder adapter until verified KDS material records are supplied."""

from openframe.core.domain.materials import MaterialDefinition, MaterialFamily


class EmptyKdsMaterialCatalog:
    def search(
        self,
        query: str = "",
        family: MaterialFamily | None = None,
    ) -> tuple[MaterialDefinition, ...]:
        del query, family
        return ()
