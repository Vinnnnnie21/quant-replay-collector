from __future__ import annotations

from safe_shutdown import SafeShutdownCoordinator
from task_lifecycle import BackgroundTaskLifecycle, TaskState


def test_safe_shutdown_waits_for_active_task_without_discarding_it() -> None:
    lifecycle = BackgroundTaskLifecycle()
    stop_requests: list[bool] = []
    lifecycle.start("export", request_stop=lambda: stop_requests.append(True))
    messages: list[str] = []
    scheduled: list[object] = []
    finalized: list[bool] = []
    coordinator = SafeShutdownCoordinator(
        lifecycle=lifecycle,
        save=lambda: None,
        show_status=messages.append,
        schedule_poll=scheduled.append,
        finalize=lambda: finalized.append(True),
    )

    assert coordinator.request_close() is False
    assert messages == ["正在安全保存任务"]
    assert lifecycle.state("export") is TaskState.STOP_REQUESTED
    assert stop_requests == [True]
    assert finalized == []

    lifecycle.complete("export")
    scheduled.pop(0)()

    assert finalized == [True]


def test_safe_shutdown_keeps_waiting_until_thread_teardown_is_safe() -> None:
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[object] = []
    attempts = iter([False, True])
    coordinator = SafeShutdownCoordinator(
        lifecycle=lifecycle,
        save=lambda: None,
        show_status=lambda _message: None,
        schedule_poll=scheduled.append,
        finalize=lambda: next(attempts),
    )

    assert coordinator.request_close() is False
    assert len(scheduled) == 1

    scheduled.pop(0)()

    assert coordinator.request_close() is True


def test_safe_shutdown_stops_task_producers_before_saving() -> None:
    lifecycle = BackgroundTaskLifecycle()
    actions: list[str] = []
    coordinator = SafeShutdownCoordinator(
        lifecycle=lifecycle,
        save=lambda: actions.append("save"),
        stop_producers=lambda: actions.append("stop_producers"),
        show_status=lambda _message: None,
        schedule_poll=lambda _callback: None,
        finalize=lambda: True,
    )

    assert coordinator.request_close() is True

    assert lifecycle.shutdown_in_progress is True
    assert actions == ["stop_producers", "save"]


def test_safe_shutdown_poll_stops_an_unexpected_running_task_and_keeps_waiting() -> None:
    class Lifecycle:
        def __init__(self) -> None:
            self.active_tasks = ("market_data_load",)
            self.stop_requests: list[tuple[str, ...]] = []

        def begin_shutdown(self) -> None:
            pass

        def request_stop_all(self) -> None:
            self.stop_requests.append(self.active_tasks)

    lifecycle = Lifecycle()
    scheduled: list[object] = []
    finalized: list[bool] = []
    coordinator = SafeShutdownCoordinator(
        lifecycle=lifecycle,
        save=lambda: None,
        show_status=lambda _message: None,
        schedule_poll=scheduled.append,
        finalize=lambda: finalized.append(True),
    )

    assert coordinator.request_close() is False
    lifecycle.active_tasks = ("premium_sample",)
    scheduled.pop(0)()

    assert lifecycle.stop_requests == [("market_data_load",), ("premium_sample",)]
    assert finalized == []
    assert len(scheduled) == 1


def test_repeated_close_requests_save_session_only_once() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("export", request_stop=lambda: None)
    saves: list[bool] = []
    coordinator = SafeShutdownCoordinator(
        lifecycle=lifecycle,
        save=lambda: saves.append(True),
        show_status=lambda _message: None,
        schedule_poll=lambda _callback: None,
        finalize=lambda: True,
    )

    assert coordinator.request_close() is False
    assert coordinator.request_close() is False

    assert saves == [True]
