from __future__ import annotations

from pathlib import Path

from app_config import EVENT_WINDOW_POST_BARS, EVENT_WINDOW_PRE_BARS
from storage import StorageManager


SESSION_ID = "sess_test"
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
NOW = "2026-01-01T00:00:00+08:00"


def make_storage(tmp_path: Path) -> StorageManager:
    return StorageManager(tmp_path / "test.db")


def make_trade_row(trade_id="trd_1", event_id="evt_open"):
    return {
        "trade_id": trade_id,
        "session_id": SESSION_ID,
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "side": "LONG",
        "status": "OPEN",
        "entry_event_id": event_id,
        "exit_event_id": None,
        "entry_bar_index": 10,
        "exit_bar_index": None,
        "entry_bar_time_bjt": NOW,
        "exit_bar_time_bjt": None,
        "entry_real_time_bjt": NOW,
        "exit_real_time_bjt": None,
        "entry_price_proxy": 100.0,
        "exit_price_proxy": None,
        "holding_bars": None,
        "final_return_pct": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def make_event_row(event_id="evt_open", trade_id="trd_1", event_type="OPEN", bar_index=10, price=100.0):
    return {
        "event_id": event_id,
        "session_id": SESSION_ID,
        "trade_id": trade_id,
        "event_type": event_type,
        "side": "LONG",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "bar_index": bar_index,
        "bar_open_time_bjt": NOW,
        "real_key_time_bjt": NOW,
        "price_proxy": price,
        "label_tags": ["test"],
        "note": "unit test",
        "created_at": NOW,
    }


def make_window_rows():
    return [
        {
            "offset": offset,
            "is_event_bar": 1 if offset == 0 else 0,
            "bar_index": 10 + offset,
            "bar_open_time_bjt": NOW,
            "open": 100.0 + offset,
            "high": 101.0 + offset,
            "low": 99.0 + offset,
            "close": 100.5 + offset,
            "volume": 10.0,
            "is_missing_padding": 0,
        }
        for offset in range(-EVENT_WINDOW_PRE_BARS, EVENT_WINDOW_POST_BARS + 1)
    ]


def make_feature_row(event_id="evt_open", trade_id="trd_1", event_type="OPEN", price=100.0):
    return {
        "event_id": event_id,
        "session_id": SESSION_ID,
        "trade_id": trade_id,
        "event_type": event_type,
        "side": "LONG",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "price_proxy": price,
        "event_body": 1.0,
        "event_upper_wick": 0.5,
        "event_lower_wick": 0.5,
        "event_range": 2.0,
        "event_volume": 10.0,
        "manual_trade_final_return_pct": None,
        "manual_trade_holding_bars": None,
        "export_version": "test",
        "created_at": NOW,
    }


def insert_open_bundle(storage: StorageManager):
    trade_row = make_trade_row()
    event_row = make_event_row()
    window_rows = make_window_rows()
    feature_row = make_feature_row()
    storage.insert_open_trade_bundle(trade_row, event_row, window_rows, feature_row)
    return trade_row, event_row, window_rows, feature_row


def test_insert_open_trade_bundle_writes_related_records(tmp_path):
    storage = make_storage(tmp_path)
    insert_open_bundle(storage)

    assert len(storage.fetch_table("trades", "session_id=?", (SESSION_ID,))) == 1
    assert len(storage.fetch_table("trade_events", "session_id=?", (SESSION_ID,))) == 1
    assert len(storage.fetch_table("event_windows", "session_id=?", (SESSION_ID,))) == 41
    assert len(storage.fetch_table("event_features", "session_id=?", (SESSION_ID,))) == 1


def test_undo_open_trade_bundle_deletes_related_records(tmp_path):
    storage = make_storage(tmp_path)
    insert_open_bundle(storage)

    storage.undo_open_trade_bundle("trd_1", "evt_open")

    assert storage.fetch_table("trades", "session_id=?", (SESSION_ID,)) == []
    assert storage.fetch_table("trade_events", "session_id=?", (SESSION_ID,)) == []
    assert storage.fetch_table("event_windows", "session_id=?", (SESSION_ID,)) == []
    assert storage.fetch_table("event_features", "session_id=?", (SESSION_ID,)) == []


def test_close_trade_bundle_sets_trade_closed(tmp_path):
    storage = make_storage(tmp_path)
    insert_open_bundle(storage)

    close_event = make_event_row("evt_close", event_type="CLOSE", bar_index=12, price=103.0)
    close_feature = make_feature_row("evt_close", event_type="CLOSE", price=103.0)
    close_update = {
        "trade_id": "trd_1",
        "status": "CLOSED",
        "exit_event_id": "evt_close",
        "exit_bar_index": 12,
        "exit_bar_time_bjt": NOW,
        "exit_real_time_bjt": NOW,
        "exit_price_proxy": 103.0,
        "holding_bars": 2,
        "final_return_pct": 3.0,
        "updated_at": NOW,
    }

    storage.close_trade_bundle(
        close_event,
        make_window_rows(),
        close_feature,
        close_update,
        "evt_open",
        3.0,
        2,
    )

    trade = storage.fetch_trade("trd_1")
    assert trade["status"] == "CLOSED"
    assert trade["exit_event_id"] == "evt_close"
    assert trade["final_return_pct"] == 3.0
    assert len(storage.fetch_table("trade_events", "session_id=?", (SESSION_ID,))) == 2


def test_undo_close_trade_bundle_restores_open(tmp_path):
    storage = make_storage(tmp_path)
    insert_open_bundle(storage)
    close_event = make_event_row("evt_close", event_type="CLOSE", bar_index=12, price=103.0)
    close_feature = make_feature_row("evt_close", event_type="CLOSE", price=103.0)
    close_update = {
        "trade_id": "trd_1",
        "status": "CLOSED",
        "exit_event_id": "evt_close",
        "exit_bar_index": 12,
        "exit_bar_time_bjt": NOW,
        "exit_real_time_bjt": NOW,
        "exit_price_proxy": 103.0,
        "holding_bars": 2,
        "final_return_pct": 3.0,
        "updated_at": NOW,
    }
    storage.close_trade_bundle(close_event, make_window_rows(), close_feature, close_update, "evt_open", 3.0, 2)

    storage.undo_close_trade_bundle("trd_1", "evt_close", "evt_open", NOW)

    trade = storage.fetch_trade("trd_1")
    assert trade["status"] == "OPEN"
    assert trade["exit_event_id"] is None
    assert trade["final_return_pct"] is None
    assert storage.fetch_table("trade_events", "event_id=?", ("evt_close",)) == []
    assert storage.fetch_table("event_windows", "event_id=?", ("evt_close",)) == []
    assert storage.fetch_table("event_features", "event_id=?", ("evt_close",)) == []
