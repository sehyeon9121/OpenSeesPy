"""Material definitions used by models authored inside OpenFrame."""

from dataclasses import dataclass, field, replace
from enum import StrEnum


class MaterialSource(StrEnum):
    KDS_DATABASE = "kds_database"
    USER_DEFINED = "user_defined"


class MaterialFamily(StrEnum):
    CONCRETE = "concrete"
    STRUCTURAL_STEEL = "structural_steel"
    REINFORCING_STEEL = "reinforcing_steel"
    ELASTIC_ISOTROPIC = "elastic_isotropic"
    OTHER = "other"


class ShearModulusMode(StrEnum):
    DERIVED_FROM_POISSON = "derived_from_poisson"
    USER_DEFINED = "user_defined"


@dataclass(frozen=True, slots=True)
class MaterialDefinition:
    """Unit-aware values are stored in the direct model's declared unit system."""

    material_id: str
    name: str
    source: MaterialSource = MaterialSource.USER_DEFINED
    family: MaterialFamily = MaterialFamily.ELASTIC_ISOTROPIC
    opensees_model: str = "Elastic"
    elastic_modulus: float = 0.0
    poisson_ratio: float = 0.3
    density: float = 0.0
    thermal_expansion: float = 0.0
    yield_strength: float | None = None
    compressive_strength: float | None = None
    tensile_strength: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def derived_shear_modulus(self) -> float | None:
        denominator = 2.0 * (1.0 + self.poisson_ratio)
        if self.elastic_modulus <= 0.0 or denominator <= 0.0:
            return None
        return self.elastic_modulus / denominator

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.material_id.strip():
            errors.append("재료 ID가 필요합니다.")
        if not self.name.strip():
            errors.append("재료 이름이 필요합니다.")
        if self.elastic_modulus <= 0.0:
            errors.append("탄성계수 E는 0보다 커야 합니다.")
        if not -1.0 < self.poisson_ratio < 0.5:
            errors.append("포아송비는 -1보다 크고 0.5보다 작아야 합니다.")
        if self.density < 0.0:
            errors.append("밀도는 음수일 수 없습니다.")
        return errors

    def with_changes(self, **changes: object) -> "MaterialDefinition":
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class ShearDeformationSettings:
    """Project option later consumed by section and element formulations."""

    enabled: bool = False
    modulus_mode: ShearModulusMode = ShearModulusMode.DERIVED_FROM_POISSON
    user_shear_modulus: float | None = None
    correction_factor_y: float = 5.0 / 6.0
    correction_factor_z: float = 5.0 / 6.0

    def effective_shear_modulus(self, material: MaterialDefinition) -> float | None:
        if self.modulus_mode == ShearModulusMode.USER_DEFINED:
            return self.user_shear_modulus
        return material.derived_shear_modulus

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.enabled:
            return errors
        if self.modulus_mode == ShearModulusMode.USER_DEFINED and (
            self.user_shear_modulus is None or self.user_shear_modulus <= 0.0
        ):
            errors.append("사용자 정의 전단탄성계수 G는 0보다 커야 합니다.")
        if self.correction_factor_y <= 0.0 or self.correction_factor_z <= 0.0:
            errors.append("전단보정계수는 0보다 커야 합니다.")
        return errors
