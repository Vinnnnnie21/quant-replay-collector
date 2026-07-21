from __future__ import annotations

import os
import threading
import time

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6 import QtCore

from controllers.research_backfill_controller import ResearchBackfillController
from market_data.types import (
    DataLoadCancelled,
    interval_to_ms,
    to_api_utc_ms_from_bjt,
)
from services.research_data_availability import ResearchRangeRequest
from storage import StorageManager
from task_lifecycle import BackgroundTaskLifecycle, TaskState
from workers.research_backfill_worker import ResearchBackfillWorker
from tests.research.test_research_data_backfill import _stored_kline


def _wait_until(
    predicate,
    *,
    timeout_seconds: float = 5.0,
) -> bool:
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


class _CancellableNetwork:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.thread_ids: list[int] = []

    def download(
        self,
        _symbol,
        _interval,
        _start_dt_bjt,
        _end_dt_bjt,
        progress=None,
        cancelled=None,
    ):
        del progress
        self.thread_ids.append(threading.get_ident())
        self.started.set()
        cancellation_requested = cancelled or (lambda: False)
        while not cancellation_requested():
            time.sleep(0.005)
        raise DataLoadCancelled("cancelled")


def _exchange_rows(interval, start_dt_bjt, end_dt_bjt) -> list[list]:
    step_ms = interval_to_ms(interval)
    start_ms = to_api_utc_ms_from_bjt(start_dt_bjt)
    end_ms = to_api_utc_ms_from_bjt(end_dt_bjt)
    return [
        [
            open_time_ms,
            "100.0",
            "102.0",
            "99.0",
            "101.0",
            "10.0",
            open_time_ms + step_ms - 1,
            "1200.5",
            42,
            "3.25",
            "650.75",
            "0",
        ]
        for open_time_ms in range(start_ms, end_ms + 1, step_ms)
    ]


class _DelayedNetwork:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def download(
        self,
        _symbol,
        interval,
        start_dt_bjt,
        end_dt_bjt,
        progress=None,
        cancelled=None,
    ):
        del progress, cancelled
        self.started.set()
        self.release.wait(timeout=5.0)
        return _exchange_rows(interval, start_dt_bjt, end_dt_bjt)


class _FailingNetwork:
    def download(self, *_args, **_kwargs):
        raise ConnectionError("temporary network failure")


class _CompletingNetwork:
    def download(
        self,
        _symbol,
        interval,
        start_dt_bjt,
        end_dt_bjt,
        progress=None,
        cancelled=None,
    ):
        del progress, cancelled
        return _exchange_rows(interval, start_dt_bjt, end_dt_bjt)


class _StartThenRaiseThread(QtCore.QThread):
    def start(self, priority=QtCore.QThread.InheritPriority):
        super().start(priority)
        raise RuntimeError("start failed after the thread began")


def test_controller_uses_thread_safe_cancellation_and_shared_lifecycle(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    network = _CancellableNetwork()
    lifecycle = BackgroundTaskLifecycle()
    controller = ResearchBackfillController(
        db_path=db_path,
        lifecycle=lifecycle,
        worker_factory=lambda: ResearchBackfillWorker(
            network_factory=lambda: network
        ),
    )
    cancellations = []
    controller.cancelled.connect(cancellations.append)
    main_thread_id = threading.get_ident()
    start_ms = 1_767_225_600_000

    assert controller.start(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=start_ms,
            as_of_utc_ms=start_ms + 24 * 60 * 60_000,
        )
    )
    assert _wait_until(network.started.is_set)
    assert lifecycle.state("research_data_backfill") is TaskState.RUNNING

    lifecycle.request_stop_all()

    assert _wait_until(lambda: not controller.is_running)
    assert len(cancellations) == 1
    assert lifecycle.state("research_data_backfill") is TaskState.COMPLETED
    assert network.thread_ids
    assert all(thread_id != main_thread_id for thread_id in network.thread_ids)
    assert controller.shutdown() is True


def test_invalidated_task_does_not_publish_stale_progress_or_terminal_state(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    network = _DelayedNetwork()
    lifecycle = BackgroundTaskLifecycle()
    controller = ResearchBackfillController(
        db_path=db_path,
        lifecycle=lifecycle,
        worker_factory=lambda: ResearchBackfillWorker(
            network_factory=lambda: network
        ),
    )
    progress = []
    finished = []
    failures = []
    cancellations = []
    idle = []
    controller.progress.connect(progress.append)
    controller.finished.connect(finished.append)
    controller.failed.connect(failures.append)
    controller.cancelled.connect(cancellations.append)
    controller.idle.connect(lambda: idle.append(True))
    start_ms = 1_767_225_600_000

    assert controller.start(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=start_ms,
            as_of_utc_ms=start_ms + 24 * 60 * 60_000,
        )
    )
    assert _wait_until(network.started.is_set)

    controller.invalidate()
    network.release.set()

    assert _wait_until(lambda: not controller.is_running)
    assert progress == []
    assert finished == []
    assert failures == []
    assert cancellations == []
    assert idle == [True]
    assert lifecycle.state("research_data_backfill") is TaskState.COMPLETED


