from __future__ import annotations

import importlib


def test_lightweight_runtime_modules_import_without_ui_creation():
    for module_name in [
        "app_config",
        "app_logger",
        "errors",
        "error_boundary",
        "lazy_imports",
        "startup",
        "state",
        "perf.timing",
        "views.chart_view",
        "market_data.types",
        "market_data.client",
        "market_data.cache",
        "market_data.loader",
        "market_data.quality",
        "market_data.transforms",
        "market_data.features",
        "services.market_data_service",
        "services.export_service",
        "services.analysis_service",
    ]:
        assert importlib.import_module(module_name) is not None


def test_storage_import_does_not_open_default_database(monkeypatch):
    module = importlib.import_module("storage")
    called = []
    monkeypatch.setattr(module.StorageManager, "_init_db", lambda self: called.append(self.db_path))

    assert called == []
