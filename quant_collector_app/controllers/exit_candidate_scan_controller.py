from __future__ import annotations

from typing import Any, Callable

from PySide6 import QtCore

try:
    from controllers.entry_candidate_scan_controller import (
        EntryCandidateScanController,
    )
    from research.exit_candidate_generation import exit_candidate_scan_overview
except ImportError:  # pragma: no cover - package import path
    from .entry_candidate_scan_controller import EntryCandidateScanController
    from ..research.exit_candidate_generation import exit_candidate_scan_overview


class ExitCandidateScanController(EntryCandidateScanController):
    """Exit semantics adapter over the shared cancellable scan lifecycle."""

    def __init__(
        self,
        service: Any,
        *,
        worker_factory: Callable[..., Any] | None = None,
        thread_factory: Callable[[QtCore.QObject], Any] | None = None,
        lifecycle: Any | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        options: dict[str, Any] = {
            "lifecycle": lifecycle,
            "overview_factory": exit_candidate_scan_overview,
            "task_key": "exit_candidate_scan",
            "parent": parent,
        }
        if worker_factory is not None:
            options["worker_factory"] = worker_factory
        if thread_factory is not None:
            options["thread_factory"] = thread_factory
        super().__init__(service, **options)


__all__ = ["ExitCandidateScanController"]
