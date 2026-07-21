from __future__ import annotations

from types import SimpleNamespace
import threading
import time

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")

from controllers.entry_behavior_training_controller import (
    EntryBehaviorTrainingController,
)
from research.entry_behavior_model import EntryBehaviorTrainingRequest
from services.entry_behavior_training import EntryBehaviorTrainingCancelled
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


class _ReplacingTrainingService:
    def __init__(self) -> None:
        self.first_started = threading.Event()
        self.thread_ids: list[int] = []

    def train(self, request, *, cancelled=None, progress=None):
        self.thread_ids.append(threading.get_ident())
        if request.setup_version_id == "setup_old":
            self.first_started.set()
            while not cancelled():
                time.sleep(0.005)
            raise EntryBehaviorTrainingCancelled("replaced")
        if progress is not None:
            progress(1, 1)
        return SimpleNamespace(
            experiment_id="experiment_new",
            setup_version_id=request.setup_version_id,
            model=SimpleNamespace(model_version_id="model_new"),
        )


def test_replaced_training_is_cancelled_and_old_setup_cannot_publish_result():
    service = _ReplacingTrainingService()
    lifecycle = BackgroundTaskLifecycle()
    controller = EntryBehaviorTrainingController(service, lifecycle=lifecycle)
    results = []
    cancellations = []
    controller.resultReady.connect(results.append)
    controller.cancelled.connect(lambda: cancellations.append(True))
    main_thread_id = threading.get_ident()

    controller.start(
        EntryBehaviorTrainingRequest("setup_old", "grouping_1", "LONG")
    )
    assert _wait_until(service.first_started.is_set)
    controller.start(
        EntryBehaviorTrainingRequest("setup_new", "grouping_1", "LONG")
    )

    assert _wait_until(lambda: not controller.is_running)
    assert [result.setup_version_id for result in results] == ["setup_new"]
    assert cancellations == []
    assert service.thread_ids
    assert all(thread_id != main_thread_id for thread_id in service.thread_ids)
    assert lifecycle.state("entry_behavior_training") is TaskState.COMPLETED


def test_safe_shutdown_requests_cooperative_cancel_and_waits_for_worker():
    service = _ReplacingTrainingService()
    controller = EntryBehaviorTrainingController(service)
    controller.start(
        EntryBehaviorTrainingRequest("setup_old", "grouping_1", "LONG")
    )
    assert _wait_until(service.first_started.is_set)

    assert controller.shutdown() is False
    assert _wait_until(lambda: not controller.is_running)
    assert controller.shutdown() is True
