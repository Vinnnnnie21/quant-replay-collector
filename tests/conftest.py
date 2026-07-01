from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "quant_collector_app"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for path in (REPO_ROOT, APP_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


_QAPP_HOLDER = None


@pytest.fixture(autouse=True)
def _isolate_qt_test_lifecycle():
    """Keep one QApplication alive and close top-level widgets between tests.

    Forcing Qt DeferredDelete processing under the Windows offscreen platform can
    abort the interpreter during teardown. Closing widgets is enough isolation
    for these tests and avoids driving native deletion from the fixture.
    """
    global _QAPP_HOLDER
    try:
        from PySide6 import QtWidgets
    except ModuleNotFoundError:
        yield
        return

    _QAPP_HOLDER = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield

    for widget in list(_QAPP_HOLDER.topLevelWidgets()):
        try:
            widget.close()
        except RuntimeError:
            continue
    _QAPP_HOLDER.processEvents()
