from __future__ import annotations

import importlib


def test_package_exposes_version():
    package = importlib.import_module("quant_collector_app")
    from quant_collector_app.app_config import APP_VERSION
    assert package.__version__ == APP_VERSION


def test_root_launcher_is_import_safe():
    module = importlib.import_module("run_app")
    assert callable(module.main)
