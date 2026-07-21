from __future__ import annotations

from types import SimpleNamespace

import pytest
import pandas as pd


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow, QtCore, QtWidgets
from task_lifecycle import BackgroundTaskLifecycle
from controllers.market_data_controller import on_loaded, restore_session_snapshot


class _ValueControl:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class _TextControl:
    def __init__(self, value):
        self._value = value

    def currentText(self):
        return self._value

    def setCurrentText(self, value):
        self._value = value


class _DateControl:
    def __init__(self, value):
        self._value = QtCore.QDate.fromString(value, "yyyy-MM-dd")

    def date(self):
        return self._value

    def setDate(self, value):
        self._value = value


class _SessionChoice:
    def __init__(self, session_id):
        self.session_id = session_id

    def currentData(self):
        return self.session_id


class _SessionCatalogChoice:
    def __init__(self):
        self.items = []
        self.index = -1

    def currentData(self):
        return self.items[self.index][1] if self.index >= 0 else None

    def blockSignals(self, _blocked):
        return False

    def clear(self):
        self.items.clear()
        self.index = -1

    def addItem(self, label, session_id):
        self.items.append((label, session_id))
        if self.index < 0:
            self.index = 0

    def setCurrentIndex(self, index):
        self.index = index


def _resume_window():
    calls = []
    target = {
        "session_id": "sess_history",
        "symbol": "ETHUSDT",
        "interval": "5m",
        "start_date_bjt": "2026-01-01",
        "end_date_bjt": "2026-01-07",
        "cursor_bar_index": 37,
        "follow_latest": 0,
        "speed": 2.0,
        "initial_equity": 12_000.0,
        "trade_notional": 2_000.0,
        "fee_bps": 3.0,
        "slippage_bps": 1.5,
        "fill_mode": "NEXT_OPEN",
        "take_profit_pct": 2.0,
        "stop_loss_pct": 1.0,
    }
    window = SimpleNamespace(
        replayPerformanceSessionBox=_SessionChoice("sess_history"),
        storage=SimpleNamespace(get_session=lambda session_id: target if session_id == "sess_history" else None),
        task_lifecycle=BackgroundTaskLifecycle(),
        _loading_data=False,
        _trade_transaction_active=False,
        app_state=SimpleNamespace(export=SimpleNamespace(running=False)),
        analysis_refresh_controller=SimpleNamespace(is_running=False),
        session_id="sess_current",
        restoring_session_id=None,
        restore_snapshot_pending=False,
        _restoring_session_settings=False,
        symbolBox=_TextControl("BTCUSDT"),
        intervalBox=_TextControl("1m"),
        startDate=_DateControl("2026-02-01"),
        endDate=_DateControl("2026-02-02"),
        follow_latest=True,
        speedSlider=_ValueControl(3),
        initialEquitySpin=_ValueControl(10_000.0),
        tradeNotionalSpin=_ValueControl(1_000.0),
        feeBpsSpin=_ValueControl(2.0),
        slippageBpsSpin=_ValueControl(1.0),
        takeProfitPctSpin=_ValueControl(0.0),
        stopLossPctSpin=_ValueControl(0.0),
        trades=[{"trade_id": "current"}],
        events=[{"event_id": "current"}],
        _trade_by_id={"current": {}},
        _event_by_id={"current": {}},
        undo_stack=["undo"],
        redo_stack=["redo"],
        df=object(),
        cursor=11,
        playing=True,
        _display_market_key=("BTCUSDT", "1m", "2026-02-01", "2026-02-02"),
        _sample_market_key=("BTCUSDT", "1m", "2026-02-01", "2026-02-02"),
        _set_symbol_value=lambda value: setattr(window.symbolBox, "_value", value),
        _set_fill_mode_value=lambda value: calls.append(("fill", value)),
        _fill_mode_value=lambda: "CLOSE",
        take_profit_pct_value=lambda: None,
        stop_loss_pct_value=lambda: None,
        persist_session_state=lambda: calls.append(("persist", window.session_id)),
        load_data=lambda **kwargs: calls.append(("load", kwargs)) or True,
        _operation_error=lambda title, exc: calls.append(("error", title, str(exc))),
        tr=lambda key: key,
    )
    return window, calls


def test_execution_setting_signals_do_not_save_during_session_restore():
    calls = []
    window = SimpleNamespace(
        _restoring_session_settings=True,
        persist_session_state=lambda: calls.append("persist"),
        _sync_equity_curve=lambda: calls.append("equity"),
        _refresh_tables=lambda: calls.append("tables"),
        _log=lambda message: calls.append(message),
    )

    MainWindow.on_execution_settings_changed(window)

    assert calls == []


