from pathlib import Path

from PySide6.QtCore import QSettings

from openframe.app.shell.imported_model_units import (
    ImportedModelUnitStore,
    unit_system_from_metadata,
)
from openframe.core.domain import UnitSystem


def test_unit_system_from_complete_import_metadata() -> None:
    units = unit_system_from_metadata(
        {"unit_force": "kip", "unit_length": "in", "unit_time": "s"}
    )

    assert units == UnitSystem("kip", "in", "s")


def test_incomplete_or_unsupported_import_metadata_is_not_guessed() -> None:
    assert unit_system_from_metadata({"unit_force": "kip"}) is None
    assert (
        unit_system_from_metadata(
            {"unit_force": "kgf", "unit_length": "cm", "unit_time": "s"}
        )
        is None
    )


def test_user_selected_native_units_are_persisted_by_source_path(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "units.ini"), QSettings.Format.IniFormat)
    store = ImportedModelUnitStore(settings)
    source = tmp_path / "legacy_model.py"

    assert store.load(source) is None
    store.save(source, UnitSystem("N", "mm"))
    settings.sync()

    restored = ImportedModelUnitStore(settings).load(source)
    assert restored == UnitSystem("N", "mm")
