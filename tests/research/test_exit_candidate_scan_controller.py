from __future__ import annotations

import threading
import time

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")

from controllers.exit_candidate_scan_controller import ExitCandidateScanController
from research.exit_candidate_generation import (
    ExitCandidateMaturity,
    ExitCandidateReference,
    ExitCandidateScanCancelled,
    ExitCandidateScanRequest,
    ExitCandidateScanResult,
    ExitCandidateScanStatus,
    ExitCandidateScore,
)


def test_replaced_exit_scan_cannot_publish_result_for_old_setup():
    service = _ReplacingExitScanService()
    controller = ExitCandidateScanController(service)
    results = []
    cancellations = []
    controller.resultReady.connect(results.append)
    controller.cancelled.connect(lambda: cancellations.append(True))

    controller.start(ExitCandidateScanRequest("setup_old", "grouping_1", "LONG"))
    assert _wait_until(service.first_started.is_set)
    controller.start(ExitCandidateScanRequest("setup_new", "grouping_1", "LONG"))

    assert _wait_until(lambda: not controller.is_running)
    assert [result.setup_version_id for result in results] == ["setup_new"]
    assert results[0].usable_candidate_count == 1
    assert results[0].maturity.complete_exit_now_count == 10
    assert not hasattr(results[0], "candidates")
    assert cancellations == []
    assert controller.shutdown() is True


class _ReplacingExitScanService:
    def __init__(self) -> None:
        self.first_started = threading.Event()

    def scan(self, request, *, cancelled=None, progress=None):
        if request.setup_version_id == "setup_old":
            self.first_started.set()
            while not cancelled():
                time.sleep(0.005)
            raise ExitCandidateScanCancelled("replaced")
        if progress is not None:
            progress(1, 1)
        reference = ExitCandidateReference("exit_ref", "holding_ref", 90.0)
        return ExitCandidateScanResult(
            scan_id="exit_scan_new",
            setup_version_id=request.setup_version_id,
            grouping_version_id=request.grouping_version_id,
            direction=request.direction,
            formula_version="exit_formula_v1",
            feature_version="feature_v1",
            status=ExitCandidateScanStatus.COMPLETED,
            maturity=ExitCandidateMaturity(10, 5),
            candidate_universe_count=1,
            unavailable_candidate_count=0,
            candidates=(
                ExitCandidateScore(
                    decision_event_id="secret_exit_candidate",
                    holding_episode_id="secret_holding_episode",
                    similarity=90.0,
                    references=(reference, reference, reference),
                    completeness_ratio=1.0,
                    diversity_vector=(0.1,) * 13,
                ),
            ),
        )


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
