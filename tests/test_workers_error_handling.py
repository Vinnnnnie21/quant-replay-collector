from __future__ import annotations

import pytest


def test_export_worker_exposes_lifecycle_signals():
    pytest.importorskip("PySide6")
    from workers.export_worker import ExportWorker

    assert all(hasattr(ExportWorker, name) for name in ("started", "progress", "finished", "failed", "cancelled"))


def test_loader_worker_exposes_lifecycle_signals():
    pytest.importorskip("PySide6")
    from market_data import LoaderWorker

    assert all(hasattr(LoaderWorker, name) for name in ("started", "progress", "finished", "failed", "cancelled"))
