from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow


class _Text:
    def __init__(self, value: str):
        self.value = value

    def currentText(self) -> str:
        return self.value


class _SignalRecorder:
    def __init__(self) -> None:
        self.count = 0

    def emit(self) -> None:
        self.count += 1


class _TradeController:
    def __init__(self, fail_commit: bool = False) -> None:
        self.commits = 0
        self.prepares = 0
        self.undos = 0
        self.fail_commit = fail_commit
        self.close_trade_ids: list[str] = []
        self.close_kwargs: list[dict] = []

    def prepare_open(self, *_args, **_kwargs):
        self.prepares += 1
        return SimpleNamespace(
            trade_row={"trade_id": "trd_1", "side": "LONG", "status": "OPEN", "interval": "5m"},
            event_row={"event_id": "evt_1", "event_type": "OPEN_LONG", "interval": "5m"},
        )

    def commit_open(self, _transaction) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def undo_open(self, _transaction) -> None:
        self.undos += 1

    def prepare_close(self, *_args, **kwargs):
        self.prepares += 1
        trade = kwargs["trade"]
        self.close_trade_ids.append(trade["trade_id"])
        self.close_kwargs.append(dict(kwargs))
        return SimpleNamespace(
            original_trade=dict(trade),
            event_row={
                "event_id": kwargs["event_id"],
                "trade_id": trade["trade_id"],
                "event_type": "CLOSE",
                "side": trade["side"],
                "interval": trade["interval"],
            },
            close_update={
                "trade_id": trade["trade_id"],
                "status": "CLOSED",
                "exit_event_id": kwargs["event_id"],
                "exit_bar_index": kwargs["event_idx"],
                "exit_reason": kwargs.get("exit_reason"),
                "exit_fill_price": kwargs.get("override_exit_price"),
            },
        )

    def commit_close(self, transaction) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def undo_close(self, _transaction, _updated_at: str) -> None:
        self.undos += 1


