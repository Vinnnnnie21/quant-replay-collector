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
    assert all(path.is_absolute() for path in (app_config.DATA_DIR, app_config.CACHE_DIR, app_config.EXPORT_DIR, app_config.LOG_DIR))