def test_continue_performance_session_restores_target_and_keeps_same_session_id(monkeypatch):
    window, calls = _resume_window()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )

    resumed = MainWindow.continue_performance_session(window)

    assert resumed is True
    assert calls[:2] == [("persist", "sess_current"), ("fill", "NEXT_OPEN")]
    assert calls[-1] == ("load", {"restore": True, "reset_session": False})
    assert window.session_id == "sess_history"
    assert window.restoring_session_id == "sess_history"
    assert window.restore_snapshot_pending is True
    assert window.symbolBox.currentText() == "ETHUSDT"
    assert window.intervalBox.currentText() == "5m"
    assert window.startDate.date().toString("yyyy-MM-dd") == "2026-01-01"
    assert window.endDate.date().toString("yyyy-MM-dd") == "2026-01-07"


def test_replay_continue_selector_uses_shared_performance_session_catalog():
    combo = _SessionCatalogChoice()
    storage = SimpleNamespace(
        list_performance_sessions=lambda: [
            {
                "session_id": "sess_history",
                "symbol": "ETHUSDT",
                "interval": "5m",
                "start_date_bjt": "2026-01-01",
                "end_date_bjt": "2026-01-07",
                "last_saved_at": "2026-01-08T00:00:00+08:00",
            }
        ]
    )
    window = SimpleNamespace(
        replayPerformanceSessionBox=combo,
        storage=storage,
    )

    MainWindow.refresh_replay_performance_sessions(window)

    assert len(combo.items) == 1
    label, session_id = combo.items[0]
    assert session_id == "sess_history"
    assert all(value in label for value in ("ETHUSDT", "5m", "2026-01-01", "2026-01-07"))


def test_continue_performance_session_cancel_keeps_current_session_untouched(monkeypatch):
    window, calls = _resume_window()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Cancel,
    )

    resumed = MainWindow.continue_performance_session(window)

    assert resumed is False
    assert window.session_id == "sess_current"
    assert window.symbolBox.currentText() == "BTCUSDT"
    assert calls == []


def test_continue_already_current_performance_session_is_a_safe_noop(monkeypatch):
    window, calls = _resume_window()
    window.session_id = "sess_history"
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("current session must not require a destructive switch")
        ),
    )

    resumed = MainWindow.continue_performance_session(window)

    assert resumed is True
    assert window.session_id == "sess_history"
    assert calls == []


@pytest.mark.parametrize(
    "busy_state",
    ("loading", "export", "analysis", "daily_backup", "shutdown"),
)
def test_continue_performance_session_rejects_busy_or_shutdown(monkeypatch, busy_state):
    window, calls = _resume_window()
    if busy_state == "loading":
        window._loading_data = True
    elif busy_state == "export":
        window.app_state.export.running = True
    elif busy_state == "analysis":
        window.analysis_refresh_controller.is_running = True
    elif busy_state == "daily_backup":
        window.task_lifecycle.start("daily_backup")
    else:
        window.task_lifecycle.begin_shutdown()
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: None)

    resumed = MainWindow.continue_performance_session(window)

    assert resumed is False
    assert window.session_id == "sess_current"
    assert calls == []


def test_continue_performance_session_load_rejection_rolls_back_current_state(monkeypatch):
    window, calls = _resume_window()
    original_df = window.df
    window.load_data = lambda **kwargs: calls.append(("load", kwargs)) or False
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )

    resumed = MainWindow.continue_performance_session(window)

    assert resumed is False
    assert window.session_id == "sess_current"
    assert window.restoring_session_id is None
    assert window.restore_snapshot_pending is False
    assert window.symbolBox.currentText() == "BTCUSDT"
    assert window.intervalBox.currentText() == "1m"
    assert window.df is original_df
    assert window.cursor == 11
    assert window.playing is True


def test_failed_async_resume_load_restores_previous_session_before_frame_mutation(monkeypatch):
    window, _calls = _resume_window()
    original_df = window.df
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    assert MainWindow.continue_performance_session(window) is True
    window._loading_data = True
    window.app_state.data_load = SimpleNamespace(loading=True)
    window._log = lambda _message: None
    window.status = SimpleNamespace(setText=lambda _message: None)
    window.task_lifecycle.start("market_data_load")

    on_loaded(window, pd.DataFrame(), "加载失败：network error")

    assert window.session_id == "sess_current"
    assert window.df is original_df
    assert window.cursor == 11
    assert window.playing is True
    assert window.task_lifecycle.active_tasks == ()


def test_failed_session_snapshot_read_rolls_back_previous_session(monkeypatch):
    window, _calls = _resume_window()
    original_df = window.df
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    assert MainWindow.continue_performance_session(window) is True
    window.storage.load_session_snapshot = lambda _session_id: (_ for _ in ()).throw(
        RuntimeError("snapshot unavailable")
    )

    restored = restore_session_snapshot(window)

    assert restored is False
    assert window.session_id == "sess_current"
    assert window.df is original_df
    assert window.cursor == 11
    assert window.playing is True
