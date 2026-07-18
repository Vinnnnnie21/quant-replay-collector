from __future__ import annotations

from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pandas")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow, QtCore, QtGui, QtWidgets


class _Storage:
    def __init__(self, *, allow_clear: bool = False):
        self.preview_calls = 0
        self.clear_calls = 0
        self.allow_clear = allow_clear

    def preview_all_trade_sample_deletion(self):
        self.preview_calls += 1
        return {
            "trades": 1,
            "trade_events": 2,
            "event_windows": 82,
            "event_features": 2,
            "account_equity": 1,
            "session_ids": ["sess_current"],
        }

    def clear_manual_research_records(self):
        self.clear_calls += 1
        if not self.allow_clear:
            raise AssertionError("clear must not run")
        return self.preview_all_trade_sample_deletion()


class _RangeStorage:
    def __init__(self, *, allow_delete: bool = False):
        self.preview_calls = 0
        self.delete_calls = 0
        self.allow_delete = allow_delete

    def list_trade_samples_for_management(self, **_kwargs):
        return [
            {
                "trade_id": "trd_history",
                "session_id": "sess_history",
                "side": "LONG",
                "status": "CLOSED",
                "entry_time": "2026-01-01T00:01:00+08:00",
                "exit_time": "2026-01-01T00:02:00+08:00",
                "net_pnl_quote": 10.0,
            }
        ]

    def preview_trade_sample_deletion(self, trade_ids):
        self.preview_calls += 1
        assert trade_ids == ["trd_history"]
        return {
            "trades": 1,
            "trade_events": 2,
            "event_windows": 82,
            "event_features": 2,
            "trade_ids": ["trd_history"],
            "event_ids": ["evt_open", "evt_close"],
            "session_ids": ["sess_history"],
        }

    def delete_trade_samples(self, trade_ids):
        self.delete_calls += 1
        if not self.allow_delete:
            raise AssertionError("delete must not run")
        assert trade_ids == ["trd_history"]
        return {
            "trades": 1,
            "trade_events": 2,
            "event_windows": 82,
            "event_features": 2,
            "trade_ids": ["trd_history"],
            "event_ids": ["evt_open", "evt_close"],
            "session_ids": ["sess_history"],
        }


class _DateTimeEdit:
    def __init__(self, value: str):
        self._value = value

    def dateTime(self):
        return self

    def toString(self, _format):
        return self._value


class _CandidateBox:
    def __init__(self, trade_id: str = "trd_history"):
        self._trade_id = trade_id

    def currentData(self):
        return self._trade_id


class _PreviewCandidateBox:
    def __init__(self):
        self.items = []

    def clear(self):
        self.items.clear()

    def addItem(self, label, trade_id):
        self.items.append({"label": label, "trade_id": trade_id, "data": {}})

    def count(self):
        return len(self.items)

    def setItemData(self, index, value, role):
        self.items[index]["data"][role] = value


class _PreviewLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class _SessionBox:
    def __init__(self):
        self.items = []
        self.index = -1

    def blockSignals(self, _blocked):
        return False

    def clear(self):
        self.items.clear()
        self.index = -1

    def addItem(self, label, session_id):
        self.items.append((label, session_id))
        if self.index < 0:
            self.index = 0

    def currentData(self):
        if self.index < 0:
            return None
        return self.items[self.index][1]


class _SessionTradeTable:
    def __init__(self):
        self.rows = []

    def setRowCount(self, count):
        self.rows = [[None] * 11 for _ in range(count)]

    def setItem(self, row, column, item):
        self.rows[row][column] = item

    def item(self, row, column):
        return self.rows[row][column]

    def currentRow(self):
        return 0 if self.rows else -1


