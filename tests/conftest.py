from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "quant_collector_app"
HELPERS_DIR = REPO_ROOT / "tests" / "helpers"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

for path in (REPO_ROOT, APP_DIR, HELPERS_DIR):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


_QAPP_HOLDER = None


def _artifact_run_root(
    *,
    pid: int | None = None,
    token: str | None = None,
) -> Path:
    """Return a never-reused pytest temp root below the ignored artifact tree."""

    process_id = os.getpid() if pid is None else int(pid)
    run_token = uuid.uuid4().hex if token is None else str(token)
    return Path(
        f".test-artifacts/pytest-tmp-run-{process_id}-{run_token}"
    )


def pytest_configure(config) -> None:
    """Avoid Windows ACL failures caused by reusing and deleting one base temp."""

    if config.option.basetemp is None:
        config.option.basetemp = str(_artifact_run_root())


def pytest_collection_modifyitems(config, items) -> None:
    """Run the native Qt process gate before memory-heavy performance cases.

    The Qt gate already owns a clean child interpreter. Keeping the parent
    pytest process alive after the 270k benchmarks can nevertheless leave
    enough resident allocator pages to force that child into Windows paging,
    turning a 70-second lifecycle gate into a false outer-watchdog timeout.
    Default test order is unchanged.
    """

    if str(config.option.markexpr).strip() != "performance":
        return
    items.sort(
        key=lambda item: (
            item.path.name != "test_qt_native_subprocess.py",
            item.nodeid,
        )
    )


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
