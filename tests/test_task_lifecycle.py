from __future__ import annotations

from task_lifecycle import BackgroundTaskLifecycle, TaskState


def test_task_lifecycle_reports_running_then_completed() -> None:
    lifecycle = BackgroundTaskLifecycle()

    assert lifecycle.start("market_data_load") is True
    assert lifecycle.state("market_data_load") is TaskState.RUNNING
    assert lifecycle.active_tasks == ("market_data_load",)

    lifecycle.complete("market_data_load")

    assert lifecycle.state("market_data_load") is TaskState.COMPLETED
    assert lifecycle.active_tasks == ()


def test_request_stop_all_marks_active_tasks_and_calls_their_stop_requests() -> None:
    lifecycle = BackgroundTaskLifecycle()
    stopped: list[str] = []
    lifecycle.start("export", request_stop=lambda: stopped.append("export"))
    lifecycle.start("premium_sample", request_stop=lambda: stopped.append("premium_sample"))

    lifecycle.request_stop_all()

    assert lifecycle.state("export") is TaskState.STOP_REQUESTED
    assert lifecycle.state("premium_sample") is TaskState.STOP_REQUESTED
    assert lifecycle.active_tasks == ("export", "premium_sample")
    assert stopped == ["export", "premium_sample"]


def test_task_lifecycle_reports_failure_and_error() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("analysis_refresh")

    lifecycle.fail("analysis_refresh", "calculation failed")

    assert lifecycle.state("analysis_refresh") is TaskState.FAILED
    assert lifecycle.error("analysis_refresh") == "calculation failed"
    assert lifecycle.active_tasks == ()


def test_stop_request_failure_does_not_skip_other_active_tasks() -> None:
    lifecycle = BackgroundTaskLifecycle()
    stopped: list[str] = []
    lifecycle.start(
        "market_data_load",
        request_stop=lambda: (_ for _ in ()).throw(RuntimeError("abort failed")),
    )
    lifecycle.start("export", request_stop=lambda: stopped.append("export"))

    lifecycle.request_stop_all()

    assert lifecycle.state("market_data_load") is TaskState.STOP_REQUESTED
    assert lifecycle.error("market_data_load") == "RuntimeError: abort failed"
    assert stopped == ["export"]


def test_shutdown_state_rejects_new_background_tasks() -> None:
    lifecycle = BackgroundTaskLifecycle()

    lifecycle.begin_shutdown()

    assert lifecycle.shutdown_in_progress is True
    assert lifecycle.start("premium_sample") is False
    assert lifecycle.state("premium_sample") is None
    assert lifecycle.active_tasks == ()
