from __future__ import annotations

from pathlib import Path

import app_config


def test_runtime_paths_are_absolute_and_anchored_to_application_directory():
    app_dir = Path(app_config.__file__).resolve().parent
    assert app_config.ROOT_DIR == app_dir
    assert app_config.DATA_DIR == app_dir / "data"
    assert app_config.CACHE_DIR == app_config.DATA_DIR / "cache"
    assert app_config.EXPORT_DIR == app_config.DATA_DIR / "exports"
    assert app_config.LOG_DIR == app_dir / "logs"
    assert app_config.BACKUP_DIR == app_dir.parent / "backups"
    assert all(path.is_absolute() for path in (app_config.DATA_DIR, app_config.CACHE_DIR, app_config.EXPORT_DIR, app_config.LOG_DIR))


def test_local_frozen_executable_reuses_workspace_research_data(tmp_path):
    workspace = tmp_path / "Trading"
    app_dir = workspace / "quant_collector_app"
    executable = workspace / "dist" / "QRC-v1.5.2-Windows-x64.exe"
    app_dir.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "app_config.py").write_text("", encoding="utf-8")

    paths = app_config.resolve_application_paths(
        module_file=app_dir / "app_config.py",
        executable=executable,
        frozen=True,
    )

    assert paths.data_dir == app_dir / "data"
    assert paths.log_dir == app_dir / "logs"
    assert paths.backup_dir == workspace / "backups"


def test_portable_frozen_executable_keeps_data_beside_executable(tmp_path):
    install_dir = tmp_path / "QRC"
    executable = install_dir / "QRC.exe"

    paths = app_config.resolve_application_paths(
        module_file=tmp_path / "bundle" / "app_config.py",
        executable=executable,
        frozen=True,
    )

    assert paths.data_dir == install_dir / "data"
    assert paths.log_dir == install_dir / "logs"
    assert paths.backup_dir == install_dir / "backups"
