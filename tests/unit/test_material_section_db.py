"""Pure unit tests for the Material & Section Master DB domain model.

These only import ``openframe.core.domain`` and the loader's internal
``_unique_index`` helper directly - no Excel file, no Qt. Records are built
by hand so each scenario (CONDITIONAL with a matching rule, PENDING data
blocked from auto-apply, an unknown material_id, ...) is isolated from the
real spreadsheet's actual content, which is covered separately in
``test_material_section_db_loader.py``.
"""

import pytest

from openframe.core.domain import (
    DataStatus,
    DuplicateRecordError,
    MaterialDatabase,
    MaterialRecord,
    PropertyResolutionStatus,
    PropertyRule,
    PropertyType,
    RCSectionRecord,
    RecordNotFoundError,
    SectionRecord,
    density_kg_m3_to_unit_weight_kN_m3,
)
from openframe.core.domain.material_section_db import UnsupportedConditionTypeError
from openframe.infrastructure.material_section_db.excel_loader import _unique_index


def _material(
    material_id: str,
    *,
    property_type: PropertyType = PropertyType.CONSTANT,
    data_status: DataStatus = DataStatus.VERIFIED,
    auto_apply: bool = True,
    E_MPa: float | None = 200000.0,
    fy_MPa: float | None = None,
    category: str = "Structural Steel",
) -> MaterialRecord:
    return MaterialRecord(
        material_id=material_id,
        category=category,
        grade=material_id,
        name=material_id,
        fck_MPa=None,
        E_MPa=E_MPa,
        density_kg_m3=7850.0,
        unit_weight_kN_m3=76.9822025,
        design_unit_weight_kN_m3=None,
        poisson_ratio=0.3,
        fy_MPa=fy_MPa,
        fu_MPa=None,
        property_type=property_type,
        data_status=data_status,
        auto_apply=auto_apply,
        standard=None,
        source_id=None,
        note=None,
    )


def _rule(
    material_id: str,
    property_name: str,
    *,
    min_value: float | None,
    min_inclusive: bool | None,
    max_value: float | None,
    max_inclusive: bool | None,
    property_value: float | None,
) -> PropertyRule:
    return PropertyRule(
        material_id=material_id,
        property_name=property_name,
        condition_type="thickness_range",
        min_value=min_value,
        min_inclusive=min_inclusive,
        max_value=max_value,
        max_inclusive=max_inclusive,
        condition_unit="mm",
        product_form=None,
        section_part=None,
        property_value=property_value,
        property_unit="MPa",
        source_id=None,
        note=None,
    )


def _section(section_id: str, category: str = "User Defined") -> SectionRecord:
    return SectionRecord(
        section_id=section_id,
        category=category,
        shape="Rectangle",
        designation=section_id,
        compatible_material_category=category,
        dimensions_text="b=300; h=500",
        area_mm2=150000.0,
        Iy_mm4=None,
        Iz_mm4=None,
        J_mm4=None,
        property_source="CALCULATED",
        mass_per_length_kg_m=None,
        unit_weight_per_length_kN_m=None,
        source_id=None,
    )


def _empty_database(
    materials: dict[str, MaterialRecord] | None = None,
    property_rules: tuple[PropertyRule, ...] = (),
    sections: dict[str, SectionRecord] | None = None,
    rc_sections: dict[str, RCSectionRecord] | None = None,
) -> MaterialDatabase:
    return MaterialDatabase(
        materials=materials or {},
        sections=sections or {},
        rc_sections=rc_sections or {},
        property_rules=property_rules,
        sources={},
        meta={},
    )


# -- MaterialRecord.auto_appliable ---------------------------------------


def test_verified_and_auto_apply_true_is_auto_appliable() -> None:
    material = _material("M1", data_status=DataStatus.VERIFIED, auto_apply=True)
    assert material.auto_appliable is True


def test_pending_blocks_auto_apply_even_when_auto_apply_flag_is_true() -> None:
    material = _material("M1", data_status=DataStatus.PENDING, auto_apply=True)
    assert material.auto_appliable is False


def test_auto_apply_false_blocks_auto_apply_even_when_verified() -> None:
    material = _material("M1", data_status=DataStatus.VERIFIED, auto_apply=False)
    assert material.auto_appliable is False


def test_user_defined_status_blocks_auto_apply() -> None:
    material = _material(
        "M1", property_type=PropertyType.USER_DEFINED, data_status=DataStatus.USER_DEFINED,
        auto_apply=False,
    )
    assert material.auto_appliable is False


