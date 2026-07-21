from __future__ import annotations

from types import SimpleNamespace
import threading
import time

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")

from controllers.research_snapshot_controller import (
    ResearchSnapshotController,
    ResearchSnapshotPublishRequest,
)
from research.cancellation import ResearchCancelled
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


class _SnapshotService:
    def __init__(self) -> None:
        self.thread_ids: list[int] = []

    def publish(self, snapshot_input, *, created_at, cancelled, progress):
        self.thread_ids.append(threading.get_ident())
        progress("正在生成中文研究报告")
        return SimpleNamespace(
            snapshot=SimpleNamespace(snapshot_id="snapshot-1"),
            directory="reports/snapshot-1",
            duplicate=False,
        )

    def read(self, snapshot_id):
        return SimpleNamespace(
            snapshot=SimpleNamespace(
                snapshot_id=snapshot_id,
                created_at="2026-02-02T00:00:00+00:00",
            ),
            report_markdown="# 已发布报告",
        )


class _CancellableSnapshotService:
    def __init__(self) -> None:
        self.started = threading.Event()

    def publish(self, snapshot_input, *, created_at, cancelled, progress):
        self.started.set()
        while not cancelled():
            time.sleep(0.005)
        raise ResearchCancelled("cancelled")


def test_snapshot_controller_runs_publish_and_read_outside_qt_main_thread():
    service = _SnapshotService()
    lifecycle = BackgroundTaskLifecycle()
    controller = ResearchSnapshotController(service, lifecycle=lifecycle)
    completed = []
    progress = []
    controller.finished.connect(completed.append)
    controller.progress.connect(progress.append)
    main_thread_id = threading.get_ident()

    controller.start(
        ResearchSnapshotPublishRequest(
            snapshot_input=object(),
            created_at="2026-02-02T00:00:00+00:00",
        )
    )

    assert _wait_until(lambda: not controller.is_running)
    assert len(completed) == 1
    assert completed[0].view.report_markdown == "# 已发布报告"
    assert progress == ["正在生成中文研究报告"]
    assert service.thread_ids != [main_thread_id]
    assert lifecycle.state("research_snapshot_publish") is TaskState.COMPLETED


def test_snapshot_controller_shutdown_requests_cooperative_cancel():
    service = _CancellableSnapshotService()
    controller = ResearchSnapshotController(service)
    cancellations = []
    controller.cancelled.connect(lambda: cancellations.append(True))
    controller.start(
        ResearchSnapshotPublishRequest(
            snapshot_input=object(),
            created_at="2026-02-02T00:00:00+00:00",
        )
    )
    assert _wait_until(service.started.is_set)

    assert controller.shutdown() is False
    assert _wait_until(lambda: not controller.is_running)
    assert controller.shutdown() is True
    assert cancellations == [True]


def test_snapshot_controller_loads_old_version_outside_qt_main_thread():
    service = _SnapshotService()
    controller = ResearchSnapshotController(service)
    completed = []
    controller.finished.connect(completed.append)

    controller.load("snapshot-old")

    assert _wait_until(lambda: not controller.is_running)
    assert completed[0].publication is None
    assert completed[0].view.snapshot.snapshot_id == "snapshot-old"
