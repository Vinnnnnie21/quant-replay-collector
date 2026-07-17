from __future__ import annotations

from collections.abc import Callable
from typing import Any


SAFE_SHUTDOWN_MESSAGE = "正在安全保存任务"


class SafeShutdownCoordinator:
    def __init__(
        self,
        *,
        lifecycle: Any,
        save: Callable[[], None],
        stop_producers: Callable[[], None] | None = None,
        show_status: Callable[[str], None],
        schedule_poll: Callable[[Callable[[], None]], None],
        finalize: Callable[[], bool | None],
    ) -> None:
        self._lifecycle = lifecycle
        self._save = save
        self._stop_producers = stop_producers or (lambda: None)
        self._show_status = show_status
        self._schedule_poll = schedule_poll
        self._finalize = finalize
        self._save_attempted = False
        self._shutdown_started = False
        self._poll_scheduled = False
        self._finalized = False

    def request_close(self) -> bool:
        if self._finalized:
            return True
        if not self._shutdown_started:
            self._shutdown_started = True
            self._lifecycle.begin_shutdown()
            self._stop_producers()
        if self._lifecycle.active_tasks:
            self._show_status(SAFE_SHUTDOWN_MESSAGE)
        if not self._save_attempted:
            self._save_attempted = True
            self._save()
        if not self._lifecycle.active_tasks:
            return self._finish()
        self._lifecycle.request_stop_all()
        self._schedule_next_poll()
        return False

    def _schedule_next_poll(self) -> None:
        if self._poll_scheduled:
            return
        self._poll_scheduled = True
        self._schedule_poll(self._poll)

    def _poll(self) -> None:
        self._poll_scheduled = False
        if self._lifecycle.active_tasks:
            self._show_status(SAFE_SHUTDOWN_MESSAGE)
            self._lifecycle.request_stop_all()
            self._schedule_next_poll()
            return
        self._finish()

    def _finish(self) -> bool:
        if self._finalized:
            return True
        if self._finalize() is False:
            self._show_status(SAFE_SHUTDOWN_MESSAGE)
            self._schedule_next_poll()
            return False
        self._finalized = True
        return True


__all__ = ["SAFE_SHUTDOWN_MESSAGE", "SafeShutdownCoordinator"]
