"""Application-wide errors that can be translated into user messages."""


class OpenFrameError(Exception):
    """Base exception for expected application failures."""


class ModelValidationError(OpenFrameError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = tuple(errors)


class ModelImportError(OpenFrameError):
    """Raised when a source file cannot be converted to a structural model."""