class _SessionStorage(_RangeStorage):
    def __init__(self, *, allow_delete: bool = False):
        super().__init__(allow_delete=allow_delete)
        self.session_deleted = False

    def list_performance_sessions(self):
        if self.session_deleted:
            return []
        return [
            {
                "session_id": "sess_history",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "start_date_bjt": "2026-01-01",
                "end_date_bjt": "2026-01-02",
                "last_opened_at": "2026-01-02T00:00:00+08:00",
                "last_saved_at": "2026-01-02T00:00:00+08:00",
            }
        ]

    def list_trade_samples_for_session(self, session_id, *, limit=500):
        assert session_id == "sess_history"
        assert limit == 500
        return [
            {
                "trade_id": "trd_history",
                "session_id": session_id,
                "symbol": "BTCUSDT",
                "interval": "1m",
                "side": "LONG",
                "status": "CLOSED",
                "entry_time": "2026-01-01T00:01:00+08:00",
                "exit_time": "2026-01-01T00:02:00+08:00",
                "entry_price": 100.0,
                "exit_price": 102.0,
                "quantity": 10.0,
                "return_pct": 2.0,
                "pnl": 20.0,
            }
        ]

    def preview_performance_session_deletion(self, session_id):
        assert session_id == "sess_history"
        self.preview_calls += 1
        return {
            "sessions": 1,
            "trades": 1,
            "trade_events": 2,
            "event_windows": 82,
            "event_features": 2,
            "account_equity": 1,
            "research_records": 0,
            "trade_ids": ["trd_history"],
            "event_ids": ["evt_open", "evt_close"],
            "session_ids": [session_id],
        }

    def delete_performance_session(self, session_id):
        assert session_id == "sess_history"
        self.delete_calls += 1
        if not self.allow_delete:
            raise AssertionError("delete must not run")
        deleted = self.preview_performance_session_deletion(session_id)
        self.session_deleted = True
        return deleted


class _EmptyPerformanceSessionStorage(_SessionStorage):
    def preview_performance_session_deletion(self, session_id):
        assert session_id == "sess_history"
        self.preview_calls += 1
        return {
            "sessions": 1,
            "trades": 0,
            "trade_events": 0,
            "event_windows": 0,
            "event_features": 0,
            "account_equity": 0,
            "research_records": 0,
            "trade_ids": [],
            "event_ids": [],
            "session_ids": [session_id],
        }

def _range_window_stub(*, allow_delete: bool = False):
    return SimpleNamespace(
        _loading_data=False,
        _trade_transaction_active=False,
        app_state=SimpleNamespace(export=SimpleNamespace(running=False)),
        storage=_RangeStorage(allow_delete=allow_delete),
        tradeManagementStart=_DateTimeEdit("2026-01-01T00:00:00+08:00"),
        tradeManagementEnd=_DateTimeEdit("2026-01-01T00:10:00+08:00"),
        tradeManagementCandidateBox=_CandidateBox(),
        session_id="sess_current",
        df=object(),
        cursor=37,
        symbolBox=SimpleNamespace(currentText=lambda: "ETHUSDT"),
        intervalBox=SimpleNamespace(currentText=lambda: "5m"),
        startDate=object(),
        endDate=object(),
        playing=True,
        _analysis_workspace=None,
        theme_settings={"green": "#168a5b", "red": "#d64545"},
        _log=lambda _message: None,
        tr=lambda key: {
            "clear_trade_records_phrase": "清空交易数据",
            "delete_trade_range_phrase": "删除时间段交易数据",
            "delete_selected_trade_phrase": "删除这笔交易样本",
            "delete_session_trade_phrase": "DELETE TRADE",
            "delete_performance_session_phrase": "DELETE SESSION",
            "trade_data_management_preview_message": (
                "scope={scope}; trades={trades}; events={events}; "
                "windows={windows}; features={features}; sessions={sessions}"
            ),
        }.get(key, key),
    )


def _window_stub():
    return SimpleNamespace(
        _loading_data=False,
        app_state=SimpleNamespace(export=SimpleNamespace(running=False)),
        storage=_Storage(),
        tr=lambda key: {
            "clear_trade_records_title": "清空全部交易样本",
            "clear_trade_records_warning": "warning",
            "clear_trade_records_phrase_prompt": "prompt",
            "clear_trade_records_phrase": "清空交易数据",
            "clear_trade_records_phrase_mismatch": "mismatch",
        }.get(key, key),
    )


