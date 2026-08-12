"""JSON cache in front of the Master DB spreadsheet.

The spreadsheet stays the source of truth: this cache exists only so a
normal app launch does not have to re-parse an Excel workbook with
``openpyxl`` every time. Whenever the spreadsheet's own content changes
(tracked by a SHA-256 fingerprint of its bytes, not its mtime, so copying
the file around never invalidates a good cache) the cache is rebuilt from
Excel and rewritten; if it cannot be rewritten (e.g. a read-only install),
loading still succeeds by parsing Excel directly - caching is purely an
optimization, never a correctness requirement.
"""

import dataclasses
import hashlib
import json
from pathlib import Path

from openframe.core.domain.material_section_db import (
    DataStatus,
    MaterialDatabase,
    MaterialRecord,
    PropertyRule,
    PropertyType,
    RCSectionRecord,
    SectionRecord,
    Source,
)
from openframe.infrastructure.material_section_db.excel_loader import load_database_from_excel

_CACHE_FORMAT_VERSION = 1

_DEFAULT_EXCEL_PATH = Path(__file__).parent / "data" / "material_section_database.xlsx"
_DEFAULT_CACHE_PATH = Path(__file__).parent / "data" / "material_section_database.cache.json"


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _material_to_json(material: MaterialRecord) -> dict:
    payload = dataclasses.asdict(material)
    payload["property_type"] = material.property_type.value
    payload["data_status"] = material.data_status.value
    return payload


def _material_from_json(payload: dict) -> MaterialRecord:
    payload = dict(payload)
    payload["property_type"] = PropertyType(payload["property_type"])
    payload["data_status"] = DataStatus(payload["data_status"])
    return MaterialRecord(**payload)


def _database_to_json(database: MaterialDatabase, source_fingerprint: str) -> dict:
    return {
        "cache_format_version": _CACHE_FORMAT_VERSION,
        "source_fingerprint": source_fingerprint,
        "materials": [_material_to_json(m) for m in database.all_materials()],
        "sections": [dataclasses.asdict(s) for s in database.all_sections()],
        "rc_sections": [dataclasses.asdict(rc) for rc in database.all_rc_sections()],
        "property_rules": [dataclasses.asdict(r) for r in database.all_property_rules()],
        "sources": [dataclasses.asdict(s) for s in database.all_sources()],
        "meta": database.meta,
        "warnings": list(database.warnings),
    }


def _database_from_json(payload: dict) -> MaterialDatabase:
    materials = {m["material_id"]: _material_from_json(m) for m in payload["materials"]}
    sections = {s["section_id"]: SectionRecord(**s) for s in payload["sections"]}
    rc_sections = {rc["section_id"]: RCSectionRecord(**rc) for rc in payload["rc_sections"]}
    property_rules = tuple(PropertyRule(**r) for r in payload["property_rules"])
    sources = {s["source_id"]: Source(**s) for s in payload["sources"]}
    return MaterialDatabase(
        materials=materials,
        sections=sections,
        rc_sections=rc_sections,
        property_rules=property_rules,
        sources=sources,
        meta=payload["meta"],
        warnings=tuple(payload["warnings"]),
    )


def load_material_database(
    *,
    excel_path: Path | None = None,
    cache_path: Path | None = None,
    force_reload: bool = False,
) -> MaterialDatabase:
    """Load the Master DB, using the JSON cache when it still matches the
    spreadsheet's current content. Always returns a usable
    :class:`MaterialDatabase` - a broken/unwritable cache never prevents
    loading, since Excel itself is always a valid fallback source.
    """
    excel_path = excel_path or _DEFAULT_EXCEL_PATH
    cache_path = cache_path or _DEFAULT_CACHE_PATH
    fingerprint = _fingerprint(excel_path)

    if not force_reload and cache_path.exists():
        try:
            cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                cached_payload.get("cache_format_version") == _CACHE_FORMAT_VERSION
                and cached_payload.get("source_fingerprint") == fingerprint
            ):
                return _database_from_json(cached_payload)
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Cache is missing/corrupt/stale - fall through to a fresh Excel parse.

    database = load_database_from_excel(excel_path)
    try:
        cache_path.write_text(
            json.dumps(_database_to_json(database, fingerprint), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass  # Caching is an optimization only - a read-only install must still work.
    return database
