"""Exception hierarchy. Every failure PyField raises on purpose derives from PyFieldError."""


class PyFieldError(Exception):
    """Base class."""


class FormatError(PyFieldError):
    """The bytes do not form a valid container (truncation, bad sizes, bad compression)."""

    def __init__(self, message, offset=None):
        self.offset = offset
        super().__init__(f'{message} at {offset:#x}' if offset is not None else message)


class UnsupportedOperation(PyFieldError):
    """The operation is known but not supported (or not yet validated) for this adapter/format."""

    def __init__(self, capability, detail=''):
        self.capability = capability
        super().__init__(f'unsupported: {capability}' + (f' ({detail})' if detail else ''))


class ResolutionError(PyFieldError):
    """A FormID or plugin name cannot be resolved in the current load context."""


class SchemaError(PyFieldError):
    """A schema definition or a typed decode/encode does not match the data."""


class ValidationError(PyFieldError):
    """Validation found errors; carries the report."""

    def __init__(self, report):
        self.report = report
        super().__init__(report.summary())


class TransactionError(PyFieldError):
    """Misuse of transactions (nested commit, use after rollback, ...)."""
