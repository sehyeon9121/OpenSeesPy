"""Application service for KDS and user-authored material definitions."""

from openframe.core.contracts.material_catalog import MaterialCatalog
from openframe.core.domain.materials import MaterialDefinition, MaterialFamily, MaterialSource


class MaterialLibrary:
    def __init__(self, kds_catalog: MaterialCatalog) -> None:
        self._kds_catalog = kds_catalog
        self._user_materials: dict[str, MaterialDefinition] = {}
        self._next_user_id = 1

    def search_kds(
        self,
        query: str = "",
        family: MaterialFamily | None = None,
    ) -> tuple[MaterialDefinition, ...]:
        return self._kds_catalog.search(query=query, family=family)

    def user_materials(self) -> tuple[MaterialDefinition, ...]:
        return tuple(self._user_materials.values())

    def create_user_material(self, name: str | None = None) -> MaterialDefinition:
        material_id = f"USER-{self._next_user_id:03d}"
        self._next_user_id += 1
        material = MaterialDefinition(
            material_id=material_id,
            name=name or f"사용자 재료 {len(self._user_materials) + 1}",
            source=MaterialSource.USER_DEFINED,
            elastic_modulus=1.0,
        )
        self._user_materials[material_id] = material
        return material

    def save_user_material(self, material: MaterialDefinition) -> None:
        if material.source != MaterialSource.USER_DEFINED:
            raise ValueError("KDS DB 재료는 사용자 재료로 덮어쓸 수 없습니다.")
        if material.validate():
            raise ValueError("유효하지 않은 재료는 저장할 수 없습니다.")
        self._user_materials[material.material_id] = material

    def duplicate_as_user_material(self, material: MaterialDefinition) -> MaterialDefinition:
        duplicate = self.create_user_material(f"{material.name} 복사본")
        duplicate = material.with_changes(
            material_id=duplicate.material_id,
            name=duplicate.name,
            source=MaterialSource.USER_DEFINED,
            metadata=dict(material.metadata),
        )
        self._user_materials[duplicate.material_id] = duplicate
        return duplicate

    def remove_user_material(self, material_id: str) -> None:
        self._user_materials.pop(material_id, None)
