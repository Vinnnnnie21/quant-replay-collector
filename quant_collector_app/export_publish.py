from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

try:
    from app_logger import get_logger
except ImportError:  # pragma: no cover - package import path
    from .app_logger import get_logger


logger = get_logger(__name__)


class ExportPublishError(RuntimeError):
    pass


EXPORT_CLEANUP_BACKOFF_SECONDS = (0.05, 0.1)
EXPORT_CLEANUP_MAX_ATTEMPTS = len(EXPORT_CLEANUP_BACKOFF_SECONDS) + 1
_TRANSIENT_CLEANUP_WINERRORS = frozenset({5, 32, 33})


def _is_transient_cleanup_error(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in _TRANSIENT_CLEANUP_WINERRORS


class ExportDirectoryPublisher:
    """Build an export off to the side, then publish it with recoverable renames."""

    def __init__(
        self,
        export_root: str | Path,
        final_name: str,
        *,
        rename: Callable[[str | Path, str | Path], None] = os.replace,
        remove_tree: Callable[[str | Path], None] = shutil.rmtree,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if Path(final_name).name != final_name:
            raise ValueError("final_name must be a single directory name")
        self.export_root = Path(export_root)
        self.final_dir = self.export_root / final_name
        self._prefix = f".{final_name}"
        self._rename = rename
        self._remove_tree = remove_tree
        self._sleep = sleep
        self._cleanup_warnings: list[str] = []
        self.staging_dir: Path | None = None
        self.backup_dir: Path | None = None

    @property
    def has_deferred_cleanup(self) -> bool:
        return bool(self._cleanup_warnings)

    def prepare(self) -> Path:
        self.export_root.mkdir(parents=True, exist_ok=True)
        self.recover()
        self.staging_dir = self.export_root / f"{self._prefix}.staging-{uuid.uuid4().hex}"
        self.staging_dir.mkdir()
        return self.staging_dir

    def recover(self) -> Path | None:
        self.export_root.mkdir(parents=True, exist_ok=True)
        staging_dirs = sorted(self.export_root.glob(f"{self._prefix}.staging-*"))
        backup_dirs = sorted(self.export_root.glob(f"{self._prefix}.backup-*"))
        if self.final_dir.exists():
            _validate_export_directory(self.final_dir)
            self._remove_recovery_directories([*staging_dirs, *backup_dirs])
            return self.final_dir

        valid_backups = [path for path in backup_dirs if _is_valid_export_directory(path)]
        if len(backup_dirs) == 1 and len(valid_backups) == 1:
            self._rename(valid_backups[0], self.final_dir)
            _validate_export_directory(self.final_dir)
            self._remove_recovery_directories(staging_dirs)
            return self.final_dir
        if backup_dirs:
            raise ExportPublishError(
                "export recovery is ambiguous; recovery directories were preserved"
            )
        # A staging directory alone does not prove that publication had started.
        # Preserve it for diagnosis instead of promoting or deleting it.
        return None

    def _remove_recovery_directories(self, paths: list[Path]) -> None:
        for path in paths:
            if path.is_dir():
                self._remove_directory_with_retry(path)

    def _remove_directory_with_retry(self, path: Path) -> bool:
        for attempt in range(EXPORT_CLEANUP_MAX_ATTEMPTS):
            try:
                self._remove_tree(path)
                return True
            except OSError as exc:
                if not _is_transient_cleanup_error(exc):
                    self._record_deferred_cleanup(path, 1, exc)
                    return False
                if attempt == EXPORT_CLEANUP_MAX_ATTEMPTS - 1:
                    self._record_deferred_cleanup(
                        path,
                        EXPORT_CLEANUP_MAX_ATTEMPTS,
                        exc,
                    )
                    return False
                self._sleep(EXPORT_CLEANUP_BACKOFF_SECONDS[attempt])
        return False

    def _record_deferred_cleanup(self, path: Path, attempts: int, exc: OSError) -> None:
        warning = (
            f"Export cleanup deferred for {path} after {attempts} "
            f"attempt{'s' if attempts != 1 else ''}: {type(exc).__name__}: {exc}"
        )
        self._cleanup_warnings.append(warning)
        logger.warning("%s", warning)

    def abort(self) -> None:
        if self.staging_dir is not None and self.staging_dir.exists():
            self._remove_directory_with_retry(self.staging_dir)
        self.staging_dir = None

    def publish(self) -> Path:
        staging = self.staging_dir
        if staging is None or not staging.is_dir():
            raise ExportPublishError("export staging directory is not available")
        _validate_export_directory(staging)
        if not self.final_dir.exists():
            self._rename(staging, self.final_dir)
            self.staging_dir = None
            _validate_export_directory(self.final_dir)
            return self.final_dir

        backup = self.export_root / f"{self._prefix}.backup-{uuid.uuid4().hex}"
        self._rename(self.final_dir, backup)
        self.backup_dir = backup
        try:
            self._rename(staging, self.final_dir)
            self.staging_dir = None
            _validate_export_directory(self.final_dir)
        except Exception as exc:
            try:
                if self.final_dir.exists():
                    self._rename(self.final_dir, staging)
                self._rename(backup, self.final_dir)
            except Exception as restore_exc:
                # The on-disk state is now ambiguous. Detach automatic cleanup so
                # the next recovery attempt has both the old backup and new staging.
                self.staging_dir = None
                raise ExportPublishError(
                    "export directory publication and rollback failed; recovery directories were preserved"
                ) from restore_exc
            if staging.exists():
                self._remove_directory_with_retry(staging)
            self.staging_dir = None
            self.backup_dir = None
            raise ExportPublishError(
                "export directory publication failed; previous successful export was restored"
            ) from exc
        self._remove_directory_with_retry(backup)
        self.backup_dir = None
        return self.final_dir


def _validate_export_directory(directory: Path) -> dict:
    manifest_path = directory / "export_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ExportPublishError(
            f"export staging manifest is missing or invalid: {manifest_path}"
        ) from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("row_counts"), dict):
        raise ExportPublishError("export manifest is missing row_counts")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ExportPublishError("export manifest is missing files")
    for table_name in manifest["row_counts"]:
        record = files.get(table_name)
        if not isinstance(record, dict) or not isinstance(record.get("csv"), str):
            raise ExportPublishError(f"export manifest is missing CSV for table: {table_name}")
    reference_keys = {"csv", "parquet", "json", "markdown", "manifest", "report"}
    for record in files.values():
        if not isinstance(record, dict):
            continue
        for key in reference_keys:
            relative_path = record.get(key)
            if isinstance(relative_path, str) and not (directory / relative_path).is_file():
                raise ExportPublishError(f"export manifest references a missing file: {relative_path}")
    return manifest


def _is_valid_export_directory(directory: Path) -> bool:
    try:
        _validate_export_directory(directory)
    except ExportPublishError:
        return False
    return True


__all__ = ["ExportDirectoryPublisher", "ExportPublishError"]
