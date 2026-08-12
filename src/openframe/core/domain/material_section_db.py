"""Material & Section master database domain model.

Framework-independent representation of the external Master DB spreadsheet
(``Materials`` / ``PropertyRules`` / ``Sections`` / ``RC_Sections`` /
``Sources`` sheets). The spreadsheet is the authoritative source of truth;
this module only describes the shape of that data and the rules for
resolving a material property from it. Reading the actual Excel/JSON cache
files is an infrastructure concern (see
``openframe.infrastructure.material_section_db``) and never happens here.

Section and Material stay independent on purpose (a ``SectionRecord`` never
embeds a material, and vice versa) so that geometry and material properties
can be combined freely when a real member is created - see
``MaterialDatabase.compose_member``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "DataStatus",
    "DuplicateRecordError",
    "MaterialDatabase",
    "MaterialRecord",
    "MaterialSectionComposition",
    "MaterialSectionDBError",
    "PropertyResolution",
    "PropertyResolutionStatus",
    "PropertyRule",
    "PropertyType",
    "RCSectionRecord",
    "RecordNotFoundError",
    "SectionRecord",
    "Source",
    "UnsupportedConditionTypeError",
]


class MaterialSectionDBError(Exception):
    """Base class for every Master DB domain error."""


class RecordNotFoundError(MaterialSectionDBError, KeyError):
    """A lookup was made for an id that does not exist in the database."""

    def __init__(self, table: str, record_id: str) -> None:
        super().__init__(f"{table}에 존재하지 않는 id입니다: {record_id!r}")
        self.table = table
        self.record_id = record_id


class DuplicateRecordError(MaterialSectionDBError):
    """The same id appears more than once in a sheet that requires unique ids.

    Silently keeping "last row wins" (what a naive ``dict`` build would do)
    would quietly drop data - this is raised instead so the conflict is
    impossible to miss.
    """

    def __init__(self, table: str, duplicate_ids: tuple[str, ...]) -> None:
        listed = ", ".join(duplicate_ids)
        super().__init__(f"{table}에 중복된 id가 있습니다: {listed}")
        self.table = table
        self.duplicate_ids = duplicate_ids


class UnsupportedConditionTypeError(MaterialSectionDBError):
    """A ``PropertyRules`` row uses a ``condition_type`` this module cannot
    evaluate. Raised rather than guessed at, since silently ignoring the
    condition would mean fabricating a match."""

    def __init__(self, condition_type: str) -> None:
        super().__init__(f"지원하지 않는 PropertyRules condition_type입니다: {condition_type!r}")
        self.condition_type = condition_type


class PropertyType(StrEnum):
    """How a ``MaterialRecord``'s properties were determined - see the
    ``Meta`` sheet's ``PROPERTY_TYPE`` enum declaration."""

    CONSTANT = "CONSTANT"
    FORMULA = "FORMULA"
    CONDITIONAL = "CONDITIONAL"
    USER_DEFINED = "USER_DEFINED"


class DataStatus(StrEnum):
    """Review state of a ``MaterialRecord`` - see the ``Meta`` sheet's
    ``DATA_STATUS`` enum declaration."""

    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    USER_DEFINED = "USER_DEFINED"


class PropertyResolutionStatus(StrEnum):
    """Outcome of :meth:`MaterialDatabase.resolve_property`."""

    #: Read directly from the material's own column (CONSTANT/FORMULA rows).
    RESOLVED_CONSTANT = "RESOLVED_CONSTANT"
    #: A ``PropertyRules`` interval matched the given context and carried a value.
    RESOLVED_BY_RULE = "RESOLVED_BY_RULE"
    #: The material is CONDITIONAL for this property, but the caller did not
    #: supply the context value the rules are keyed on (e.g. thickness).
    MISSING_CONTEXT = "MISSING_CONTEXT"
    #: Context was supplied, but no rule interval covers it.
    NO_MATCHING_RULE = "NO_MATCHING_RULE"
    #: A rule interval matched, but its own ``property_value`` cell is empty.
    RULE_VALUE_MISSING = "RULE_VALUE_MISSING"
    #: The material's own column for this property is empty - never fabricated.
    VALUE_MISSING = "VALUE_MISSING"
    #: The material itself is the ``USER_DEFINED`` placeholder row.
    USER_DEFINED = "USER_DEFINED"


#: Maps a PropertyRules ``condition_type`` to the ``context`` key
#: ``resolve_property`` expects it under. The only condition type the
#: current Master DB uses is a thickness range.
_CONDITION_CONTEXT_KEYS: dict[str, str] = {"thickness_range": "thickness_mm"}


