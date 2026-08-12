"""Material & Section Master DB: spreadsheet-backed, JSON-cached, read-only."""

from openframe.infrastructure.material_section_db.cache import load_material_database
from openframe.infrastructure.material_section_db.excel_loader import load_database_from_excel

__all__ = ["load_database_from_excel", "load_material_database"]