def test_clear_trade_records_cancelled_at_warning_does_not_delete(monkeypatch):
    window = _window_stub()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Cancel,
    )

    MainWindow.confirm_clear_trade_records(window)

    assert window.storage.preview_calls == 1
    assert window.storage.clear_calls == 0


def test_clear_trade_records_requires_confirmation_phrase(monkeypatch):
    window = _window_stub()
    responses = iter([QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.Ok])
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: next(responses),
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("wrong", True),
    )

    MainWindow.confirm_clear_trade_records(window)

    assert window.storage.clear_calls == 0


def test_clear_all_trade_samples_two_confirmations_keep_current_session_and_refresh(monkeypatch):
    window = _range_window_stub()
    window.storage = _Storage(allow_clear=True)
    window.session_id = "sess_current"
    window.trades = [{"trade_id": "trd_current"}]
    window.events = [{"event_id": "evt_current"}]
    window._trade_by_id = {"trd_current": window.trades[0]}
    window._event_by_id = {"evt_current": window.events[0]}
    window.undo_stack = [object()]
    window.redo_stack = [object()]
    calls = []
    window.persist_session_state = lambda: calls.append("persist")
    window._chart_render_state = lambda: SimpleNamespace(
        mark_events_changed=lambda: calls.append("events")
    )
    window._sync_markers = lambda: calls.append("markers")
    window._refresh_tables = lambda: calls.append("tables")
    window._render = lambda **_kwargs: calls.append("render")
    window._render_dirty = False
    window._analysis_performance_payload = object()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("清空交易数据", True),
    )

    MainWindow.confirm_clear_trade_records(window)

    assert window.storage.clear_calls == 1
    assert window.session_id == "sess_current"
    assert window.trades == []
    assert window.events == []
    assert window._trade_by_id == {}
    assert window._event_by_id == {}
    assert window.undo_stack == []
    assert window.redo_stack == []
    assert calls == ["persist", "events", "markers", "tables", "render"]


def test_delete_trade_range_cancelled_at_preview_does_not_delete(monkeypatch):
    window = _range_window_stub()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Cancel,
    )

    MainWindow.confirm_delete_trade_range(window)

    assert window.storage.preview_calls == 1
    assert window.storage.delete_calls == 0


def test_delete_trade_range_wrong_phrase_does_not_delete(monkeypatch):
    window = _range_window_stub()
    prompts = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: (prompts.append(args) or "wrong", True),
    )

    MainWindow.confirm_delete_trade_range(window)

    assert len(prompts) == 1
    assert window.storage.delete_calls == 0


def test_delete_trade_range_closed_phrase_dialog_does_not_delete(monkeypatch):
    window = _range_window_stub()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("删除时间段交易数据", False),
    )

    MainWindow.confirm_delete_trade_range(window)

    assert window.storage.delete_calls == 0


def test_preview_trade_data_range_populates_trade_candidates_and_counts():
    window = _range_window_stub()
    window.tradeManagementCandidateBox = _PreviewCandidateBox()
    window.tradeManagementPreviewLabel = _PreviewLabel()

    preview = MainWindow.preview_trade_data_range(window)

    assert preview["trades"] == 1
    assert window.tradeManagementCandidateBox.count() == 1
    assert window.tradeManagementCandidateBox.items[0]["trade_id"] == "trd_history"
    stored_rows = window.tradeManagementCandidateBox.items[0]["data"].values()
    assert any(row["trade_id"] == "trd_history" for row in stored_rows)
    assert "trades=1" in window.tradeManagementPreviewLabel.text


