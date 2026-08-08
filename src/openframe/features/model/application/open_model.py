"""Open and validate an external structural model."""

from pathlib import Path

from openframe.core.contracts import ModelImporter
from openframe.core.domain import StructuralModel
from openframe.core.errors import ModelValidationError


class OpenModelService:
    def __init__(self, importer: ModelImporter) -> None:
        self._importer = importer

    def execute(self, source: Path) -> StructuralModel:
        model = self._importer.load(source)
        errors = model.validate()
        if errors:
            raise ModelValidationError(errors)
        return model

