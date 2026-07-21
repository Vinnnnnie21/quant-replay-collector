from __future__ import annotations

import threading
import time

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")

from controllers.entry_candidate_scan_controller import EntryCandidateScanController
from research.entry_candidate_generation import (
    CandidateMaturity,
    CandidateReference,
    CandidateScanCancelled,
    CandidateScanRequest,
    CandidateScanResult,
    CandidateScanStatus,
    EntryCandidateScore,
)
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


class _ReplacingScanService:
    def __init__(self) -> None:
        self.first_started = threading.Event()
        self.thread_ids: list[int] = []

    def scan(self, request, *, cancelled=None, progress=None):
        self.thread_ids.append(threading.get_ident())
        if request.setup_version_id == "setup_old":
            self.first_started.set()
            while not cancelled():
                time.sleep(0.005)
            raise CandidateScanCancelled("replaced")
        if progress is not None:
            progress(1, 1)
        return CandidateScanResult(
            scan_id="scan_new",
            setup_version_id=request.setup_version_id,
            grouping_version_id=request.grouping_version_id,
            direction=request.direction,
            formula_version="formula_v1",
            feature_version="feature_v1",
            status=CandidateScanStatus.COMPLETED,
            maturity=CandidateMaturity(10, 5),
            candidate_universe_count=0,
            unavailable_candidate_count=0,
            candidates=(
                EntryCandidateScore(
                    source_sample_id="secret_candidate",
                    episode_id="secret_episode",
                    similarity=99.0,
                    references=(
                        CandidateReference("secret_ref", "secret_ref_ep", 99.0),
                    ) * 3,
                    completeness_ratio=1.0,
                    diversity_vector=(0.1,) * 12,
                ),
            ),
        )


def test_replaced_scan_is_cancelled_and_cannot_overwrite_new_setup_result():
    service = _ReplacingScanService()
    controller = EntryCandidateScanController(service)
    results = []
    cancellations = []
    controller.resultReady.connect(results.append)
    controller.cancelled.connect(lambda: cancellations.append(True))
    main_thread_id = threading.get_ident()

    controller.start(CandidateScanRequest("setup_old", "grouping_1", "LONG"))
    assert _wait_until(service.first_started.is_set)
    controller.start(CandidateScanRequest("setup_new", "grouping_1", "LONG"))

    assert _wait_until(lambda: not controller.is_running)
    assert [result.setup_version_id for result in results] == ["setup_new"]
    assert results[0].usable_candidate_count == 1
    assert not hasattr(results[0], "candidates")
    assert cancellations == []
    assert service.thread_ids
    assert all(thread_id != main_thread_id for thread_id in service.thread_ids)
    assert controller.shutdown() is True


def test_scan_start_failure_releases_shared_lifecycle_and_reports_error():
    lifecycle = BackgroundTaskLifecycle()
    controller = EntryCandidateScanController(
        _ReplacingScanService(),
        lifecycle=lifecycle,
        thread_factory=lambda _parent: (_ for _ in ()).throw(
            RuntimeError("thread construction failed")
        ),
    )
    failures = []
    controller.failed.connect(failures.append)

    revision = controller.start(
        CandidateScanRequest("setup_new", "grouping_1", "LONG")
    )

    assert revision == 1
    assert failures == ["RuntimeError: thread construction failed"]
    assert controller.is_running is False
    assert lifecycle.state("entry_candidate_scan") is TaskState.FAILED


def test_context_invalidation_cancels_scan_without_publishing_old_terminal():
    service = _ReplacingScanService()
    controller = EntryCandidateScanController(service)
    results = []
    cancellations = []
    controller.resultReady.connect(results.append)
    controller.cancelled.connect(lambda: cancellations.append(True))

    controller.start(CandidateScanRequest("setup_old", "grouping_1", "LONG"))
    assert _wait_until(service.first_started.is_set)
    controller.invalidate()

    assert _wait_until(lambda: not controller.is_running)
    assert results == []
    assert cancellations == []