def test_failed_task_exposes_retry_and_retry_reaudits_to_completion(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    networks = [_FailingNetwork(), _CompletingNetwork()]
    lifecycle = BackgroundTaskLifecycle()
    controller = ResearchBackfillController(
        db_path=db_path,
        lifecycle=lifecycle,
        worker_factory=lambda: ResearchBackfillWorker(
            network_factory=lambda: networks.pop(0)
        ),
    )
    failures = []
    finished = []
    controller.failed.connect(failures.append)
    controller.finished.connect(finished.append)
    start_ms = 1_767_225_600_000
    request = ResearchRangeRequest(
        symbol="BTCUSDT",
        timeframes=("1m", "5m", "15m"),
        start_time_utc_ms=start_ms,
        end_time_utc_ms=start_ms,
        as_of_utc_ms=start_ms + 24 * 60 * 60_000,
    )

    assert controller.can_retry is False
    assert controller.start(request)
    assert _wait_until(lambda: len(failures) == 1)
    assert lifecycle.state("research_data_backfill") is TaskState.FAILED
    assert controller.can_retry is True

    assert controller.retry() is True
    assert _wait_until(lambda: len(finished) == 1)

    assert finished[0].result.status.value == "complete"
    assert controller.can_retry is False
    assert lifecycle.state("research_data_backfill") is TaskState.COMPLETED


def test_controller_runs_local_completeness_audit_in_worker_thread(tmp_path) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    lifecycle = BackgroundTaskLifecycle()
    controller = ResearchBackfillController(
        db_path=db_path,
        lifecycle=lifecycle,
        worker_factory=lambda: ResearchBackfillWorker(
            network_factory=lambda: (_ for _ in ()).throw(
                AssertionError("audit must not construct the network adapter")
            )
        ),
    )
    inspected = []
    controller.inspected.connect(inspected.append)
    start_ms = 1_767_225_600_000

    assert controller.inspect(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=start_ms,
            as_of_utc_ms=start_ms + 24 * 60 * 60_000,
        )
    )
    assert _wait_until(lambda: len(inspected) == 1)

    assert inspected[0].report.is_complete is False
    assert controller.is_running is False
    assert lifecycle.state("research_data_backfill") is TaskState.COMPLETED


def test_running_local_audit_cooperatively_stops_during_safe_shutdown(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    lifecycle = BackgroundTaskLifecycle()
    controller = ResearchBackfillController(
        db_path=db_path,
        lifecycle=lifecycle,
        worker_factory=lambda: ResearchBackfillWorker(
            network_factory=lambda: (_ for _ in ()).throw(
                AssertionError("audit shutdown must not touch the network")
            )
        ),
    )
    inspected = []
    cancelled = []
    controller.inspected.connect(inspected.append)
    controller.auditCancelled.connect(cancelled.append)
    start_ms = 1_767_225_600_000

    assert controller.inspect(
        ResearchRangeRequest(
            symbol="BTCUSDT",
            timeframes=("1m", "5m", "15m"),
            start_time_utc_ms=start_ms,
            end_time_utc_ms=start_ms,
            as_of_utc_ms=start_ms + 24 * 60 * 60_000,
        )
    )

    assert controller.shutdown() is False
    assert _wait_until(lambda: not controller.is_running)
    assert inspected == []
    assert len(cancelled) == 1
    assert lifecycle.state("research_data_backfill") is TaskState.COMPLETED
    assert controller.shutdown() is True


def test_controller_runs_full_history_backfill_only_when_explicitly_started(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    storage = StorageManager(db_path)
    start_ms = 1_767_225_600_000
    row = _stored_kline("1m", start_ms)
    row["quote_volume"] = None
    storage.upsert_klines([row])
    lifecycle = BackgroundTaskLifecycle()
    network = _CompletingNetwork()
    controller = ResearchBackfillController(
        db_path=db_path,
        lifecycle=lifecycle,
        worker_factory=lambda: ResearchBackfillWorker(
            network_factory=lambda: network
        ),
    )
    finished = []
    controller.maintenanceFinished.connect(finished.append)

    assert finished == []
    assert controller.start_full_history() is True
    assert _wait_until(lambda: len(finished) == 1)

    assert finished[0].result.is_complete is True
    assert storage.list_kline_series_ranges(
        ancillary_incomplete_only=True
    ) == []


def test_start_failure_waits_for_running_thread_before_publishing_failure(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    created_threads = []
    lifecycle = BackgroundTaskLifecycle()

    def thread_factory(parent):
        thread = _StartThenRaiseThread(parent)
        created_threads.append(thread)
        return thread

    controller = ResearchBackfillController(
        db_path=db_path,
        lifecycle=lifecycle,
        thread_factory=thread_factory,
    )
    failures = []
    controller.failed.connect(failures.append)
    start_ms = 1_767_225_600_000
    request = ResearchRangeRequest(
        symbol="BTCUSDT",
        timeframes=("1m", "5m", "15m"),
        start_time_utc_ms=start_ms,
        end_time_utc_ms=start_ms,
        as_of_utc_ms=start_ms + 24 * 60 * 60_000,
    )

    try:
        assert controller.start(request) is False
        assert failures == []
        assert controller.is_running is True

        assert _wait_until(lambda: len(failures) == 1)
        assert controller.is_running is False
        assert lifecycle.state("research_data_backfill") is TaskState.FAILED
    finally:
        for thread in created_threads:
            if thread.isRunning():
                thread.quit()
                thread.wait(2_000)
