from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from export_publish import ExportDirectoryPublisher, ExportPublishError


def _write_valid_export(directory: Path, marker: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "data.csv").write_text(f"marker\n{marker}\n", encoding="utf-8")
    manifest = {
        "row_counts": {"data": 1},
        "files": {
            "data": {"csv": "data.csv"},
            "export_manifest": {"json": "export_manifest.json"},
        },
    }
    (directory / "export_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )


def _snapshot(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_second_publish_rename_failure_restores_previous_export_and_cleans_staging(tmp_path):
    export_root = tmp_path / "exports"
    final_dir = export_root / "session_s1"
    _write_valid_export(final_dir, "old")
    old_snapshot = _snapshot(final_dir)
    rename_calls = 0

    def fail_second_rename(source: str | Path, target: str | Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("simulated second rename failure")
        os.replace(source, target)

    publisher = ExportDirectoryPublisher(
        export_root,
        "session_s1",
        rename=fail_second_rename,
    )
    staging_dir = publisher.prepare()
    _write_valid_export(staging_dir, "new")

    with pytest.raises(ExportPublishError, match="previous successful export was restored"):
        publisher.publish()

    assert _snapshot(final_dir) == old_snapshot
    assert not list(export_root.glob(".session_s1.staging-*"))
    assert not list(export_root.glob(".session_s1.backup-*"))


def test_publish_failure_restores_previous_export_when_staging_cleanup_stays_locked(
    tmp_path,
    caplog,
):
    export_root = tmp_path / "exports"
    final_dir = export_root / "session_s1"
    _write_valid_export(final_dir, "old")
    old_snapshot = _snapshot(final_dir)
    rename_calls = 0
    remove_attempts: list[Path] = []

    def fail_second_rename(source: str | Path, target: str | Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("simulated second rename failure")
        os.replace(source, target)

    def remove_with_persistent_acl_error(path: str | Path) -> None:
        path = Path(path)
        remove_attempts.append(path)
        raise PermissionError(5, "simulated persistent access denied", str(path))

    publisher = ExportDirectoryPublisher(
        export_root,
        "session_s1",
        rename=fail_second_rename,
        remove_tree=remove_with_persistent_acl_error,
        sleep=lambda _delay: None,
    )
    staging_dir = publisher.prepare()
    _write_valid_export(staging_dir, "new")

    with pytest.raises(ExportPublishError, match="previous successful export was restored"):
        publisher.publish()

    assert _snapshot(final_dir) == old_snapshot
    assert remove_attempts == [staging_dir, staging_dir, staging_dir]
    assert staging_dir.is_dir()
    assert not list(export_root.glob(".session_s1.backup-*"))
    assert str(staging_dir) in caplog.text
    assert "cleanup deferred" in caplog.text


def test_recovery_restores_only_valid_backup_when_final_is_missing_and_cleans_staging(tmp_path):
    export_root = tmp_path / "exports"
    backup_dir = export_root / ".session_s1.backup-interrupted"
    staging_dir = export_root / ".session_s1.staging-interrupted"
    _write_valid_export(backup_dir, "old")
    staging_dir.mkdir(parents=True)
    (staging_dir / "unfinished.csv.partial").write_text("partial", encoding="utf-8")
    old_snapshot = _snapshot(backup_dir)

    publisher = ExportDirectoryPublisher(export_root, "session_s1")
    recovered = publisher.recover()

    assert recovered == export_root / "session_s1"
    assert _snapshot(recovered) == old_snapshot
    assert not backup_dir.exists()
    assert not staging_dir.exists()


def test_recovery_retries_transient_permission_error_when_cleaning_staging(tmp_path):
    export_root = tmp_path / "exports"
    backup_dir = export_root / ".session_s1.backup-interrupted"
    staging_dir = export_root / ".session_s1.staging-interrupted"
    _write_valid_export(backup_dir, "old")
    staging_dir.mkdir(parents=True)
    (staging_dir / "unfinished.csv.partial").write_text("partial", encoding="utf-8")
    remove_attempts: list[Path] = []
    backoff_delays: list[float] = []

    def remove_with_transient_acl_error(path: str | Path) -> None:
        path = Path(path)
        remove_attempts.append(path)
        if path == staging_dir and remove_attempts.count(staging_dir) < 3:
            raise PermissionError(5, "simulated transient access denied", str(path))
        shutil.rmtree(path)

    publisher = ExportDirectoryPublisher(
        export_root,
        "session_s1",
        remove_tree=remove_with_transient_acl_error,
        sleep=backoff_delays.append,
    )

    recovered = publisher.recover()

    assert recovered == export_root / "session_s1"
    assert remove_attempts.count(staging_dir) == 3
    assert len(backoff_delays) == 2
    assert all(delay > 0 for delay in backoff_delays)
    assert not staging_dir.exists()


def test_recovery_retries_windows_sharing_violation_when_cleaning_staging(tmp_path):
    export_root = tmp_path / "exports"
    final_dir = export_root / "session_s1"
    staging_dir = export_root / ".session_s1.staging-interrupted"
    _write_valid_export(final_dir, "current")
    staging_dir.mkdir(parents=True)
    remove_attempts = 0

    def remove_with_transient_sharing_violation(path: str | Path) -> None:
        nonlocal remove_attempts
        remove_attempts += 1
        if remove_attempts < 3:
            error = OSError("simulated file sharing violation")
            error.winerror = 32
            raise error
        shutil.rmtree(path)

    publisher = ExportDirectoryPublisher(
        export_root,
        "session_s1",
        remove_tree=remove_with_transient_sharing_violation,
        sleep=lambda _delay: None,
    )

    recovered = publisher.recover()

    assert recovered == final_dir
    assert remove_attempts == 3
    assert not staging_dir.exists()


def test_recovery_keeps_locked_staging_and_allows_next_export_prepare(tmp_path, caplog):
    export_root = tmp_path / "exports"
    backup_dir = export_root / ".session_s1.backup-interrupted"
    staging_dir = export_root / ".session_s1.staging-interrupted"
    _write_valid_export(backup_dir, "old")
    staging_dir.mkdir(parents=True)
    (staging_dir / "unfinished.csv.partial").write_text("partial", encoding="utf-8")
    remove_attempts = 0

    def remove_with_persistent_acl_error(path: str | Path) -> None:
        nonlocal remove_attempts
        path = Path(path)
        if path == staging_dir:
            remove_attempts += 1
            raise PermissionError(5, "simulated persistent access denied", str(path))
        shutil.rmtree(path)

    publisher = ExportDirectoryPublisher(
        export_root,
        "session_s1",
        remove_tree=remove_with_persistent_acl_error,
        sleep=lambda _delay: None,
    )

    recovered = publisher.recover()
    next_staging = publisher.prepare()

    assert recovered == export_root / "session_s1"
    assert recovered.is_dir()
    assert staging_dir.is_dir()
    assert next_staging.is_dir()
    assert next_staging != staging_dir
    assert remove_attempts == 6
    assert str(staging_dir) in caplog.text
    assert "cleanup deferred" in caplog.text
    assert "simulated persistent access denied" in caplog.text


def test_failed_publish_and_failed_rollback_preserve_recovery_directories(tmp_path):
    export_root = tmp_path / "exports"
    final_dir = export_root / "session_s1"
    _write_valid_export(final_dir, "old")
    old_snapshot = _snapshot(final_dir)
    rename_calls = 0

    def fail_publish_and_rollback(source: str | Path, target: str | Path) -> None:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls in {2, 3}:
            raise OSError(f"simulated rename failure {rename_calls}")
        os.replace(source, target)

    publisher = ExportDirectoryPublisher(
        export_root,
        "session_s1",
        rename=fail_publish_and_rollback,
    )
    staging_dir = publisher.prepare()
    _write_valid_export(staging_dir, "new")

    with pytest.raises(ExportPublishError, match="rollback failed"):
        publisher.publish()
    publisher.abort()

    backups = list(export_root.glob(".session_s1.backup-*"))
    stagings = list(export_root.glob(".session_s1.staging-*"))
    assert len(backups) == 1
    assert len(stagings) == 1
    assert _snapshot(backups[0]) == old_snapshot
    assert (stagings[0] / "data.csv").read_text(encoding="utf-8") == "marker\nnew\n"


def test_successful_publish_keeps_locked_backup_without_downgrading_success(tmp_path, caplog):
    export_root = tmp_path / "exports"
    final_dir = export_root / "session_s1"
    _write_valid_export(final_dir, "old")
    remove_attempts: list[Path] = []

    def remove_with_persistent_acl_error(path: str | Path) -> None:
        path = Path(path)
        remove_attempts.append(path)
        raise PermissionError(5, "simulated persistent access denied", str(path))

    publisher = ExportDirectoryPublisher(
        export_root,
        "session_s1",
        remove_tree=remove_with_persistent_acl_error,
        sleep=lambda _delay: None,
    )
    staging_dir = publisher.prepare()
    _write_valid_export(staging_dir, "new")

    published = publisher.publish()

    backups = list(export_root.glob(".session_s1.backup-*"))
    assert published == final_dir
    assert (published / "data.csv").read_text(encoding="utf-8") == "marker\nnew\n"
    assert len(remove_attempts) == 3
    assert backups == remove_attempts[:1]
    assert str(backups[0]) in caplog.text
    assert "cleanup deferred" in caplog.text
    assert "simulated persistent access denied" in caplog.text


def test_recovery_keeps_valid_final_and_cleans_confirmed_old_work_directories(tmp_path):
    export_root = tmp_path / "exports"
    final_dir = export_root / "session_s1"
    staging_dir = export_root / ".session_s1.staging-interrupted"
    backup_dir = export_root / ".session_s1.backup-interrupted"
    _write_valid_export(final_dir, "current")
    _write_valid_export(backup_dir, "old")
    staging_dir.mkdir(parents=True)
    (staging_dir / "unfinished.csv.partial").write_text("partial", encoding="utf-8")
    current_snapshot = _snapshot(final_dir)

    recovered = ExportDirectoryPublisher(export_root, "session_s1").recover()

    assert recovered == final_dir
    assert _snapshot(final_dir) == current_snapshot
    assert not staging_dir.exists()
    assert not backup_dir.exists()


def test_recovery_does_not_clean_directories_outside_its_session_namespace(tmp_path):
    export_root = tmp_path / "exports"
    final_dir = export_root / "session_s1"
    own_staging = export_root / ".session_s1.staging-interrupted"
    other_session_staging = export_root / ".session_s2.staging-interrupted"
    unrelated_directory = export_root / "session_s1.staging-not-owned"
    _write_valid_export(final_dir, "current")
    own_staging.mkdir(parents=True)
    other_session_staging.mkdir(parents=True)
    unrelated_directory.mkdir(parents=True)

    recovered = ExportDirectoryPublisher(export_root, "session_s1").recover()

    assert recovered == final_dir
    assert not own_staging.exists()
    assert other_session_staging.is_dir()
    assert unrelated_directory.is_dir()
