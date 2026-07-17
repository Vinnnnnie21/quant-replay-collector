from __future__ import annotations

from collections.abc import Callable
from enum import Enum


class TaskState(str, Enum):
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    COMPLETED = "completed"
    FAILED = "failed"


class BackgroundTaskLifecycle:
    def __init__(self) -> None:
        self._states: dict[str, TaskState] = {}
        self._stop_requests: dict[str, Callable[[], None]] = {}
        self._errors: dict[str, str] = {}
        self._shutdown_in_progress = False

    @property
    def shutdown_in_progress(self) -> bool:
        return self._shutdown_in_progress

    @property
    def active_tasks(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, state in self._states.items()
            if state in {TaskState.RUNNING, TaskState.STOP_REQUESTED}
        )

    def state(self, name: str) -> TaskState | None:
        return self._states.get(name)

    def error(self, name: str) -> str | None:
        return self._errors.get(name)

    def start(self, name: str, *, request_stop: Callable[[], None] | None = None) -> bool:
        if self._shutdown_in_progress or name in self.active_tasks:
            return False
        self._states[name] = TaskState.RUNNING
        self._errors.pop(name, None)
        if request_stop is not None:
            self._stop_requests[name] = request_stop
        return True

    def begin_shutdown(self) -> None:
        self._shutdown_in_progress = True

    def complete(self, name: str) -> None:
        self._states[name] = TaskState.COMPLETED
        self._stop_requests.pop(name, None)

    def fail(self, name: str, error: str) -> None:
        self._states[name] = TaskState.FAILED
        self._errors[name] = str(error)
        self._stop_requests.pop(name, None)

    def request_stop_all(self) -> None:
        for name in self.active_tasks:
            if self._states[name] is not TaskState.RUNNING:
                continue
            self._states[name] = TaskState.STOP_REQUESTED
            request_stop = self._stop_requests.get(name)
            if request_stop is not None:
                try:
                    request_stop()
                except Exception as exc:
                    self._errors[name] = f"{type(exc).__name__}: {exc}"


__all__ = ["BackgroundTaskLifecycle", "TaskState"]