@dataclass(frozen=True, slots=True)
class Source:
    """One row from ``Sources`` - the provenance a Material/Section traces back to."""

    source_id: str
    organization: str | None
    standard_or_document: str | None
    edition: str | None
    table_or_section: str | None
    description: str | None
    reference: str | None


@dataclass(frozen=True, slots=True)
class PropertyRule:
    """One conditional-value row from ``PropertyRules``.

    ``min_value``/``max_value`` bound the interval this rule applies to,
    inclusive/exclusive per their own flags; ``None`` means unbounded on
    that side. A ``property_value`` of ``None`` means the Master DB has not
    filled in a value for this interval yet - callers must never invent one.
    """

    material_id: str
    property_name: str
    condition_type: str
    min_value: float | None
    #: ``None`` exactly when ``min_value`` is ``None`` - an unbounded side has
    #: no inclusive/exclusive meaning, so the Master DB leaves it blank there.
    min_inclusive: bool | None
    max_value: float | None
    max_inclusive: bool | None
    condition_unit: str | None
    product_form: str | None
    section_part: str | None
    property_value: float | None
    property_unit: str | None
    source_id: str | None
    note: str | None

    @property
    def context_key(self) -> str:
        try:
            return _CONDITION_CONTEXT_KEYS[self.condition_type]
        except KeyError as error:
            raise UnsupportedConditionTypeError(self.condition_type) from error

    def matches(self, context: Mapping[str, float]) -> bool:
        """Whether ``context`` (e.g. ``{"thickness_mm": 12.0}``) falls inside
        this rule's interval. Returns ``False`` (never raises) when the
        required key is simply absent - ``resolve_property`` uses that to
        tell "no context given" apart from "context given, no rule covers it"."""
        key = self.context_key
        if key not in context:
            return False
        value = context[key]
        if self.min_value is not None:
            if self.min_inclusive:
                if value < self.min_value:
                    return False
            elif value <= self.min_value:
                return False
        if self.max_value is not None:
            if self.max_inclusive:
                if value > self.max_value:
                    return False
            elif value >= self.max_value:
                return False
        return True


@dataclass(frozen=True, slots=True)
class MaterialRecord:
    """One row from ``Materials``.

    Numeric fields are ``None`` exactly when the source cell is empty - no
    fallback is ever synthesized here (see ``auto_appliable`` for the
    separate question of whether a *present* value may be used automatically).
    """

    material_id: str
    category: str
    grade: str
    name: str
    fck_MPa: float | None
    E_MPa: float | None
    density_kg_m3: float | None
    unit_weight_kN_m3: float | None
    design_unit_weight_kN_m3: float | None
    poisson_ratio: float | None
    fy_MPa: float | None
    fu_MPa: float | None
    property_type: PropertyType
    data_status: DataStatus
    auto_apply: bool
    standard: str | None
    source_id: str | None
    note: str | None

    @property
    def auto_appliable(self) -> bool:
        """Whether this material's values may be wired into an automatic
        analysis input without a human reviewing them first.

        Requirement: ``auto_apply is False`` or ``data_status != VERIFIED``
        (which includes ``PENDING`` and ``USER_DEFINED``) both block
        automatic use, regardless of whether a numeric value happens to be
        present in the sheet."""
        return self.auto_apply and self.data_status is DataStatus.VERIFIED


@dataclass(frozen=True, slots=True)
class SectionRecord:
    """One row from ``Sections`` (pure geometry - no material reference).

    ``dimensions`` holds every populated shape-specific dimension column
    (``H_mm``, ``B_mm``, ``tw_mm``, ``tf_mm``, ``b_mm2``, ``h_mm3``, ``t_mm``,
    ``D_mm``, ``d_mm4``) verbatim under its original spreadsheet column name -
    which columns are populated depends entirely on ``shape`` and is not
    reinterpreted here, so a shape this module was not written to expect
    still comes through without guessing at a meaning for an odd column name.
    """

    section_id: str
    category: str
    shape: str
    designation: str
    compatible_material_category: str | None
    dimensions_text: str | None
    area_mm2: float | None
    Iy_mm4: float | None
    Iz_mm4: float | None
    J_mm4: float | None
    property_source: str | None
    mass_per_length_kg_m: float | None
    unit_weight_per_length_kN_m: float | None
    source_id: str | None
    dimensions: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RCSectionRecord:
    """One row from ``RC_Sections``.

    Deliberately not a single "RC material" - concrete and rebar stay two
    separate ``MaterialRecord`` references (resolved through
    :meth:`MaterialDatabase.get_material`), combined with geometry and a
    reinforcement layout, per the Master DB's own structure."""

    section_id: str
    section_type: str
    member_type: str | None
    width_mm: float | None
    height_mm: float | None
    diameter_mm: float | None
    concrete_material_id: str
    rebar_material_id: str
    cover_mm: float | None
    longitudinal_bar_diameter: float | None
    longitudinal_bar_count: int | None
    stirrup_diameter: float | None
    stirrup_spacing: float | None
    note: str | None


