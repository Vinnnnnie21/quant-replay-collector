from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from services.research_data_availability import ResearchRangeRequest
from services.research_data_backfill import ResearchBackfillStatus
from storage import StorageManager
from workers.research_backfill_worker import (
    ResearchBackfillTask,
    ResearchBackfillWorker,
    ResearchDataTaskMode,
)

from tests.research.test_research_data_backfill import (
    _FailingSecondChunkNetwork,
    _RecordingNetwork,
    _stored_kline,
)


def test_worker_runs_real_backfill_service_and_emits_committed_progress(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    start_ms = 1_767_225_600_000
    network = _RecordingNetwork()
    worker = ResearchBackfillWorker(network_factory=lambda: network)
    progress = []
    finished = []
    failures = []
    cancellations = []
    worker.progress.connect(progress.append)
    worker.finished.connect(finished.append)
    worker.failed.connect(failures.append)
    worker.cancelled.connect(cancellations.append)

    worker.run(
        ResearchBackfillTask(
            revision=7,
            db_path=str(db_path),
            request=ResearchRangeRequest(
                symbol="BTCUSDT",
                timeframes=("1m", "5m", "15m"),
                start_time_utc_ms=start_ms,
                end_time_utc_ms=start_ms,
                as_of_utc_ms=start_ms + 24 * 60 * 60_000,
            ),
        )
    )

    assert failures == []
    assert cancellations == []
    assert len(finished) == 1
    assert finished[0].revision == 7
    assert finished[0].result.status is ResearchBackfillStatus.COMPLETE
    assert progress
    assert all(event.revision == 7 for event in progress)
    assert progress[-1].progress.completed_chunks == len(network.requests)
    stored = StorageManager(db_path).fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=start_ms,
        end_time_utc_ms=start_ms,
    )
    assert len(stored) == 1
    assert stored[0]["quote_volume"] == 1200.5


def test_worker_can_audit_local_storage_without_touching_network(tmp_path) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    start_ms = 1_767_225_600_000
    network_calls = []
    worker = ResearchBackfillWorker(
        network_factory=lambda: network_calls.append(True)
    )
    inspected = []
    worker.inspected.connect(inspected.append)

    worker.run(
        ResearchBackfillTask(
            revision=8,
            db_path=str(db_path),
            request=ResearchRangeRequest(
                symbol="BTCUSDT",
                timeframes=("1m", "5m", "15m"),
                start_time_utc_ms=start_ms,
                end_time_utc_ms=start_ms,
                as_of_utc_ms=start_ms + 24 * 60 * 60_000,
            ),
            mode=ResearchDataTaskMode.AUDIT,
        )
    )

    assert network_calls == []
    assert len(inspected) == 1
    assert inspected[0].revision == 8
    assert inspected[0].report.is_complete is False


def test_worker_cancels_audit_without_publishing_an_incomplete_report(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    StorageManager(db_path)
    start_ms = 1_767_225_600_000
    worker = ResearchBackfillWorker()
    inspected = []
    cancelled = []
    failures = []
    worker.inspected.connect(inspected.append)
    worker.cancelled.connect(cancelled.append)
    worker.failed.connect(failures.append)
    worker.cancellation_token.request()

    worker.run(
        ResearchBackfillTask(
            revision=9,
            db_path=str(db_path),
            request=ResearchRangeRequest(
                symbol="BTCUSDT",
                timeframes=("1m", "5m", "15m"),
                start_time_utc_ms=start_ms,
                end_time_utc_ms=start_ms,
                as_of_utc_ms=start_ms + 24 * 60 * 60_000,
            ),
            mode=ResearchDataTaskMode.AUDIT,
        )
    )

    assert inspected == []
    assert failures == []
    assert len(cancelled) == 1
    assert cancelled[0].revision == 9


def test_worker_routes_full_history_failure_with_partial_result(
    tmp_path,
) -> None:
    db_path = tmp_path / "research.db"
    storage = StorageManager(db_path)
    start_ms = 1_767_225_600_000
    btc = _stored_kline("1m", start_ms)
    btc["quote_volume"] = None
    eth = _stored_kline("1m", start_ms)
    eth["symbol"] = "ETHUSDT"
    eth["quote_volume"] = None
    storage.upsert_klines([btc, eth])
    worker = ResearchBackfillWorker(
        network_factory=_FailingSecondChunkNetwork
    )
    research_failures = []
    maintenance_failures = []
    worker.failed.connect(research_failures.append)
    worker.maintenanceFailed.connect(maintenance_failures.append)

    worker.run(
        ResearchBackfillTask(
            revision=10,
            db_path=str(db_path),
            request=None,
            mode=ResearchDataTaskMode.FULL_HISTORY,
        )
    )

    assert research_failures == []
    assert len(maintenance_failures) == 1
    assert maintenance_failures[0].result.completed_series == 1
    assert maintenance_failures[0].result.downloaded_bars == 1