def test_trade_management_session_catalog_lists_only_selected_session_trades():
    window = _range_window_stub()
    window.storage = _SessionStorage()
    window.tradeManagementSessionBox = _SessionBox()
    window.tradeManagementSessionTradeTable = _SessionTradeTable()

    MainWindow.refresh_trade_management_sessions(window)

    assert len(window.tradeManagementSessionBox.items) == 1
    label, session_id = window.tradeManagementSessionBox.items[0]
    assert session_id == "sess_history"
    assert all(value in label for value in ("BTCUSDT", "1m", "2026-01-01", "2026-01-02"))
    assert len(window.tradeManagementSessionTradeTable.rows) == 1
    first = window.tradeManagementSessionTradeTable.rows[0]
    assert first[0].data(QtCore.Qt.UserRole) == "trd_history"
    assert [item.text() for item in first] == [
        "BTCUSDT",
        "多",
        "2",
        "20",
        "trd_history",
        "2026-01-01T00:01:00+08:00",
        "2026-01-01T00:02:00+08:00",
        "100",
        "102",
        "10",
        "已平仓",
    ]
    assert first[2].foreground().color() == QtGui.QColor("#168a5b")
    assert first[3].foreground().color() == QtGui.QColor("#168a5b")


def test_trade_management_session_table_colors_losses_red():
    window = _range_window_stub()
    window.storage = _SessionStorage()
    window.storage.list_trade_samples_for_session = lambda *_args, **_kwargs: [
        {
            "trade_id": "trd_loss",
            "session_id": "sess_history",
            "symbol": "BTCUSDT",
            "side": "SHORT",
            "return_pct": -1.5,
            "pnl": -15.0,
        }
    ]
    window.tradeManagementSessionBox = _SessionBox()
    window.tradeManagementSessionBox.addItem("history", "sess_history")
    window.tradeManagementSessionTradeTable = _SessionTradeTable()

    MainWindow.load_trade_management_session_trades(window)

    row = window.tradeManagementSessionTradeTable.rows[0]
    assert row[2].foreground().color() == QtGui.QColor("#d64545")
    assert row[3].foreground().color() == QtGui.QColor("#d64545")


def test_delete_session_trade_requires_preview_and_exact_phrase_before_delete(monkeypatch):
    window = _range_window_stub(allow_delete=True)
    window.storage = _SessionStorage(allow_delete=True)
    window.tradeManagementSessionBox = _SessionBox()
    window.tradeManagementSessionTradeTable = _SessionTradeTable()
    MainWindow.refresh_trade_management_sessions(window)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("DELETE TRADE", True),
    )

    MainWindow.confirm_delete_session_trade(window)

    assert window.storage.preview_calls == 1
    assert window.storage.delete_calls == 1
    assert window.session_id == "sess_current"


def test_delete_performance_session_requires_two_confirmations(monkeypatch):
    window = _range_window_stub(allow_delete=True)
    window.storage = _SessionStorage(allow_delete=True)
    window.tradeManagementSessionBox = _SessionBox()
    window.tradeManagementSessionTradeTable = _SessionTradeTable()
    MainWindow.refresh_trade_management_sessions(window)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("DELETE SESSION", True),
    )

    MainWindow.confirm_delete_performance_session(window)

    assert window.storage.delete_calls == 1
    assert window.session_id == "sess_current"
    assert window.cursor == 37
    assert window.symbolBox.currentText() == "ETHUSDT"
    assert window.intervalBox.currentText() == "5m"


def test_delete_empty_performance_session_removes_catalog_entry_after_two_confirmations(
    monkeypatch,
):
    window = _range_window_stub(allow_delete=True)
    window.storage = _EmptyPerformanceSessionStorage(allow_delete=True)
    window.tradeManagementSessionBox = _SessionBox()
    window.tradeManagementSessionTradeTable = _SessionTradeTable()
    MainWindow.refresh_trade_management_sessions(window)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("DELETE SESSION", True),
    )

    MainWindow.confirm_delete_performance_session(window)

    assert window.storage.delete_calls == 1
    assert window.tradeManagementSessionBox.items == []
    assert window.session_id == "sess_current"
    assert window.cursor == 37


