from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from export_controller import ExportController
from premium_controller import PremiumController
from replay_controller import ReplayController
from storage import StorageManager
from trade_controller import TradeController


NOW = "2026-01-01T00:20:00+08:00"


class RecordingTradeStorage:
    def __init__(self):
        self.calls = []

    def insert_open_trade_bundle(self, trade_row, event_row, window_rows, feature_row):
        self.calls.append(("commit_open", trade_row, event_row, list(window_rows), feature_row))

    def undo_open_trade_bundle(self, trade_id, event_id):
        self.calls.append(("undo_open", trade_id, event_id))

    def close_trade_bundle(self, event_row, window_rows, feature_row, close_update, entry_event_id, final_return_pct, holding_bars):
        self.calls.append(
            ("commit_close", event_row, list(window_rows), feature_row, close_update, entry_event_id, final_return_pct, holding_bars)
        )

    def undo_close_trade_bundle(self, trade_id, event_id, entry_event_id, updated_at):
        self.calls.append(("undo_close", trade_id, event_id, entry_event_id, updated_at))


def _bars():
    rows = []
    for index in range(45):
        base = 100.0 + index
        rows.append(
            {
                "bar_index": index,
                "open_time_bjt": pd.Timestamp("2026-01-01 00:00:00", tz="Asia/Shanghai") + pd.Timedelta(minutes=index),
                "open": base,
                "high": base + 1.0,
                "low": base - 1.0,
                "close": base + 0.5,
                "volume": 100.0 + index,
            }
        )
    return pd.DataFrame(rows)


def _controller():
    storage = RecordingTradeStorage()
    return TradeController(storage, export_version="test"), storage


def _open_transaction(controller, side):
    df = _bars()
    return controller.prepare_open(
        df,
        df.iloc[20],
        event_idx=20,
        session_id="sess_1",
        symbol="BTCUSDT",
        interval="1m",
        side=side,
        event_id=f"evt_open_{side.lower()}",
        trade_id=f"trd_{side.lower()}",
        label_tags=["test"],
        note="open",
        settings=controller.execution_settings("close", 4, 1, 1000),
        now_iso=NOW,
    )


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_trade_controller_prepares_and_commits_open_sides(side):
    controller, storage = _controller()

    transaction = _open_transaction(controller, side)
    controller.commit_open(transaction)

    assert transaction.trade_row["side"] == side
    assert transaction.event_row["event_type"] == "OPEN"
    assert transaction.feature_row["side"] == side
    assert storage.calls[0][0] == "commit_open"


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_trade_controller_prepares_and_commits_close_sides(side):
    controller, storage = _controller()
    df = _bars()
    open_transaction = _open_transaction(controller, side)

    transaction = controller.prepare_close(
        df,
        df.iloc[22],
        event_idx=22,
        trade=open_transaction.trade_row,
        event_id=f"evt_close_{side.lower()}",
        label_tags=["exit"],
        note="close",
        fallback_settings=controller.execution_settings("close", 4, 1, 1000),
        now_iso=NOW,
    )
    controller.commit_close(transaction)

    assert transaction.event_row["side"] == side
    assert transaction.event_row["event_type"] == "CLOSE"
    assert transaction.close_update["status"] == "CLOSED"
    assert transaction.feature_row["manual_trade_final_return_pct"] == transaction.outcome["net_return_pct"]
    assert storage.calls[0][0] == "commit_close"


def test_trade_controller_open_undo_and_redo_call_storage_transaction():
    controller, storage = _controller()
    transaction = _open_transaction(controller, "LONG")

    controller.commit_open(transaction)
    controller.undo_open(transaction)
    controller.commit_open(transaction)

    assert [call[0] for call in storage.calls] == ["commit_open", "undo_open", "commit_open"]


def test_trade_controller_close_undo_and_redo_call_storage_transaction():
    controller, storage = _controller()
    df = _bars()
    open_transaction = _open_transaction(controller, "SHORT")
    transaction = controller.prepare_close(
        df,
        df.iloc[22],
        event_idx=22,
        trade=open_transaction.trade_row,
        event_id="evt_close_short",
        label_tags=[],
        note="close",
        fallback_settings=controller.execution_settings("close", 4, 1, 1000),
        now_iso=NOW,
    )

    controller.commit_close(transaction)
    controller.undo_close(transaction, "2026-01-01T00:21:00+08:00")
    controller.commit_close(transaction)

    assert [call[0] for call in storage.calls] == ["commit_close", "undo_close", "commit_close"]


def test_trade_controller_round_trips_transactions_with_sqlite_storage(tmp_path):
    storage = StorageManager(tmp_path / "controller.db")
    controller = TradeController(storage, export_version="test")
    df = _bars()
    open_transaction = _open_transaction(controller, "LONG")

    controller.commit_open(open_transaction)
    assert storage.fetch_trade("trd_long")["status"] == "OPEN"

    close_transaction = controller.prepare_close(
        df,
        df.iloc[22],
        event_idx=22,
        trade=open_transaction.trade_row,
        event_id="evt_close_long",
        label_tags=[],
        note="close",
        fallback_settings=controller.execution_settings("close", 4, 1, 1000),
        now_iso=NOW,
    )
    controller.commit_close(close_transaction)
    assert storage.fetch_trade("trd_long")["status"] == "CLOSED"

    controller.undo_close(close_transaction, "2026-01-01T00:21:00+08:00")
    assert storage.fetch_trade("trd_long")["status"] == "OPEN"
    controller.commit_close(close_transaction)
    assert storage.fetch_trade("trd_long")["status"] == "CLOSED"

    controller.undo_close(close_transaction, "2026-01-01T00:22:00+08:00")
    controller.undo_open(open_transaction)
    assert storage.fetch_trade("trd_long") is None
    controller.commit_open(open_transaction)
    assert storage.fetch_trade("trd_long")["status"] == "OPEN"


def test_replay_controller_moves_and_stops_at_end():
    replay = ReplayController(playing=True)
    changed = replay.tick(3.0, length=3, speed=1.0)
    assert changed is True
    assert replay.cursor == 2
    assert replay.playing is False
    assert replay.step(3) == 2


def test_premium_controller_prevents_duplicate_inflight_and_saves_result():
    class Storage:
        saved = None

        def insert_premium_sample(self, row):
            self.saved = row

    storage = Storage()
    controller = PremiumController()
    assert controller.begin_sample() is True
    assert controller.begin_sample() is False
    controller.complete_sample({"sample_status": "ERROR", "error_message": "offline"}, storage)
    assert controller.inflight is False
    assert controller.last_error == "offline"
    assert storage.saved["sample_status"] == "ERROR"


def test_export_and_trade_controllers_are_pure_boundaries(tmp_path):
    class Exporter:
        def export_session(self, session_id, target):
            assert session_id == "s1"
            return Path(target) / "session_s1"

    result = ExportController(Exporter()).export_session("s1", tmp_path)
    settings = TradeController.execution_settings("close", 4, 1, 1000)
    assert result.ok is True
    assert result.output_dir.name == "session_s1"
    assert settings.fill_mode == "CLOSE"
