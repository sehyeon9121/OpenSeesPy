"""Read the Material & Section Master DB spreadsheet into domain records.

The spreadsheet is the single source of truth (see the module docstring on
``openframe.core.domain.material_section_db``). This module only translates
its rows into that domain model - it never invents a value the sheet does
not already contain, and it raises loudly (``MaterialSectionDBError`` and
subclasses) on anything that looks like a data problem rather than quietly
tolerating it.

``openpyxl`` is imported lazily inside :func:`load_database_from_excel` so
that the cache-hit path (see ``cache.py``) never needs it at runtime.
"""

import datetime
from collections.abc import Callable, Iterator, Mapping
from itertools import pairwise
from pathlib import Path
from typing import Any

from openframe.core.domain.material_section_db import (
    DataStatus,
    DuplicateRecordError,
    MaterialDatabase,
    MaterialRecord,
    MaterialSectionDBError,
    PropertyRule,
    PropertyType,
    RCSectionRecord,
    SectionRecord,
    Source,
)
from openframe.core.domain.units import density_kg_m3_to_unit_weight_kN_m3

#: Sections columns mapped to named ``SectionRecord`` fields - everything
#: else in a row becomes a ``dimensions`` entry (see ``_read_sections``).
_SECTION_KNOWN_COLUMNS = frozenset(
    {
        "section_id",
        "category",
        "shape",
        "designation",
        "compatible_material_category",
        "dimensions",
        "area_mm2",
        "Iy_mm4",
        "Iz_mm4",
        "J_mm4",
        "property_source",
        "mass_per_length_kg_m",
        "unit_weight_per_length_kN_m",
        "source_id",
    }
)

#: Relative tolerance for cross-checking the sheet's own unit_weight_kN_m3
#: against a fresh density*gravity/1000 computation - a sanity check, not a
#: correction: the sheet's stored value is always what gets used regardless.
_UNIT_WEIGHT_RELATIVE_TOLERANCE = 1.0e-6


def load_database_from_excel(path: Path) -> MaterialDatabase:
    import openpyxl  # kept off the cache-hit import path

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    warnings: list[str] = []

    meta = _read_meta(workbook["Meta"])
    gravity = float(meta.get("DATABASE", {}).get("GRAVITY", 9.80665))

    sources = _read_sources(workbook["Sources"])
    materials = _read_materials(workbook["Materials"])
    property_rules = _read_property_rules(workbook["PropertyRules"])
    sections = _read_sections(workbook["Sections"])
    rc_sections = _read_rc_sections(workbook["RC_Sections"])
    meta["validation_report"] = _read_validation(workbook["Validation"])

    _check_dangling_references(
        materials=materials,
        sections=sections,
        rc_sections=rc_sections,
        property_rules=property_rules,
        sources=sources,
        warnings=warnings,
    )
    _check_unit_weight_consistency(materials, gravity, warnings)
    _check_property_rule_overlaps(property_rules, warnings)
    _carry_forward_validation_notices(meta["validation_report"], warnings)

    pending = sorted(
        material_id
        for material_id, material in materials.items()
        if not material.auto_appliable
    )
    if pending:
        warnings.append(
            f"{len(pending)}개 재료가 자동 적용 차단 상태입니다 "
            f"(auto_apply=False 또는 data_status != VERIFIED): {', '.join(pending)}"
        )

    return MaterialDatabase(
        materials=materials,
        sections=sections,
        rc_sections=rc_sections,
        property_rules=property_rules,
        sources=sources,
        meta=meta,
        warnings=tuple(warnings),
    )


# -- generic sheet reading -----------------------------------------------


def _read_rows(worksheet: Any) -> Iterator[dict[str, Any]]:
    rows = worksheet.iter_rows(values_only=True)
    header = next(rows)
    for raw_row in rows:
        if all(value is None for value in raw_row):
            continue
        yield dict(zip(header, raw_row, strict=True))


def _unique_index[T](
    records: list[T], key: Callable[[T], str], table: str
) -> dict[str, T]:
    index: dict[str, T] = {}
    duplicate_ids: list[str] = []
    for record in records:
        record_id = key(record)
        if record_id in index:
            duplicate_ids.append(record_id)
        index[record_id] = record
    if duplicate_ids:
        raise DuplicateRecordError(table, tuple(sorted(set(duplicate_ids))))
    return index