def test_delete_current_performance_session_detaches_without_recreating_it(monkeypatch):
    window = _range_window_stub(allow_delete=True)
    window.storage = _SessionStorage(allow_delete=True)
    window.tradeManagementSessionBox = _SessionBox()
    window.tradeManagementSessionTradeTable = _SessionTradeTable()
    MainWindow.refresh_trade_management_sessions(window)
    window.session_id = "sess_history"
    window.trades = [{"trade_id": "trd_history"}]
    window.events = [{"event_id": "evt_open"}, {"event_id": "evt_close"}]
    window._trade_by_id = {"trd_history": window.trades[0]}
    window._event_by_id = {row["event_id"]: row for row in window.events}
    window.undo_stack = [object()]
    window.redo_stack = [object()]
    window._analysis_performance_payload = object()
    calls = []
    window.persist_session_state = lambda: calls.append("persist")
    window._chart_render_state = lambda: SimpleNamespace(
        mark_events_changed=lambda: calls.append("events")
    )
    window._sync_markers = lambda: calls.append("markers")
    window._refresh_tables = lambda: calls.append("tables")
    window._render = lambda **_kwargs: calls.append("render")
    window._render_dirty = False
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("DELETE SESSION", True),
    )

    MainWindow.confirm_delete_performance_session(window)

    assert window.session_id is None
    assert window.trades == []
    assert window.events == []
    assert window._trade_by_id == {}
    assert window._event_by_id == {}
    assert window.undo_stack == []
    assert window.redo_stack == []
    assert window._analysis_performance_payload is None
    assert "persist" not in calls
    assert calls == ["events", "markers", "tables", "render"]
    assert window.cursor == 37
    assert window.symbolBox.currentText() == "ETHUSDT"
    assert window.intervalBox.currentText() == "5m"


def test_delete_performance_session_cancelled_at_preview_does_not_delete(monkeypatch):
    window = _range_window_stub()
    window.storage = _SessionStorage()
    window.tradeManagementSessionBox = _SessionBox()
    window.tradeManagementSessionTradeTable = _SessionTradeTable()
    MainWindow.refresh_trade_management_sessions(window)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Cancel,
    )

    MainWindow.confirm_delete_performance_session(window)

    assert window.storage.delete_calls == 0


def test_delete_performance_session_wrong_phrase_does_not_delete(monkeypatch):
    window = _range_window_stub()
    window.storage = _SessionStorage()
    window.tradeManagementSessionBox = _SessionBox()
    window.tradeManagementSessionTradeTable = _SessionTradeTable()
    MainWindow.refresh_trade_management_sessions(window)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("wrong", True),
    )

    MainWindow.confirm_delete_performance_session(window)

    assert window.storage.delete_calls == 0


def test_delete_trade_range_with_no_matches_stops_before_confirmation(monkeypatch):
    window = _range_window_stub()
    window.storage.list_trade_samples_for_management = lambda **_kwargs: []
    window.storage.preview_trade_sample_deletion = lambda _trade_ids: {
        "trades": 0,
        "trade_events": 0,
        "event_windows": 0,
        "event_features": 0,
        "trade_ids": [],
        "event_ids": [],
        "session_ids": [],
    }
    calls = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: calls.append("warning"),
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda *args, **kwargs: calls.append("information"),
    )

    MainWindow.confirm_delete_trade_range(window)

    assert calls == ["information"]
    assert window.storage.delete_calls == 0


def test_delete_trade_range_two_confirmations_delete_history_without_changing_player(monkeypatch):
    window = _range_window_stub(allow_delete=True)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("删除时间段交易数据", True),
    )
    original = (
        window.df,
        window.cursor,
        window.symbolBox.currentText(),
        window.intervalBox.currentText(),
        window.startDate,
        window.endDate,
        window.playing,
        window.session_id,
    )

    MainWindow.confirm_delete_trade_range(window)

    assert window.storage.delete_calls == 1
    assert (
        window.df,
        window.cursor,
        window.symbolBox.currentText(),
        window.intervalBox.currentText(),
        window.startDate,
        window.endDate,
        window.playing,
        window.session_id,
    ) == original


