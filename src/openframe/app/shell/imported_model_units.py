"""Native-unit declaration and persistence for imported OpenSeesPy models."""

import hashlib
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from openframe.core.domain import FORCE_UNITS, LENGTH_UNITS, TIME_UNITS, UnitSystem


def unit_system_from_metadata(metadata: dict[str, str]) -> UnitSystem | None:
    force = metadata.get("unit_force")
    length = metadata.get("unit_length")
    time = metadata.get("unit_time", "s")
    if force not in FORCE_UNITS or length not in LENGTH_UNITS or time not in TIME_UNITS:
        return None
    return UnitSystem(force=force, length=length, time=time)


class ImportedModelUnitStore:
    """Remember a user's native-unit declaration by absolute source path."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings("OpenFrame", "OpenFrame Studio")

    @staticmethod
    def _key(source: Path) -> str:
        normalized = str(source.resolve()).casefold().encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()

    def load(self, source: Path) -> UnitSystem | None:
        prefix = f"importedModelUnits/{self._key(source)}"
        force = self._settings.value(f"{prefix}/force", type=str)
        length = self._settings.value(f"{prefix}/length", type=str)
        time = self._settings.value(f"{prefix}/time", "s", type=str)
        if force not in FORCE_UNITS or length not in LENGTH_UNITS or time not in TIME_UNITS:
            return None
        return UnitSystem(force=force, length=length, time=time)

    def save(self, source: Path, unit_system: UnitSystem) -> None:
        prefix = f"importedModelUnits/{self._key(source)}"
        self._settings.setValue(f"{prefix}/source", str(source.resolve()))
        self._settings.setValue(f"{prefix}/force", unit_system.force)
        self._settings.setValue(f"{prefix}/length", unit_system.length)
        self._settings.setValue(f"{prefix}/time", unit_system.time)


class ImportedModelUnitDialog(QDialog):
    """Ask once for an undeclared OpenSees model's native units."""

    def __init__(self, source: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Declare OpenSees Model Units")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        explanation = QLabel(
            f"{source.name} does not declare OPENFRAME_UNITS.\n"
            "Choose the units already used by the model. Values will not be converted.\n\n"
            "To make future imports automatic, add for example:\n"
            'OPENFRAME_UNITS = {"force": "kN", "length": "m", "time": "s"}'
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self.force_unit = QComboBox()
        self.force_unit.addItems(FORCE_UNITS)
        self.length_unit = QComboBox()
        self.length_unit.addItems(LENGTH_UNITS)
        self.time_unit = QComboBox()
        self.time_unit.addItems(TIME_UNITS)
        form.addRow("Force", self.force_unit)
        form.addRow("Length", self.length_unit)
        form.addRow("Time", self.time_unit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_unit_system(self) -> UnitSystem:
        return UnitSystem(
            force=self.force_unit.currentText(),
            length=self.length_unit.currentText(),
            time=self.time_unit.currentText(),
        )

    @classmethod
    def choose(cls, source: Path, parent: QWidget | None = None) -> UnitSystem | None:
        dialog = cls(source, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected_unit_system()