@dataclass(frozen=True, slots=True)
class PropertyResolution:
    """Result of :meth:`MaterialDatabase.resolve_property`.

    ``value`` may be populated even when ``auto_appliable`` is ``False`` -
    that combination means "here is the number, but it must be shown to a
    person for confirmation before it drives an analysis," which is exactly
    the PENDING/auto_apply=FALSE case the Master DB uses for most non-concrete
    materials."""

    material_id: str
    property_name: str
    status: PropertyResolutionStatus
    value: float | None
    unit: str | None
    property_type: PropertyType
    data_status: DataStatus
    auto_appliable: bool
    source_id: str | None
    note: str | None
    matched_rule: PropertyRule | None = None


@dataclass(frozen=True, slots=True)
class MaterialSectionComposition:
    """A material paired with a section for a real member.

    ``compatibility_warning`` is informational only (e.g. an H-section
    combined with a Concrete material) - composing is never blocked, since
    ``compatible_material_category`` is a hint the Master DB records, not a
    hard rule enforced elsewhere in OpenFrame."""

    material: MaterialRecord
    section: SectionRecord
    compatibility_warning: str | None


class MaterialDatabase:
    """In-memory, read-only query surface over one loaded Master DB snapshot.

    Construct this only through the infrastructure loader
    (``openframe.infrastructure.material_section_db.load_material_database``)
    - this class itself does no file I/O and trusts that whatever built it
    already validated shape (duplicate ids, etc.). ``warnings`` carries
    non-fatal data-quality notices collected while loading (e.g. the Master
    DB's own PENDING-count notice) for a caller to surface to the user.
    """

    def __init__(
        self,
        *,
        materials: Mapping[str, MaterialRecord],
        sections: Mapping[str, SectionRecord],
        rc_sections: Mapping[str, RCSectionRecord],
        property_rules: tuple[PropertyRule, ...],
        sources: Mapping[str, Source],
        meta: Mapping[str, object],
        warnings: tuple[str, ...] = (),
    ) -> None:
        self._materials = dict(materials)
        self._sections = dict(sections)
        self._rc_sections = dict(rc_sections)
        self._property_rules = property_rules
        self._sources = dict(sources)
        self.meta = dict(meta)
        self.warnings = warnings

    # -- Full snapshots (mainly for caching/serialization) --------------
    def all_materials(self) -> tuple[MaterialRecord, ...]:
        return tuple(self._materials.values())

    def all_sections(self) -> tuple[SectionRecord, ...]:
        return tuple(self._sections.values())

    def all_rc_sections(self) -> tuple[RCSectionRecord, ...]:
        return tuple(self._rc_sections.values())

    def all_property_rules(self) -> tuple[PropertyRule, ...]:
        return self._property_rules

    def all_sources(self) -> tuple[Source, ...]:
        return tuple(self._sources.values())

    # -- Materials ---------------------------------------------------
    def get_material_categories(self) -> tuple[str, ...]:
        return tuple(sorted({material.category for material in self._materials.values()}))

    def get_materials_by_category(self, category: str) -> tuple[MaterialRecord, ...]:
        return tuple(
            material
            for material in self._materials.values()
            if material.category == category
        )

    def get_material(self, material_id: str) -> MaterialRecord:
        try:
            return self._materials[material_id]
        except KeyError as error:
            raise RecordNotFoundError("Materials", material_id) from error

    # -- Sections ------------------------------------------------------
    def get_section_categories(self) -> tuple[str, ...]:
        return tuple(sorted({section.category for section in self._sections.values()}))

    def get_sections_by_category(self, category: str) -> tuple[SectionRecord, ...]:
        return tuple(
            section for section in self._sections.values() if section.category == category
        )

    def get_section(self, section_id: str) -> SectionRecord:
        try:
            return self._sections[section_id]
        except KeyError as error:
            raise RecordNotFoundError("Sections", section_id) from error

    # -- RC Sections -----------------------------------------------------
    def get_rc_section(self, section_id: str) -> RCSectionRecord:
        try:
            return self._rc_sections[section_id]
        except KeyError as error:
            raise RecordNotFoundError("RC_Sections", section_id) from error

    def get_rc_section_materials(
        self, section_id: str
    ) -> tuple[MaterialRecord, MaterialRecord]:
        """Return ``(concrete, rebar)`` for an RC section, resolved through
        :meth:`get_material` (so a dangling reference raises the same
        ``RecordNotFoundError`` a direct lookup would)."""
        rc_section = self.get_rc_section(section_id)
        return (
            self.get_material(rc_section.concrete_material_id),
            self.get_material(rc_section.rebar_material_id),
        )

    # -- Sources -----------------------------------------------------------
    def get_source(self, source_id: str) -> Source:
        try:
            return self._sources[source_id]
        except KeyError as error:
            raise RecordNotFoundError("Sources", source_id) from error

    # -- Composition ---------------------------------------------------
    def compose_member(self, material_id: str, section_id: str) -> MaterialSectionComposition:
        """Combine an independently-looked-up material and section.

        Requirement: section and material stay independent database entries;
        this is the one place they are paired for a real member."""
        material = self.get_material(material_id)
        section = self.get_section(section_id)
        warning: str | None = None
        compatible = section.compatible_material_category
        if compatible not in (None, "User Defined", material.category):
            warning = (
                f"단면 {section_id}는 {compatible} 재료용으로 등록되어 있으나, "
                f"{material_id}({material.category})와 조합되었습니다."
            )
        return MaterialSectionComposition(
            material=material, section=section, compatibility_warning=warning
        )

    # -- Property resolution -------------------------------------------
    def _rules_for(self, material_id: str, property_name: str) -> tuple[PropertyRule, ...]:
        return tuple(
            rule
            for rule in self._property_rules
            if rule.material_id == material_id and rule.property_name == property_name
        )

    def resolve_property(
        self,
        material_id: str,
        property_name: str,
        context: Mapping[str, float] | None = None,
    ) -> PropertyResolution:
        """Resolve one property of one material, dispatching on
        ``property_type``/``PropertyRules`` exactly as the Master DB defines
        them - see ``PropertyResolutionStatus`` for every possible outcome.

        ``context`` supplies whatever a CONDITIONAL property's rules are
        keyed on (currently only ``{"thickness_mm": ...}``). Never omit a
        value just because none was given - the returned status says exactly
        why no value could be produced instead.
        """
        material = self.get_material(material_id)
        context = context or {}

        def _result(
            status: PropertyResolutionStatus,
            value: float | None,
            *,
            unit: str | None = None,
            source_id: str | None = None,
            note: str | None = None,
            matched_rule: PropertyRule | None = None,
        ) -> PropertyResolution:
            return PropertyResolution(
                material_id=material_id,
                property_name=property_name,
                status=status,
                value=value,
                unit=unit,
                property_type=material.property_type,
                data_status=material.data_status,
                auto_appliable=material.auto_appliable and status
                in (PropertyResolutionStatus.RESOLVED_CONSTANT, PropertyResolutionStatus.RESOLVED_BY_RULE),
                source_id=source_id if source_id is not None else material.source_id,
                note=note,
                matched_rule=matched_rule,
            )

        if material.property_type is PropertyType.USER_DEFINED:
            return _result(
                PropertyResolutionStatus.USER_DEFINED,
                None,
                note="사용자 정의 재료입니다. 값을 직접 입력하세요.",
            )

        rules = self._rules_for(material_id, property_name)
        if rules:
            matched = [rule for rule in rules if rule.matches(context)]
            if not matched:
                required_key = rules[0].context_key
                if required_key not in context:
                    return _result(
                        PropertyResolutionStatus.MISSING_CONTEXT,
                        None,
                        note=f"context에 '{required_key}' 값이 필요합니다.",
                    )
                return _result(
                    PropertyResolutionStatus.NO_MATCHING_RULE,
                    None,
                    note="주어진 조건에 해당하는 PropertyRules 구간이 없습니다.",
                )
            rule = matched[0]
            if rule.property_value is None:
                return _result(
                    PropertyResolutionStatus.RULE_VALUE_MISSING,
                    None,
                    unit=rule.property_unit,
                    source_id=rule.source_id,
                    note=rule.note,
                    matched_rule=rule,
                )
            return _result(
                PropertyResolutionStatus.RESOLVED_BY_RULE,
                rule.property_value,
                unit=rule.property_unit,
                source_id=rule.source_id,
                note=rule.note,
                matched_rule=rule,
            )

        if not hasattr(material, property_name):
            raise ValueError(f"알 수 없는 property_name입니다: {property_name!r}")
        value = getattr(material, property_name)
        if value is None:
            return _result(PropertyResolutionStatus.VALUE_MISSING, None)
        return _result(PropertyResolutionStatus.RESOLVED_CONSTANT, value)
