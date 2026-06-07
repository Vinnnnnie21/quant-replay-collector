from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

try:
    from app_config import CACHE_DIR, DATA_DIR, EXPORT_DIR, LOG_DIR
except ImportError:  # pragma: no cover - package import path
    from .app_config import CACHE_DIR, DATA_DIR, EXPORT_DIR, LOG_DIR


def bootstrap_runtime_dirs() -> tuple[Path, ...]:
    paths = (DATA_DIR, CACHE_DIR, EXPORT_DIR, LOG_DIR)
    for path in paths:
        Path(path).mkdir(parents=True, exist_ok=True)
    return paths


def configure_logging() -> Path:
    try:
        from app_logger import setup_logging
    except ImportError:  # pragma: no cover - package import path
        from .app_logger import setup_logging

    return setup_logging()


@dataclass
class StartupMetrics:
    steps: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def measure(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.steps[name] = time.perf_counter() - started


@contextmanager
def measure_startup_step(name: str, metrics: StartupMetrics | None = None):
    started = time.perf_counter()
    try:
        yield
    finally:
        if metrics is not None:
            metrics.steps[name] = time.perf_counter() - started