def test_delete_selected_trade_cancelled_at_preview_does_not_delete(monkeypatch):
    window = _range_window_stub()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Cancel,
    )

    MainWindow.confirm_delete_selected_trade(window)

    assert window.storage.preview_calls == 1
    assert window.storage.delete_calls == 0


def test_delete_selected_trade_wrong_phrase_does_not_delete(monkeypatch):
    window = _range_window_stub()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("wrong", True),
    )

    MainWindow.confirm_delete_selected_trade(window)

    assert window.storage.delete_calls == 0


def test_delete_selected_trade_two_confirmations_execute_delete(monkeypatch):
    window = _range_window_stub(allow_delete=True)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("删除这笔交易样本", True),
    )

    MainWindow.confirm_delete_selected_trade(window)

    assert window.storage.delete_calls == 1


def test_delete_current_session_trade_refreshes_memory_markers_tables_and_analysis(monkeypatch):
    window = _range_window_stub(allow_delete=True)
    window.session_id = "sess_history"
    window.trades = [
        {"trade_id": "trd_history"},
        {"trade_id": "trd_keep"},
    ]
    window.events = [
        {"event_id": "evt_open"},
        {"event_id": "evt_close"},
        {"event_id": "evt_keep"},
    ]
    window._trade_by_id = {row["trade_id"]: row for row in window.trades}
    window._event_by_id = {row["event_id"]: row for row in window.events}
    window.undo_stack = [object()]
    window.redo_stack = [object()]
    calls = []
    window.persist_session_state = lambda: calls.append("persist")
    window._chart_render_state = lambda: SimpleNamespace(
        mark_events_changed=lambda: calls.append("events")
    )
    window._sync_markers = lambda: calls.append("markers")
    window._refresh_tables = lambda: calls.append("tables")
    window._render = lambda **_kwargs: calls.append("render")
    window._render_dirty = False
    window._analysis_performance_payload = object()
    window._analysis_workspace = SimpleNamespace(
        invalidate_performance_sessions=lambda session_ids: calls.append(
            ("analysis", tuple(session_ids))
        )
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("删除这笔交易样本", True),
    )

    MainWindow.confirm_delete_selected_trade(window)

    assert window.trades == [{"trade_id": "trd_keep"}]
    assert window.events == [{"event_id": "evt_keep"}]
    assert set(window._trade_by_id) == {"trd_keep"}
    assert set(window._event_by_id) == {"evt_keep"}
    assert window.undo_stack == []
    assert window.redo_stack == []
    assert window._analysis_performance_payload is None
    assert calls == [
        "persist",
        "events",
        "markers",
        "tables",
        "render",
        ("analysis", ("sess_history",)),
    ]


@pytest.mark.parametrize(
    "busy_state",
    ["loading", "export", "analysis", "daily_backup", "stop_requested", "shutdown"],
)
def test_trade_data_management_rejects_busy_lifecycle_before_preview(monkeypatch, busy_state):
    window = _range_window_stub()
    if busy_state == "loading":
        window._loading_data = True
    elif busy_state == "export":
        window.app_state.export.running = True
    elif busy_state == "analysis":
        window.task_lifecycle = SimpleNamespace(
            active_tasks=("analysis_refresh",),
            shutdown_in_progress=False,
        )
    elif busy_state == "daily_backup":
        window.task_lifecycle = SimpleNamespace(
            active_tasks=("daily_backup",),
            shutdown_in_progress=False,
        )
    elif busy_state == "stop_requested":
        window.task_lifecycle = SimpleNamespace(
            active_tasks=("historical_performance",),
            shutdown_in_progress=False,
        )
    else:
        window.task_lifecycle = SimpleNamespace(
            active_tasks=(),
            shutdown_in_progress=True,
        )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Cancel,
    )

    MainWindow.confirm_delete_trade_range(window)

    assert window.storage.preview_calls == 0
    assert window.storage.delete_calls == 0
