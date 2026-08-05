from openframe.core.domain.materials import (
    MaterialDefinition,
    MaterialFamily,
    MaterialSource,
    ShearDeformationSettings,
    ShearModulusMode,
)
from openframe.core.domain.units import UnitSystem
from openframe.features.model.application.material_library import MaterialLibrary
from openframe.infrastructure.materials.empty_kds_catalog import EmptyKdsMaterialCatalog


def test_material_validation_and_shear_modulus_are_domain_logic() -> None:
    material = MaterialDefinition(
        material_id="USER-001",
        name="Elastic steel",
        family=MaterialFamily.STRUCTURAL_STEEL,
        elastic_modulus=205_000.0,
        poisson_ratio=0.3,
    )

    assert material.validate() == []
    assert material.derived_shear_modulus == 205_000.0 / 2.6

    settings = ShearDeformationSettings(enabled=True)
    assert settings.effective_shear_modulus(material) == material.derived_shear_modulus
    assert settings.validate() == []


def test_manual_shear_modulus_is_validated_separately_from_material() -> None:
    settings = ShearDeformationSettings(
        enabled=True,
        modulus_mode=ShearModulusMode.USER_DEFINED,
        user_shear_modulus=0.0,
    )

    assert settings.validate() == ["사용자 정의 전단탄성계수 G는 0보다 커야 합니다."]


def test_empty_kds_adapter_and_user_library_are_independent() -> None:
    library = MaterialLibrary(EmptyKdsMaterialCatalog())

    assert library.search_kds() == ()
    material = library.create_user_material("Project steel")
    saved = material.with_changes(
        source=MaterialSource.USER_DEFINED,
        family=MaterialFamily.STRUCTURAL_STEEL,
        elastic_modulus=205_000.0,
    )
    library.save_user_material(saved)

    assert library.user_materials() == (saved,)
    assert library.search_kds(query="steel") == ()


def test_unit_system_exposes_material_property_units() -> None:
    units = UnitSystem(force="N", length="mm")

    assert units.stress == "N/mm²"
    assert units.volumetric_force == "N/mm³"
