from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6 import QtWidgets

from main_app import MainWindow
from analysis_workspace import AnalysisWorkspace
from multi_timeframe_panel import MultiTimeframePanel
from safe_shutdown import SafeShutdownCoordinator
from task_lifecycle import BackgroundTaskLifecycle


class _CloseEvent:
    def __init__(self) -> None:
        self.ignored = False
        self.accepted = False

    def ignore(self) -> None:
        self.ignored = True

    def accept(self) -> None:
        self.accepted = True


def test_main_window_ignores_close_while_safe_shutdown_is_waiting() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("market_data_load", request_stop=lambda: None)
    coordinator = SafeShutdownCoordinator(
        lifecycle=lifecycle,
        save=lambda: None,
        show_status=lambda _message: None,
        schedule_poll=lambda _callback: None,
        finalize=lambda: None,
    )
    window = SimpleNamespace(_safe_shutdown_coordinator=coordinator)
    event = _CloseEvent()

    MainWindow.closeEvent(window, event)

    assert event.ignored is True
    assert event.accepted is False


def test_main_window_releases_graphics_only_after_safe_shutdown_is_ready() -> None:
    order: list[str] = []

    class Coordinator:
        def request_close(self) -> bool:
            order.append("workers_and_producers_stopped")
            return True

    window = SimpleNamespace(
        _safe_shutdown_coordinator=Coordinator(),
        _shutdown_graphics=lambda: order.append("graphics_released"),
    )
    event = _CloseEvent()

    MainWindow.closeEvent(window, event)

    assert order == ["workers_and_producers_stopped", "graphics_released"]
    assert event.accepted is True
    assert event.ignored is False


def test_full_history_partial_result_is_not_presented_as_complete() -> None:
    messages: list[str] = []
    translations = {
        "settings.full_history_backfill_complete": (
            "complete {completed}/{total} {bars}"
        ),
        "settings.full_history_backfill_partial": (
            "partial {completed}/{total} {bars}"
        ),
    }
    window = SimpleNamespace(
        tr=translations.__getitem__,
        status=SimpleNamespace(setText=messages.append),
        _log=messages.append,
    )
    event = SimpleNamespace(
        result=SimpleNamespace(
            completed_series=1,
            total_series=2,
            downloaded_bars=10,
            is_complete=False,
        )
    )

    MainWindow._on_full_history_backfill_finished(window, event)

    assert messages == ["partial 1/2 10", "partial 1/2 10"]


def test_analysis_workspace_waits_for_research_snapshot_controller_shutdown() -> None:
    calls: list[str] = []

    class SnapshotController:
        def shutdown(self) -> bool:
            calls.append("snapshot")
            return False

    workspace = SimpleNamespace(
        entry_candidate_controller=None,
        exit_candidate_controller=None,
        entry_behavior_training_controller=None,
        entry_outcome_comparison_controller=None,
        exit_outcome_comparison_controller=None,
        research_snapshot_controller=SnapshotController(),
        historical_performance_controller=None,
    )

    assert AnalysisWorkspace.shutdown(workspace) is False
    assert calls == ["snapshot"]


def test_main_window_stops_premium_timer_when_safe_shutdown_starts() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("market_data_load", request_stop=lambda: None)
    stopped: list[str] = []
    window = SimpleNamespace(
        premium_timer=SimpleNamespace(stop=lambda: stopped.append("premium_timer")),
    )
    window._safe_shutdown_coordinator = SafeShutdownCoordinator(
        lifecycle=lifecycle,
        save=lambda: None,
        stop_producers=lambda: MainWindow._stop_shutdown_producers(window),
        show_status=lambda _message: None,
        schedule_poll=lambda _callback: None,
        finalize=lambda: True,
    )
    event = _CloseEvent()

    MainWindow.closeEvent(window, event)

    assert stopped == ["premium_timer"]
    assert event.ignored is True
    assert event.accepted is False


def test_main_window_surfaces_daily_backup_failure(tmp_path) -> None:
    messages: list[str] = []
    logs: list[str] = []
    window = SimpleNamespace(
        storage=SimpleNamespace(
            db_path=tmp_path / "missing.db",
            backup_dir=tmp_path / "backups",
        ),
        status=SimpleNamespace(setText=messages.append),
        _log=logs.append,
    )

    result = MainWindow._backup_local_database(window)

    assert result["status"] == "failed"
    assert "数据库备份失败" in messages[0]
    assert logs == messages


def test_daily_backup_progress_does_not_overwrite_foreground_task_status() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("market_data_load")
    messages: list[str] = []
    window = SimpleNamespace(
        task_lifecycle=lifecycle,
        status=SimpleNamespace(setText=messages.append),
    )

    MainWindow._on_daily_backup_progress(window, "Backing up... 50%")

    assert messages == []

    lifecycle.complete("market_data_load")
    lifecycle.start("daily_backup")
    MainWindow._on_daily_backup_progress(window, "Backing up... 50%")
    assert messages == ["Backing up... 50%"]