def _float_or_none(value: Any, *, context: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass - reject it explicitly
        raise MaterialSectionDBError(f"{context}: 숫자여야 하는 값이 불리언입니다: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    raise MaterialSectionDBError(f"{context}: 숫자여야 하는 값이 아닙니다: {value!r}")


def _int_or_none(value: Any, *, context: str) -> int | None:
    as_float = _float_or_none(value, context=context)
    return None if as_float is None else int(as_float)


def _bool_required(value: Any, *, context: str) -> bool:
    if isinstance(value, bool):
        return value
    raise MaterialSectionDBError(f"{context}: True/False 값이어야 합니다: {value!r}")


def _inclusive_flag_or_none(value: Any, *, bound_value: float | None, context: str) -> bool | None:
    """An interval's inclusive/exclusive flag is meaningless on an unbounded
    side - the sheet leaves it blank there, so ``None`` is only accepted when
    the matching ``min_value``/``max_value`` is itself ``None``."""
    if bound_value is None:
        return None
    return _bool_required(value, context=context)


def _str_required(value: Any, *, context: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise MaterialSectionDBError(f"{context}: 비어 있을 수 없는 문자열 필드입니다: {value!r}")


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


# -- Materials -------------------------------------------------------------


def _read_materials(worksheet: Any) -> dict[str, MaterialRecord]:
    records: list[MaterialRecord] = []
    for row in _read_rows(worksheet):
        material_id = _str_required(row["material_id"], context="Materials.material_id")
        context = f"Materials[{material_id}]"
        try:
            property_type = PropertyType(row["property_type"])
        except ValueError as error:
            raise MaterialSectionDBError(
                f"{context}: 알 수 없는 property_type입니다: {row['property_type']!r}"
            ) from error
        try:
            data_status = DataStatus(row["data_status"])
        except ValueError as error:
            raise MaterialSectionDBError(
                f"{context}: 알 수 없는 data_status입니다: {row['data_status']!r}"
            ) from error
        records.append(
            MaterialRecord(
                material_id=material_id,
                category=_str_required(row["category"], context=f"{context}.category"),
                grade=_str_required(row["grade"], context=f"{context}.grade"),
                name=_str_required(row["name"], context=f"{context}.name"),
                fck_MPa=_float_or_none(row["fck_MPa"], context=f"{context}.fck_MPa"),
                E_MPa=_float_or_none(row["E_MPa"], context=f"{context}.E_MPa"),
                density_kg_m3=_float_or_none(row["density_kg_m3"], context=f"{context}.density_kg_m3"),
                unit_weight_kN_m3=_float_or_none(
                    row["unit_weight_kN_m3"], context=f"{context}.unit_weight_kN_m3"
                ),
                design_unit_weight_kN_m3=_float_or_none(
                    row["design_unit_weight_kN_m3"], context=f"{context}.design_unit_weight_kN_m3"
                ),
                poisson_ratio=_float_or_none(row["poisson_ratio"], context=f"{context}.poisson_ratio"),
                fy_MPa=_float_or_none(row["fy_MPa"], context=f"{context}.fy_MPa"),
                fu_MPa=_float_or_none(row["fu_MPa"], context=f"{context}.fu_MPa"),
                property_type=property_type,
                data_status=data_status,
                auto_apply=_bool_required(row["auto_apply"], context=f"{context}.auto_apply"),
                standard=_str_or_none(row["standard"]),
                source_id=_str_or_none(row["source_id"]),
                note=_str_or_none(row["note"]),
            )
        )
    return _unique_index(records, key=lambda material: material.material_id, table="Materials")


# -- PropertyRules -----------------------------------------------------------


def _read_property_rules(worksheet: Any) -> tuple[PropertyRule, ...]:
    rules: list[PropertyRule] = []
    for index, row in enumerate(_read_rows(worksheet), start=2):
        context = f"PropertyRules[row {index}]"
        min_value = _float_or_none(row["min_value"], context=f"{context}.min_value")
        max_value = _float_or_none(row["max_value"], context=f"{context}.max_value")
        rules.append(
            PropertyRule(
                material_id=_str_required(row["material_id"], context=f"{context}.material_id"),
                property_name=_str_required(row["property_name"], context=f"{context}.property_name"),
                condition_type=_str_required(row["condition_type"], context=f"{context}.condition_type"),
                min_value=min_value,
                min_inclusive=_inclusive_flag_or_none(
                    row["min_inclusive"], bound_value=min_value, context=f"{context}.min_inclusive"
                ),
                max_value=max_value,
                max_inclusive=_inclusive_flag_or_none(
                    row["max_inclusive"], bound_value=max_value, context=f"{context}.max_inclusive"
                ),
                condition_unit=_str_or_none(row["condition_unit"]),
                product_form=_str_or_none(row["product_form"]),
                section_part=_str_or_none(row["section_part"]),
                property_value=_float_or_none(row["property_value"], context=f"{context}.property_value"),
                property_unit=_str_or_none(row["property_unit"]),
                source_id=_str_or_none(row["source_id"]),
                note=_str_or_none(row["note"]),
            )
        )
    return tuple(rules)


# -- Sections ----------------------------------------------------------------


def _read_sections(worksheet: Any) -> dict[str, SectionRecord]:
    records: list[SectionRecord] = []
    for row in _read_rows(worksheet):
        section_id = _str_required(row["section_id"], context="Sections.section_id")
        context = f"Sections[{section_id}]"
        dimensions: dict[str, float] = {}
        for key, value in row.items():
            if key in _SECTION_KNOWN_COLUMNS or value is None:
                continue
            dimensions[key] = _float_or_none(value, context=f"{context}.{key}")
        records.append(
            SectionRecord(
                section_id=section_id,
                category=_str_required(row["category"], context=f"{context}.category"),
                shape=_str_required(row["shape"], context=f"{context}.shape"),
                designation=_str_required(row["designation"], context=f"{context}.designation"),
                compatible_material_category=_str_or_none(row["compatible_material_category"]),
                dimensions_text=_str_or_none(row["dimensions"]),
                area_mm2=_float_or_none(row["area_mm2"], context=f"{context}.area_mm2"),
                Iy_mm4=_float_or_none(row["Iy_mm4"], context=f"{context}.Iy_mm4"),
                Iz_mm4=_float_or_none(row["Iz_mm4"], context=f"{context}.Iz_mm4"),
                J_mm4=_float_or_none(row["J_mm4"], context=f"{context}.J_mm4"),
                property_source=_str_or_none(row["property_source"]),
                mass_per_length_kg_m=_float_or_none(
                    row["mass_per_length_kg_m"], context=f"{context}.mass_per_length_kg_m"
                ),
                unit_weight_per_length_kN_m=_float_or_none(
                    row["unit_weight_per_length_kN_m"],
                    context=f"{context}.unit_weight_per_length_kN_m",
                ),
                source_id=_str_or_none(row["source_id"]),
                dimensions=dimensions,
            )
        )
    return _unique_index(records, key=lambda section: section.section_id, table="Sections")


# -- RC_Sections ---------------------------------------------------------------


def _read_rc_sections(worksheet: Any) -> dict[str, RCSectionRecord]:
    records: list[RCSectionRecord] = []
    for row in _read_rows(worksheet):
        section_id = _str_required(row["section_id"], context="RC_Sections.section_id")
        context = f"RC_Sections[{section_id}]"
        records.append(
            RCSectionRecord(
                section_id=section_id,
                section_type=_str_required(row["section_type"], context=f"{context}.section_type"),
                member_type=_str_or_none(row["member_type"]),
                width_mm=_float_or_none(row["width_mm"], context=f"{context}.width_mm"),
                height_mm=_float_or_none(row["height_mm"], context=f"{context}.height_mm"),
                diameter_mm=_float_or_none(row["diameter_mm"], context=f"{context}.diameter_mm"),
                concrete_material_id=_str_required(
                    row["concrete_material_id"], context=f"{context}.concrete_material_id"
                ),
                rebar_material_id=_str_required(
                    row["rebar_material_id"], context=f"{context}.rebar_material_id"
                ),
                cover_mm=_float_or_none(row["cover_mm"], context=f"{context}.cover_mm"),
                longitudinal_bar_diameter=_float_or_none(
                    row["longitudinal_bar_diameter"], context=f"{context}.longitudinal_bar_diameter"
                ),
                longitudinal_bar_count=_int_or_none(
                    row["longitudinal_bar_count"], context=f"{context}.longitudinal_bar_count"
                ),
                stirrup_diameter=_float_or_none(
                    row["stirrup_diameter"], context=f"{context}.stirrup_diameter"
                ),
                stirrup_spacing=_float_or_none(
                    row["stirrup_spacing"], context=f"{context}.stirrup_spacing"
                ),
                note=_str_or_none(row["note"]),
            )
        )
    return _unique_index(records, key=lambda rc: rc.section_id, table="RC_Sections")


# -- Sources -------------------------------------------------------------------


def _read_sources(worksheet: Any) -> dict[str, Source]:
    records: list[Source] = []
    for row in _read_rows(worksheet):
        source_id = _str_required(row["source_id"], context="Sources.source_id")
        records.append(
            Source(
                source_id=source_id,
                organization=_str_or_none(row["organization"]),
                standard_or_document=_str_or_none(row["standard_or_document"]),
                edition=_str_or_none(row["edition"]),
                table_or_section=_str_or_none(row["table_or_section"]),
                description=_str_or_none(row["description"]),
                reference=_str_or_none(row["reference"]),
            )
        )
    return _unique_index(records, key=lambda source: source.source_id, table="Sources")


# -- Meta / Validation -----------------------------------------------------


def _json_safe(value: Any) -> Any:
    """Normalize a raw cell value to a type that round-trips through the
    JSON cache unchanged, so Excel-load and cache-load return identical
    types regardless of which path was taken."""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def _read_meta(worksheet: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for row in _read_rows(worksheet):
        group = _str_required(row["meta_group"], context="Meta.meta_group")
        key = row["key"]
        value = _json_safe(row["value"])
        if group in ("PROPERTY_TYPE", "DATA_STATUS"):
            meta.setdefault(group, []).append(value)
        else:
            meta.setdefault(group, {})[key] = value
    return meta


def _read_validation(worksheet: Any) -> tuple[dict[str, Any], ...]:
    return tuple(
        {key: _json_safe(value) for key, value in row.items()} for row in _read_rows(worksheet)
    )


# -- cross-sheet validation --------------------------------------------------


def _check_dangling_references(
    *,
    materials: Mapping[str, MaterialRecord],
    sections: Mapping[str, SectionRecord],
    rc_sections: Mapping[str, RCSectionRecord],
    property_rules: tuple[PropertyRule, ...],
    sources: Mapping[str, Source],
    warnings: list[str],
) -> None:
    for rule in property_rules:
        if rule.material_id not in materials:
            warnings.append(
                f"PropertyRules 행이 존재하지 않는 material_id를 참조합니다: {rule.material_id}"
            )
        if rule.source_id is not None and rule.source_id not in sources:
            warnings.append(
                f"PropertyRules({rule.material_id}/{rule.property_name}) 행의 source_id가 "
                f"Sources에 없습니다: {rule.source_id}"
            )
    for rc_section in rc_sections.values():
        for material_id in (rc_section.concrete_material_id, rc_section.rebar_material_id):
            if material_id not in materials:
                warnings.append(
                    f"RC_Sections[{rc_section.section_id}]가 존재하지 않는 "
                    f"material_id를 참조합니다: {material_id}"
                )
    for material in materials.values():
        if material.source_id is not None and material.source_id not in sources:
            warnings.append(
                f"Materials[{material.material_id}]의 source_id가 Sources에 없습니다: "
                f"{material.source_id}"
            )
    for section in sections.values():
        if section.source_id is not None and section.source_id not in sources:
            warnings.append(
                f"Sections[{section.section_id}]의 source_id가 Sources에 없습니다: "
                f"{section.source_id}"
            )


def _check_unit_weight_consistency(
    materials: Mapping[str, MaterialRecord], gravity: float, warnings: list[str]
) -> None:
    for material in materials.values():
        if material.density_kg_m3 is None or material.unit_weight_kN_m3 is None:
            continue
        expected = density_kg_m3_to_unit_weight_kN_m3(material.density_kg_m3, gravity)
        actual = material.unit_weight_kN_m3
        if expected == 0:
            continue
        relative_error = abs(actual - expected) / abs(expected)
        if relative_error > _UNIT_WEIGHT_RELATIVE_TOLERANCE:
            warnings.append(
                f"Materials[{material.material_id}] unit_weight_kN_m3={actual}가 "
                f"density_kg_m3={material.density_kg_m3} * g/1000={expected}와 다릅니다 "
                "(상대오차 > 1e-6). Excel 값은 그대로 사용하지만 확인이 필요합니다."
            )


def _check_property_rule_overlaps(
    property_rules: tuple[PropertyRule, ...], warnings: list[str]
) -> None:
    groups: dict[tuple[str, str], list[PropertyRule]] = {}
    for rule in property_rules:
        groups.setdefault((rule.material_id, rule.property_name), []).append(rule)
    for (material_id, property_name), rules in groups.items():
        ordered = sorted(rules, key=lambda rule: (rule.min_value is None, rule.min_value or 0.0))
        for first, second in pairwise(ordered):
            if first.max_value is None or second.min_value is None:
                continue
            if second.min_value < first.max_value or (
                second.min_value == first.max_value
                and first.max_inclusive
                and second.min_inclusive
            ):
                warnings.append(
                    f"PropertyRules({material_id}/{property_name}) 구간이 겹칩니다: "
                    f"({first.min_value}, {first.max_value}] / ({second.min_value}, {second.max_value}]"
                )


def _carry_forward_validation_notices(
    validation_rows: tuple[dict[str, Any], ...], warnings: list[str]
) -> None:
    for row in validation_rows:
        result = row.get("result")
        if result and str(result).upper() not in ("PASS",):
            warnings.append(f"[{row.get('check_id')}] {row.get('message')} (result={result})")
