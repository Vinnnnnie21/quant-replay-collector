from __future__ import annotations

from types import SimpleNamespace
import threading
import time

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")

from controllers.entry_outcome_comparison_controller import (
    EntryOutcomeComparisonController,
)
from research.cancellation import ResearchCancelled
from research.entry_outcome_comparison import EntryOutcomeComparisonRequest
from task_lifecycle import BackgroundTaskLifecycle, TaskState


def _wait_until(predicate, timeout_seconds: float = 5.0) -> bool:
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


class _ReplacingOutcomeService:
    def __init__(self) -> None:
        self.first_started = threading.Event()
        self.thread_ids: list[int] = []

    def run(self, *, setup_version_id, cancelled=None, progress=None, **_):
        self.thread_ids.append(threading.get_ident())
        if setup_version_id == "setup_old":
            self.first_started.set()
            while not cancelled():
                time.sleep(0.005)
            raise ResearchCancelled("replaced")
        if progress is not None:
            progress(1, 1)
        return SimpleNamespace(
            comparison_id="comparison_new",
            setup_version_id=setup_version_id,
        )


def test_replaced_comparison_cannot_publish_an_old_setup_result():
    service = _ReplacingOutcomeService()
    lifecycle = BackgroundTaskLifecycle()
    controller = EntryOutcomeComparisonController(service, lifecycle=lifecycle)
    results = []
    cancellations = []
    controller.resultReady.connect(results.append)
    controller.cancelled.connect(lambda: cancellations.append(True))
    main_thread_id = threading.get_ident()

    controller.start(
        EntryOutcomeComparisonRequest("setup_old", "grouping_1", "LONG")
    )
    assert _wait_until(service.first_started.is_set)
    controller.start(
        EntryOutcomeComparisonRequest("setup_new", "grouping_1", "LONG")
    )

    assert _wait_until(lambda: not controller.is_running)
    assert [item.setup_version_id for item in results] == ["setup_new"]
    assert cancellations == []
    assert all(item != main_thread_id for item in service.thread_ids)
    assert lifecycle.state("entry_outcome_comparison") is TaskState.COMPLETED


def test_safe_shutdown_requests_cooperative_cancel():
    service = _ReplacingOutcomeService()
    controller = EntryOutcomeComparisonController(service)
    controller.start(
        EntryOutcomeComparisonRequest("setup_old", "grouping_1", "LONG")
    )
    assert _wait_until(service.first_started.is_set)

    assert controller.shutdown() is False
    assert _wait_until(lambda: not controller.is_running)
    assert controller.shutdown() is True
