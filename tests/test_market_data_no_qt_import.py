from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"


def test_market_data_types_does_not_pull_network_or_gui_dependencies():
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(APP_DIR)
    probe = (
        "import sys; before=set(sys.modules); import market_data.types; "
        "new_modules=set(sys.modules)-before; "
        "assert not any(name == 'requests' or name.startswith('requests.') for name in new_modules); "
        "assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in new_modules); "
        "assert not any(name == 'pyqtgraph' or name.startswith('pyqtgraph.') for name in new_modules)"
    )
    run = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=environment, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr or run.stdout


def test_pure_market_data_modules_do_not_import_qt_or_pyqtgraph():
    probe = r"""
import importlib
import importlib.abc
import sys

blocked = {"PySide6", "pyqtgraph"}
class BlockGuiImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in blocked:
            raise AssertionError(f"GUI import requested by pure market-data module: {fullname}")
        return None

sys.meta_path.insert(0, BlockGuiImports())
for name in (
    "market_data.client",
    "market_data.loader",
    "market_data.cache",
    "market_data.quality",
    "market_data.transforms",
    "market_data.features",
):
    importlib.import_module(name)
assert "PySide6" not in sys.modules
assert "pyqtgraph" not in sys.modules
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(APP_DIR)
    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr or run.stdout