# -- resolve_property: CONSTANT / missing value --------------------------


def test_resolve_property_returns_the_raw_column_value_for_a_constant_material() -> None:
    db = _empty_database(materials={"M1": _material("M1", E_MPa=200000.0)})

    result = db.resolve_property("M1", "E_MPa")

    assert result.status is PropertyResolutionStatus.RESOLVED_CONSTANT
    assert result.value == 200000.0


def test_resolve_property_never_fabricates_a_value_for_an_empty_cell() -> None:
    db = _empty_database(materials={"M1": _material("M1", fy_MPa=None)})

    result = db.resolve_property("M1", "fy_MPa")

    assert result.status is PropertyResolutionStatus.VALUE_MISSING
    assert result.value is None


def test_resolve_property_blocks_auto_apply_for_pending_data_even_with_a_value() -> None:
    db = _empty_database(
        materials={"M1": _material("M1", data_status=DataStatus.PENDING, auto_apply=False)}
    )

    result = db.resolve_property("M1", "E_MPa")

    assert result.value == 200000.0
    assert result.auto_appliable is False


def test_resolve_property_rejects_an_unknown_property_name() -> None:
    db = _empty_database(materials={"M1": _material("M1")})

    with pytest.raises(ValueError, match="property_name"):
        db.resolve_property("M1", "not_a_real_field")


# -- resolve_property: CONDITIONAL / PropertyRules -----------------------


def test_resolve_property_uses_the_matching_rule_interval() -> None:
    rules = (
        _rule("M1", "fy_MPa", min_value=0, min_inclusive=False, max_value=16, max_inclusive=True, property_value=275.0),
        _rule("M1", "fy_MPa", min_value=16, min_inclusive=False, max_value=40, max_inclusive=True, property_value=255.0),
    )
    db = _empty_database(
        materials={"M1": _material("M1", property_type=PropertyType.CONDITIONAL, fy_MPa=None)},
        property_rules=rules,
    )

    thin = db.resolve_property("M1", "fy_MPa", context={"thickness_mm": 10})
    thick = db.resolve_property("M1", "fy_MPa", context={"thickness_mm": 30})

    assert (thin.status, thin.value) == (PropertyResolutionStatus.RESOLVED_BY_RULE, 275.0)
    assert (thick.status, thick.value) == (PropertyResolutionStatus.RESOLVED_BY_RULE, 255.0)


def test_resolve_property_reports_missing_context_separately_from_no_matching_rule() -> None:
    rules = (
        _rule("M1", "fy_MPa", min_value=0, min_inclusive=False, max_value=16, max_inclusive=True, property_value=275.0),
    )
    db = _empty_database(
        materials={"M1": _material("M1", property_type=PropertyType.CONDITIONAL, fy_MPa=None)},
        property_rules=rules,
    )

    no_context = db.resolve_property("M1", "fy_MPa")
    out_of_range = db.resolve_property("M1", "fy_MPa", context={"thickness_mm": 999})

    assert no_context.status is PropertyResolutionStatus.MISSING_CONTEXT
    assert out_of_range.status is PropertyResolutionStatus.NO_MATCHING_RULE


def test_resolve_property_reports_rule_value_missing_without_fabricating_one() -> None:
    rules = (
        _rule("M1", "fy_MPa", min_value=0, min_inclusive=False, max_value=16, max_inclusive=True, property_value=None),
    )
    db = _empty_database(
        materials={"M1": _material("M1", property_type=PropertyType.CONDITIONAL, fy_MPa=None)},
        property_rules=rules,
    )

    result = db.resolve_property("M1", "fy_MPa", context={"thickness_mm": 10})

    assert result.status is PropertyResolutionStatus.RULE_VALUE_MISSING
    assert result.value is None


def test_property_rule_matches_respects_inclusive_and_exclusive_bounds() -> None:
    rule = _rule("M1", "fy_MPa", min_value=0, min_inclusive=False, max_value=16, max_inclusive=True, property_value=275.0)

    assert rule.matches({"thickness_mm": 0}) is False  # exclusive lower bound
    assert rule.matches({"thickness_mm": 0.001}) is True
    assert rule.matches({"thickness_mm": 16}) is True  # inclusive upper bound
    assert rule.matches({"thickness_mm": 16.001}) is False


