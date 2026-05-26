from __future__ import annotations

import importlib


def test_package_exposes_version():
    package = importlib.import_module("quant_collector_app")
    assert package.__version__ == "1.3.0"


def test_root_launcher_is_import_safe():
    module = importlib.import_module("run_app")
    assert callable(module.main)