def test_request_open_trade_pauses_replay_and_clears_accumulated_bars():
    trade_controller = _TradeController()
    research_changed = _SignalRecorder()
    calls: list[str] = []
    row = pd.Series(
        {
            "bar_index": 10,
            "open_time_bjt": "2024-04-01T10:00:00+08:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
    )
    window = SimpleNamespace(
        df=pd.DataFrame([row]),
        cursor=10,
        playing=True,
        follow_latest=True,
        user_view_lock=False,
        _accum=3.5,
        replay_controller=SimpleNamespace(playing=True, accumulated_bars=3.5),
        _is_trade_recording_allowed=lambda: True,
        _warn_trade_interval_mismatch=lambda: None,
        session_id="sess_1",
        persist_session_state=lambda: calls.append("persist"),
        current_bar=lambda: row,
        current_tags_and_note=lambda: ([], ""),
        _new_id=lambda prefix: {"evt": "evt_1", "trd": "trd_1"}.get(prefix, f"{prefix}_1"),
        trade_controller=trade_controller,
        symbolBox=_Text("BTCUSDT"),
        intervalBox=_Text("5m"),
        execution_settings=lambda: object(),
        _trade_by_id={},
        _event_by_id={},
        trades=[],
        events=[],
        _sample_market_key=None,
        _display_market_key=("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
        _current_market_key=lambda: ("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
        _sample_cursor_bar_index=0,
        _refresh_tables=lambda include_heavy=True: calls.append(f"refresh_tables:{include_heavy}"),
        analysis_refresh_controller=SimpleNamespace(
            schedule=lambda: calls.append("deferred_analysis_refresh")
        ),
        _populate_event_study_table=lambda: calls.append("heavy_event_study"),
        _refresh_dataset_summary=lambda: calls.append("heavy_dataset_summary"),
        _refresh_performance_summary=lambda: calls.append("heavy_performance_summary"),
        _render=lambda force=False: calls.append(f"render:{force}"),
        _log=lambda message: calls.append(message),
        _update_load_play_button=lambda: calls.append("button"),
        _update_trade_buttons_enabled=lambda: calls.append("trade_buttons"),
        _log_slow_operation=lambda *_args, **_kwargs: None,
        _trade_transaction_active=False,
        execute_command=lambda command: command.do() or True,
        decisionResearchSourceChanged=research_changed,
    )

    MainWindow.request_open_trade(window, "LONG")

    # Manual trades no longer pause playback; playback state is left untouched.
    assert window.playing is True
    assert window.replay_controller.playing is True
    assert window.replay_controller.accumulated_bars == 3.5
    assert window._accum == 3.5
    assert window.follow_latest is True
    assert window.replay_controller.follow_latest is True
    assert trade_controller.commits == 1
    assert window._trade_transaction_active is False
    assert window.trades[0]["trade_id"] == "trd_1"
    assert "refresh_tables:False" in calls
    assert "deferred_analysis_refresh" in calls
    assert "heavy_event_study" not in calls
    assert "heavy_dataset_summary" not in calls
    assert "heavy_performance_summary" not in calls
    assert research_changed.count == 1


def test_request_open_trade_redo_reuses_prepared_payload_without_reprepare():
    trade_controller = _TradeController()
    calls: list[str] = []
    row = pd.Series(
        {
            "bar_index": 10,
            "open_time_bjt": "2024-04-01T10:00:00+08:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
    )
    window = SimpleNamespace(
        df=pd.DataFrame([row]),
        cursor=10,
        playing=False,
        _accum=0.0,
        replay_controller=SimpleNamespace(playing=False, accumulated_bars=0.0),
        _is_trade_recording_allowed=lambda: True,
        _warn_trade_interval_mismatch=lambda: None,
        session_id="sess_1",
        persist_session_state=lambda: calls.append("persist"),
        current_bar=lambda: row,
        current_tags_and_note=lambda: ([], ""),
        _new_id=lambda prefix: {"evt": "evt_1", "trd": "trd_1"}.get(prefix, f"{prefix}_1"),
        trade_controller=trade_controller,
        symbolBox=_Text("BTCUSDT"),
        intervalBox=_Text("5m"),
        execution_settings=lambda: object(),
        _trade_by_id={},
        _event_by_id={},
        trades=[],
        events=[],
        _sample_market_key=None,
        _display_market_key=("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
        _current_market_key=lambda: ("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
        _sample_cursor_bar_index=0,
        _refresh_tables=lambda include_heavy=True: calls.append(f"refresh_tables:{include_heavy}"),
        analysis_refresh_controller=SimpleNamespace(
            schedule=lambda: calls.append("deferred_analysis_refresh")
        ),
        _render=lambda force=False: calls.append(f"render:{force}"),
        _log=lambda message: calls.append(message),
        _update_load_play_button=lambda: calls.append("button"),
        _update_trade_buttons_enabled=lambda: calls.append("trade_buttons"),
        _operation_error=lambda title, exc: calls.append(f"operation_error:{title}:{type(exc).__name__}"),
        _log_slow_operation=lambda *_args, **_kwargs: None,
        _trade_transaction_active=False,
        undo_stack=[],
        redo_stack=[],
    )
    window.execute_command = lambda command: MainWindow.execute_command(window, command)

    MainWindow.request_open_trade(window, "LONG")
    MainWindow.undo(window)
    MainWindow.redo(window)

    assert trade_controller.prepares == 1
    assert trade_controller.commits == 2
    assert trade_controller.undos == 1
    assert len(window.trades) == 1
    assert len(window.events) == 1


def test_request_close_trade_pauses_replay_and_updates_memory_without_heavy_refresh():
    trade_controller = _TradeController()
    research_changed = _SignalRecorder()
    calls: list[str] = []
    row = pd.Series(
        {
            "bar_index": 12,
            "open_time_bjt": "2024-04-01T10:10:00+08:00",
            "open": 102.0,
            "high": 103.0,
            "low": 101.0,
            "close": 102.5,
            "volume": 1000.0,
        }
    )
    trade = {
        "trade_id": "trd_1",
        "session_id": "sess_1",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "side": "LONG",
        "status": "OPEN",
        "entry_event_id": "evt_open",
        "entry_bar_index": 10,
    }
    window = SimpleNamespace(
        df=pd.DataFrame([row]),
        cursor=12,
        playing=True,
        follow_latest=True,
        user_view_lock=False,
        _accum=2.0,
        replay_controller=SimpleNamespace(playing=True, accumulated_bars=2.0),
        _is_trade_recording_allowed=lambda: True,
        _warn_trade_interval_mismatch=lambda: None,
        selected_open_trade=lambda verify_db=False: trade,
        current_bar=lambda: row,
        current_tags_and_note=lambda: ([], ""),
        _new_id=lambda prefix: {"evt": "evt_close"}.get(prefix, f"{prefix}_1"),
        trade_controller=trade_controller,
        execution_settings=lambda: object(),
        _trade_by_id={"trd_1": trade},
        _event_by_id={"evt_open": {"event_id": "evt_open", "trade_id": "trd_1"}},
        trades=[trade],
        events=[{"event_id": "evt_open", "trade_id": "trd_1"}],
        _sample_cursor_bar_index=10,
        persist_session_state=lambda: calls.append("persist"),
        _sync_equity_curve=lambda: calls.append("sync_equity"),
        _refresh_tables=lambda include_heavy=True: calls.append(f"refresh_tables:{include_heavy}"),
        analysis_refresh_controller=SimpleNamespace(
            schedule=lambda: calls.append("deferred_analysis_refresh")
        ),
        _populate_event_study_table=lambda: calls.append("heavy_event_study"),
        _refresh_dataset_summary=lambda: calls.append("heavy_dataset_summary"),
        _refresh_performance_summary=lambda: calls.append("heavy_performance_summary"),
        _render=lambda force=False: calls.append(f"render:{force}"),
        _log=lambda message: calls.append(message),
        _update_load_play_button=lambda: calls.append("button"),
        _update_trade_buttons_enabled=lambda: calls.append("trade_buttons"),
        _log_slow_operation=lambda *_args, **_kwargs: None,
        _trade_transaction_active=False,
        execute_command=lambda command: command.do() or True,
        decisionResearchSourceChanged=research_changed,
    )

    MainWindow.request_close_trade(window, "LONG")

    # Manual trades no longer pause playback; playback state is left untouched.
    assert window.playing is True
    assert window.replay_controller.playing is True
    assert window.replay_controller.accumulated_bars == 2.0
    assert window._accum == 2.0
    assert window.follow_latest is True
    assert window.replay_controller.follow_latest is True
    assert trade_controller.commits == 1
    assert window._trade_transaction_active is False
    assert trade["status"] == "CLOSED"
    assert window._trade_by_id["trd_1"]["status"] == "CLOSED"
    assert window.events[-1]["event_id"] == "evt_close"
    assert window._event_by_id["evt_close"]["event_type"] == "CLOSE"
    assert window._sample_cursor_bar_index == 12
    assert "sync_equity" in calls
    assert "refresh_tables:False" in calls
    assert "deferred_analysis_refresh" in calls
    assert "heavy_event_study" not in calls
    assert "heavy_dataset_summary" not in calls
    assert "heavy_performance_summary" not in calls
    assert research_changed.count == 1


def test_request_close_trade_without_selection_closes_earliest_matching_position():
    QtCore = pytest.importorskip("PySide6.QtCore")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    trade_controller = _TradeController()
    calls: list[str] = []
    row = pd.Series(
        {
            "bar_index": 12,
            "open_time_bjt": "2024-04-01T10:10:00+08:00",
            "open": 102.0,
            "high": 103.0,
            "low": 101.0,
            "close": 102.5,
            "volume": 1000.0,
        }
    )
    earliest = {
        "trade_id": "trd_earliest",
        "session_id": "sess_1",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "side": "LONG",
        "status": "OPEN",
        "entry_event_id": "evt_1",
        "entry_bar_index": 8,
        "created_at": "2024-04-01T10:00:00+08:00",
    }
    later = {
        **earliest,
        "trade_id": "trd_later",
        "entry_event_id": "evt_2",
        "entry_bar_index": 10,
        "created_at": "2024-04-01T10:05:00+08:00",
    }
    table = QtWidgets.QTableWidget()
    table.setColumnCount(1)
    table.setRowCount(2)
    for index, trade_id in enumerate(("trd_later", "trd_earliest")):
        item = QtWidgets.QTableWidgetItem(trade_id)
        item.setData(QtCore.Qt.UserRole, trade_id)
        table.setItem(index, 0, item)
    table.clearSelection()
    window = SimpleNamespace(
        df=pd.DataFrame([row]),
        cursor=12,
        playing=False,
        _accum=0.0,
        replay_controller=SimpleNamespace(playing=False, accumulated_bars=0.0),
        _is_trade_recording_allowed=lambda: True,
        _warn_trade_interval_mismatch=lambda: None,
        selected_open_trade=lambda verify_db=False: None,
        _selected_id_from_table=lambda _table: None,
        openTradesTable=table,
        current_bar=lambda: row,
        current_tags_and_note=lambda: ([], ""),
        _new_id=lambda prefix: {"evt": "evt_close"}.get(prefix, f"{prefix}_1"),
        trade_controller=trade_controller,
        execution_settings=lambda: object(),
        _trade_by_id={"trd_earliest": earliest, "trd_later": later},
        _event_by_id={},
        trades=[earliest, later],
        events=[],
        _sample_cursor_bar_index=10,
        persist_session_state=lambda: calls.append("persist"),
        _sync_equity_curve=lambda: calls.append("sync_equity"),
        _refresh_tables=lambda include_heavy=True: calls.append(f"refresh_tables:{include_heavy}"),
        analysis_refresh_controller=SimpleNamespace(schedule=lambda: calls.append("deferred_analysis_refresh")),
        _render=lambda force=False: calls.append(f"render:{force}"),
        _log=lambda message: calls.append(message),
        _update_load_play_button=lambda: calls.append("button"),
        _update_trade_buttons_enabled=lambda: calls.append("trade_buttons"),
        _log_slow_operation=lambda *_args, **_kwargs: None,
        _trade_transaction_active=False,
        execute_command=lambda command: command.do() or True,
    )

    MainWindow.request_close_trade(window, "LONG")

    assert trade_controller.close_trade_ids == ["trd_earliest"]
    assert earliest["status"] == "CLOSED"
    assert later["status"] == "OPEN"
    app.processEvents()


def test_apply_tp_sl_triggers_closes_open_trade_at_trigger_price():
    trade_controller = _TradeController()
    calls: list[str] = []
    bars = pd.DataFrame(
        [
            {
                "bar_index": 0,
                "open_time_bjt": "2024-04-01T10:00:00+08:00",
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.0,
                "volume": 1000.0,
            },
            {
                "bar_index": 1,
                "open_time_bjt": "2024-04-01T10:05:00+08:00",
                "open": 100.0,
                "high": 103.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 1000.0,
            },
        ]
    )
    trade = {
        "trade_id": "trd_1",
        "session_id": "sess_1",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "side": "LONG",
        "status": "OPEN",
        "entry_event_id": "evt_open",
        "entry_bar_index": 0,
        "entry_fill_price": 100.0,
        "take_profit_price": 102.0,
        "stop_loss_price": 99.0,
    }
    window = SimpleNamespace(
        df=bars,
        cursor=1,
        trade_controller=trade_controller,
        execution_settings=lambda: object(),
        _trade_by_id={"trd_1": trade},
        _event_by_id={},
        trades=[trade],
        events=[],
        _new_id=lambda prefix: {"evt": "evt_auto_close"}.get(prefix, f"{prefix}_1"),
        persist_session_state=lambda: calls.append("persist"),
        _sync_equity_curve=lambda: calls.append("sync_equity"),
        _refresh_tables=lambda include_heavy=True: calls.append(f"refresh_tables:{include_heavy}"),
        analysis_refresh_controller=SimpleNamespace(schedule=lambda: calls.append("deferred_analysis_refresh")),
        _log=lambda message: calls.append(message),
        _chart_render_state=lambda: SimpleNamespace(mark_events_changed=lambda: calls.append("events_changed")),
    )

    MainWindow._apply_tp_sl_triggers(window, 0, 1)

    assert trade["status"] == "CLOSED"
    assert trade["exit_reason"] == "TAKE_PROFIT"
    assert trade["exit_fill_price"] == 102.0
    assert trade_controller.close_kwargs[0]["override_exit_price"] == 102.0
    assert trade_controller.close_kwargs[0]["exit_reason"] == "TAKE_PROFIT"
    assert calls.count("persist") == 1
    assert "sync_equity" in calls
    assert "refresh_tables:False" in calls


def test_tp_sl_scan_skips_dataframe_conversion_without_risk_managed_open_positions():
    class Frame:
        def __len__(self):
            return 14_880

        def to_dict(self, *_args, **_kwargs):
            raise AssertionError("full dataframe conversion must not run")

    window = SimpleNamespace(
        df=Frame(),
        trades=[{"trade_id": "closed", "status": "CLOSED"}],
        _trade_by_id={},
    )

    assert MainWindow._apply_tp_sl_triggers(window, 100, 101) == 0


def test_request_open_trade_restores_trade_buttons_after_transaction_error():
    trade_controller = _TradeController(fail_commit=True)
    calls: list[str] = []
    row = pd.Series(
        {
            "bar_index": 10,
            "open_time_bjt": "2024-04-01T10:00:00+08:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
    )
    window = SimpleNamespace(
        df=pd.DataFrame([row]),
        cursor=10,
        playing=True,
        _accum=3.5,
        replay_controller=SimpleNamespace(playing=True, accumulated_bars=3.5),
        _is_trade_recording_allowed=lambda: True,
        _warn_trade_interval_mismatch=lambda: None,
        session_id="sess_1",
        persist_session_state=lambda: calls.append("persist"),
        current_bar=lambda: row,
        current_tags_and_note=lambda: ([], ""),
        _new_id=lambda prefix: {"evt": "evt_1", "trd": "trd_1"}.get(prefix, f"{prefix}_1"),
        trade_controller=trade_controller,
        symbolBox=_Text("BTCUSDT"),
        intervalBox=_Text("5m"),
        execution_settings=lambda: object(),
        _trade_by_id={},
        _event_by_id={},
        trades=[],
        events=[],
        _sample_market_key=None,
        _display_market_key=("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
        _current_market_key=lambda: ("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
        _sample_cursor_bar_index=0,
        _refresh_tables=lambda include_heavy=True: calls.append(f"refresh_tables:{include_heavy}"),
        analysis_refresh_controller=SimpleNamespace(
            schedule=lambda: calls.append("deferred_analysis_refresh")
        ),
        _populate_event_study_table=lambda: calls.append("heavy_event_study"),
        _refresh_dataset_summary=lambda: calls.append("heavy_dataset_summary"),
        _refresh_performance_summary=lambda: calls.append("heavy_performance_summary"),
        _render=lambda force=False: calls.append(f"render:{force}"),
        _log=lambda message: calls.append(message),
        _update_load_play_button=lambda: calls.append("button"),
        _update_trade_buttons_enabled=lambda: calls.append("trade_buttons"),
        _operation_error=lambda title, exc: calls.append(f"operation_error:{title}:{type(exc).__name__}"),
        _log_slow_operation=lambda *_args, **_kwargs: None,
        _trade_transaction_active=False,
        undo_stack=[],
        redo_stack=[],
    )
    window.execute_command = lambda command: MainWindow.execute_command(window, command)

    MainWindow.request_open_trade(window, "LONG")

    # Manual trades no longer pause playback, even when the transaction fails.
    assert window.playing is True
    assert window._trade_transaction_active is False
    assert trade_controller.commits == 1
    assert window.trades == []
    assert window.events == []
    assert calls.count("trade_buttons") >= 2
    assert any(call.startswith("operation_error:") for call in calls)
    assert "heavy_event_study" not in calls
    assert "heavy_dataset_summary" not in calls
    assert "heavy_performance_summary" not in calls


def test_request_open_trade_ignores_reentrant_trade_transaction():
    calls: list[str] = []
    window = SimpleNamespace(
        df=pd.DataFrame({"close": [1.0]}),
        _trade_transaction_active=True,
        _log=lambda message: calls.append(message),
    )

    MainWindow.request_open_trade(window, "LONG")

    assert calls == ["交易事务正在执行，已忽略重复开仓请求。"]