def test_property_rule_matches_returns_false_rather_than_raising_when_context_key_absent() -> None:
    rule = _rule("M1", "fy_MPa", min_value=0, min_inclusive=False, max_value=16, max_inclusive=True, property_value=275.0)

    assert rule.matches({}) is False


def test_unsupported_condition_type_raises_instead_of_silently_matching() -> None:
    rule = _rule("M1", "fy_MPa", min_value=0, min_inclusive=False, max_value=16, max_inclusive=True, property_value=275.0)
    object.__setattr__(rule, "condition_type", "made_up_condition")

    with pytest.raises(UnsupportedConditionTypeError):
        rule.matches({"thickness_mm": 5})


# -- USER_DEFINED ----------------------------------------------------------


def test_user_defined_material_never_resolves_a_value_regardless_of_property() -> None:
    db = _empty_database(
        materials={
            "USER-DEFINED": _material(
                "USER-DEFINED",
                property_type=PropertyType.USER_DEFINED,
                data_status=DataStatus.USER_DEFINED,
                auto_apply=False,
                E_MPa=None,
            )
        }
    )

    result = db.resolve_property("USER-DEFINED", "E_MPa")

    assert result.status is PropertyResolutionStatus.USER_DEFINED
    assert result.value is None
    assert result.auto_appliable is False


# -- Not-found lookups -----------------------------------------------------


def test_get_material_raises_for_an_unknown_id() -> None:
    db = _empty_database()

    with pytest.raises(RecordNotFoundError):
        db.get_material("DOES-NOT-EXIST")


def test_get_section_raises_for_an_unknown_id() -> None:
    db = _empty_database()

    with pytest.raises(RecordNotFoundError):
        db.get_section("DOES-NOT-EXIST")


def test_get_rc_section_raises_for_an_unknown_id() -> None:
    db = _empty_database()

    with pytest.raises(RecordNotFoundError):
        db.get_rc_section("DOES-NOT-EXIST")


def test_resolve_property_raises_for_an_unknown_material_id() -> None:
    db = _empty_database()

    with pytest.raises(RecordNotFoundError):
        db.resolve_property("DOES-NOT-EXIST", "E_MPa")


# -- Duplicate id detection --------------------------------------------------


def test_unique_index_raises_on_duplicate_ids_instead_of_dropping_a_row() -> None:
    records = [_material("DUP"), _material("DUP"), _material("OK")]

    with pytest.raises(DuplicateRecordError) as excinfo:
        _unique_index(records, key=lambda material: material.material_id, table="Materials")

    assert "DUP" in str(excinfo.value)


def test_unique_index_accepts_a_list_with_no_duplicates() -> None:
    records = [_material("A"), _material("B")]

    index = _unique_index(records, key=lambda material: material.material_id, table="Materials")

    assert set(index) == {"A", "B"}


# -- Section/Material independence and composition --------------------------


def test_compose_member_warns_on_a_category_mismatch() -> None:
    db = _empty_database(
        materials={"CONC-C24": _material("CONC-C24", category="Concrete")},
        sections={"SEC-H-300": _section("SEC-H-300", category="Structural Steel")},
    )

    composition = db.compose_member("CONC-C24", "SEC-H-300")

    assert composition.compatibility_warning is not None


def test_compose_member_does_not_warn_for_a_user_defined_section() -> None:
    db = _empty_database(
        materials={"CONC-C24": _material("CONC-C24", category="Concrete")},
        sections={"SEC-RECT": _section("SEC-RECT", category="User Defined")},
    )

    composition = db.compose_member("CONC-C24", "SEC-RECT")

    assert composition.compatibility_warning is None


def test_section_record_carries_no_material_reference() -> None:
    section = _section("SEC-RECT")
    assert not hasattr(section, "material_id")
    assert not hasattr(section, "E_MPa")


# -- Unit conversion --------------------------------------------------------


def test_density_to_unit_weight_matches_the_master_db_formula() -> None:
    # Master DB's own Materials!H2 formula: =G2*Meta!$C$5/1000, Meta GRAVITY=9.80665.
    assert density_kg_m3_to_unit_weight_kN_m3(2400.0, 9.80665) == pytest.approx(23.53596)


def test_density_and_unit_weight_are_distinct_fields() -> None:
    material = _material("M1")
    assert material.density_kg_m3 != material.unit_weight_kN_m3
    assert hasattr(material, "density_kg_m3")
    assert hasattr(material, "unit_weight_kN_m3")
    assert hasattr(material, "design_unit_weight_kN_m3")
