from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

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


def native_smoke_exit_delay_ms(
    environ: Mapping[str, str] | None = None,
) -> int | None:
    values = os.environ if environ is None else environ
    raw = values.get("QRC_NATIVE_SMOKE_EXIT_MS", "").strip()
    try:
        delay = int(raw)
    except ValueError:
        return None
    return delay if 1 <= delay <= 60_000 else None


_NATIVE_SMOKE_WORKSPACES = {
    "analysis",
    "decision_entry",
    "decision_exit",
    "version_report",
}


def native_smoke_workspace(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    values = os.environ if environ is None else environ
    value = values.get("QRC_NATIVE_SMOKE_WORKSPACE", "").strip().lower()
    return value if value in _NATIVE_SMOKE_WORKSPACES else None


def open_native_smoke_workspace(window, target: str) -> None:
    """Navigate through public window actions for opt-in packaged smoke tests."""

    if target == "analysis":
        window.open_analysis_workspace()
        return
    if target not in _NATIVE_SMOKE_WORKSPACES:
        raise ValueError(f"unknown native smoke workspace: {target}")
    window.open_decision_research_workspace()
    decision = window._analysis_workspace.decisionResearchWorkspace
    if target == "decision_entry":
        decision.modeTabs.setCurrentIndex(0)
    elif target == "decision_exit":
        decision.modeTabs.setCurrentIndex(1)
    elif target == "version_report":
        decision.stepButtons["version_report"].click()


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


@dataclass(frozen=True)
class StartupEvent:
    name: str
    elapsed_seconds: float


class StartupTimeline:
    """Opt-in startup milestones that stay silent during normal runs."""

    def __init__(
        self,
        *,
        enabled: bool,
        output_path: Path | None = None,
        clock: Callable[[], float] = time.perf_counter,
        started_at: float | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._output_path = output_path
        self._clock = clock
        self._started_at = started_at
        self._events: list[StartupEvent] = []

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> "StartupTimeline":
        values = os.environ if environ is None else environ
        enabled = values.get("QRC_STARTUP_TIMING", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        raw_path = values.get("QRC_STARTUP_TIMING_FILE", "").strip()
        raw_origin = values.get(
            "QRC_PROCESS_START_PERF_COUNTER",
            "",
        ).strip()
        try:
            process_origin = float(raw_origin) if raw_origin else None
        except ValueError:
            process_origin = None
        return cls(
            enabled=enabled,
            output_path=Path(raw_path) if raw_path else None,
            clock=clock,
            started_at=process_origin,
        )

    @property
    def events(self) -> tuple[StartupEvent, ...]:
        return tuple(self._events)

    def mark(self, name: str) -> None:
        if not self._enabled:
            return
        value = self._clock()
        if self._started_at is None:
            self._started_at = value
        if not self._events and name == "process_start":
            elapsed = 0.0
        else:
            elapsed = value - self._started_at
        self._events.append(
            StartupEvent(
                name=str(name),
                elapsed_seconds=round(elapsed, 6),
            )
        )

    def flush(self) -> None:
        if not self._enabled or self._output_path is None:
            return
        output = self._output_path
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.tmp")
        payload = {
            "events": [
                {
                    "name": event.name,
                    "elapsed_seconds": event.elapsed_seconds,
                }
                for event in self._events
            ]
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(output)


_STARTUP_TIMELINE = StartupTimeline.from_environment()
_STARTUP_TIMELINE.mark("process_start")


def mark_startup_stage(name: str, *, flush: bool = False) -> None:
    _STARTUP_TIMELINE.mark(name)
    if flush:
        try:
            _STARTUP_TIMELINE.flush()
        except OSError:
            # Diagnostics must never make the desktop application unavailable.
            pass


def startup_timeline() -> StartupTimeline:
    return _STARTUP_TIMELINE


@contextmanager
def measure_startup_step(name: str, metrics: StartupMetrics | None = None):
    started = time.perf_counter()
    try:
        yield
    finally:
        if metrics is not None:
            metrics.steps[name] = time.perf_counter() - started
