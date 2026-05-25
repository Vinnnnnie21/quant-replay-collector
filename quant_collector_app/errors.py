from __future__ import annotations


class UserFacingError(RuntimeError):
    """An operational error that can be shown without a traceback."""


class DataLoadError(UserFacingError):
    pass


class CacheError(DataLoadError):
    pass


class DatabaseError(UserFacingError):
    pass


class ExportError(UserFacingError):
    pass


class AnalysisError(UserFacingError):
    pass


class ConfigError(UserFacingError):
    pass


class DependencyError(UserFacingError):
    pass
