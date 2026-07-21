from __future__ import annotations

from pathlib import Path


class UserFacingError(RuntimeError):
    """An operational error that can be shown without a traceback."""


class DataLoadError(UserFacingError):
    pass


class CacheError(DataLoadError):
    pass


class DatabaseError(UserFacingError):
    pass


class DatabaseSchemaTooNewError(DatabaseError):
    """The database belongs to a newer application and must not be downgraded."""

    def __init__(
        self,
        *,
        database_schema_version: int,
        supported_schema_version: int,
        database_path: str | Path,
    ) -> None:
        self.database_schema_version = int(database_schema_version)
        self.supported_schema_version = int(supported_schema_version)
        self.database_path = Path(database_path).resolve()
        super().__init__(
            "Database schema version "
            f"{self.database_schema_version} is newer than supported version "
            f"{self.supported_schema_version}: {self.database_path}"
        )

    def user_message_zh(self, application_version: str) -> str:
        return (
            "数据库与当前程序不兼容。\n\n"
            f"当前程序版本：{application_version}\n"
            f"当前程序支持的数据库版本：{self.supported_schema_version}\n"
            f"数据库版本：{self.database_schema_version}\n"
            f"数据库路径：{self.database_path}\n\n"
            "请启动更新版本。禁止使用旧版覆盖或降级数据库。"
        )


class ExportError(UserFacingError):
    pass


class AnalysisError(UserFacingError):
    pass


class ConfigError(UserFacingError):
    pass


class DependencyError(UserFacingError):
    pass
