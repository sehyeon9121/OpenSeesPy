"""Standalone model validation use case for pre-analysis checks."""

from openframe.core.domain import StructuralModel


def validate_model(model: StructuralModel) -> list[str]:
    return model.validate()