def test_main_window_does_not_finalize_while_worker_thread_is_still_running() -> None:
    class Thread:
        def __init__(self, stopped: bool) -> None:
            self.stopped = stopped
            self.quit_calls = 0

        def isRunning(self) -> bool:
            return not self.stopped

        def quit(self) -> None:
            self.quit_calls += 1

        def wait(self, _timeout: int) -> bool:
            return self.stopped

    active = Thread(stopped=False)
    stopped = Thread(stopped=True)
    window = SimpleNamespace(
        export_task_controller=SimpleNamespace(shutdown=lambda: None),
        analysis_refresh_controller=SimpleNamespace(shutdown=lambda: None),
        loader_thread=active,
        premium_thread=stopped,
        _handling_close_event=False,
        close=lambda: (_ for _ in ()).throw(AssertionError("must not close")),
    )

    assert MainWindow._finalize_shutdown(window) is False
    assert active.quit_calls == 1


def test_main_window_does_not_finalize_until_all_controller_threads_finish() -> None:
    stopped_thread = SimpleNamespace(isRunning=lambda: False)
    close_calls: list[bool] = []
    window = SimpleNamespace(
        daily_backup_controller=SimpleNamespace(shutdown=lambda: False),
        export_task_controller=SimpleNamespace(shutdown=lambda: True),
        analysis_refresh_controller=SimpleNamespace(shutdown=lambda: True),
        loader_thread=stopped_thread,
        premium_thread=stopped_thread,
        _handling_close_event=False,
        close=lambda: close_calls.append(True),
    )

    assert MainWindow._finalize_shutdown(window) is False
    assert close_calls == []


def test_main_window_waits_for_research_backfill_thread_teardown() -> None:
    stopped_thread = SimpleNamespace(isRunning=lambda: False)
    window = SimpleNamespace(
        daily_backup_controller=SimpleNamespace(shutdown=lambda: True),
        export_task_controller=SimpleNamespace(shutdown=lambda: True),
        analysis_refresh_controller=SimpleNamespace(shutdown=lambda: True),
        research_backfill_controller=SimpleNamespace(
            shutdown=lambda: False
        ),
        loader_thread=stopped_thread,
        premium_thread=stopped_thread,
        _handling_close_event=False,
        close=lambda: (_ for _ in ()).throw(
            AssertionError("must not close")
        ),
    )

    assert MainWindow._finalize_shutdown(window) is False


def test_main_window_waits_for_multi_timeframe_thread_teardown() -> None:
    stopped_thread = SimpleNamespace(isRunning=lambda: False)
    window = SimpleNamespace(
        multiTimeframePanel=SimpleNamespace(shutdown=lambda **_kwargs: False),
        export_task_controller=SimpleNamespace(shutdown=lambda: None),
        analysis_refresh_controller=SimpleNamespace(shutdown=lambda: None),
        loader_thread=stopped_thread,
        premium_thread=stopped_thread,
        _handling_close_event=False,
        close=lambda: (_ for _ in ()).throw(AssertionError("must not close")),
    )

    assert MainWindow._finalize_shutdown(window) is False


def test_export_after_shutdown_does_not_change_ui_or_start_worker() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.begin_shutdown()
    starts: list[tuple] = []
    enabled: list[bool] = []
    messages: list[str] = []
    export_state = SimpleNamespace(running=False, last_error="unchanged")
    window = SimpleNamespace(
        task_lifecycle=lifecycle,
        session_id="sess_1",
        current_language="zh_CN",
        app_state=SimpleNamespace(export=export_state),
        export_task_controller=SimpleNamespace(
            is_running=False,
            start=lambda *args: starts.append(args) or True,
        ),
        storage=SimpleNamespace(db_path=Path("research.db")),
        btnExport=SimpleNamespace(setEnabled=enabled.append),
        status=SimpleNamespace(setText=messages.append),
        _export_success_callback=None,
    )

    assert MainWindow.start_export_task(window, Path("exports")) is False

    assert starts == []
    assert export_state.running is False
    assert export_state.last_error == "unchanged"
    assert enabled == []
    assert messages == []
    assert lifecycle.state("export") is None


def test_export_click_after_shutdown_does_not_open_directory_dialog(monkeypatch) -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.begin_shutdown()
    dialog_calls: list[bool] = []
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        lambda *_args: dialog_calls.append(True) or "",
    )
    window = SimpleNamespace(
        task_lifecycle=lifecycle,
        session_id="sess_1",
    )

    MainWindow.export_session(window)

    assert dialog_calls == []


def test_safe_shutdown_paths_do_not_force_terminate_workers() -> None:
    shutdown_source = "\n".join(
        (
            inspect.getsource(SafeShutdownCoordinator),
            inspect.getsource(MainWindow._finalize_shutdown),
            inspect.getsource(MultiTimeframePanel.shutdown),
        )
    )

    assert ".terminate(" not in shutdown_source
    assert ".wait(" not in shutdown_source
    assert ".kill(" not in shutdown_source


def test_production_code_has_no_unbounded_qthread_wait() -> None:
    production = Path("quant_collector_app")
    offenders = [
        str(path)
        for path in production.rglob("*.py")
        if ".wait()" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
