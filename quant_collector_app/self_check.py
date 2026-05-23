from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from app_config import EVENT_WINDOW_POST_BARS, EVENT_WINDOW_PRE_BARS
from exporter import Exporter
from storage import StorageManager


SESSION_ID = "sess_selfcheck"
NOW = "2026-01-01T00:00:00+08:00"


def _event(event_id: str, trade_id: str, event_type: str, bar_index: int, price: float):
    return {
        "event_id": event_id,
        "session_id": SESSION_ID,
        "trade_id": trade_id,
        "event_type": event_type,
        "side": "LONG",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "bar_index": bar_index,
        "bar_open_time_bjt": NOW,
        "real_key_time_bjt": NOW,
        "price_proxy": price,
        "label_tags": ["selfcheck"],
        "note": "self check",
        "created_at": NOW,
    }


def _windows():
    return [
        {
            "offset": offset,
            "is_event_bar": 1 if offset == 0 else 0,
            "bar_index": 10 + offset,
            "bar_open_time_bjt": NOW,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
            "is_missing_padding": 0,
        }
        for offset in range(-EVENT_WINDOW_PRE_BARS, EVENT_WINDOW_POST_BARS + 1)
    ]


def _feature(event_id: str, trade_id: str, event_type: str):
    return {
        "event_id": event_id,
        "session_id": SESSION_ID,
        "trade_id": trade_id,
        "event_type": event_type,
        "side": "LONG",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "price_proxy": 100.0,
        "event_body": 1.0,
        "event_range": 2.0,
        "fwd_ret_1": 0.01,
        "manual_trade_final_return_pct": None,
        "manual_trade_holding_bars": None,
        "export_version": "selfcheck",
        "created_at": NOW,
    }


def run_self_check() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="qrc_selfcheck_"))
    try:
        storage = StorageManager(tmp / "selfcheck.db")
        storage.upsert_session(
            {
                "session_id": SESSION_ID,
                "symbol": "BTCUSDT",
                "interval": "1m",
                "start_date_bjt": "2026-01-01",
                "end_date_bjt": "2026-01-01",
                "cursor_bar_index": 12,
                "follow_latest": 0,
                "speed": 1.0,
                "last_opened_at": NOW,
                "last_saved_at": NOW,
                "app_version": "selfcheck",
                "initial_equity": 10_000.0,
                "trade_notional": 1_000.0,
                "fee_bps": 4.0,
                "slippage_bps": 1.0,
                "fill_mode": "MID",
            }
        )
        trade = {
            "trade_id": "trd_selfcheck",
            "session_id": SESSION_ID,
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": "LONG",
            "status": "OPEN",
            "entry_event_id": "evt_open",
            "entry_bar_index": 10,
            "entry_bar_time_bjt": NOW,
            "entry_real_time_bjt": NOW,
            "entry_price_proxy": 100.0,
            "entry_fill_price": 100.01,
            "entry_fee_quote": 0.4,
            "notional_quote": 1_000.0,
            "fill_mode": "MID",
            "fee_bps": 4.0,
            "slippage_bps": 1.0,
            "created_at": NOW,
            "updated_at": NOW,
        }
        storage.insert_open_trade_bundle(trade, _event("evt_open", "trd_selfcheck", "OPEN", 10, 100.0), _windows(), _feature("evt_open", "trd_selfcheck", "OPEN"))
        close_update = {
            "trade_id": "trd_selfcheck",
            "status": "CLOSED",
            "exit_event_id": "evt_close",
            "exit_bar_index": 12,
            "exit_bar_time_bjt": NOW,
            "exit_real_time_bjt": NOW,
            "exit_price_proxy": 103.0,
            "holding_bars": 2,
            "final_return_pct": 3.0,
            "quantity": 9.999,
            "exit_fill_price": 102.99,
            "exit_fee_quote": 0.41,
            "gross_pnl_quote": 29.8,
            "net_pnl_quote": 29.0,
            "gross_return_pct": 2.98,
            "net_return_pct": 2.90,
            "fee_return_pct": 0.08,
            "updated_at": NOW,
        }
        storage.close_trade_bundle(_event("evt_close", "trd_selfcheck", "CLOSE", 12, 103.0), _windows(), _feature("evt_close", "trd_selfcheck", "CLOSE"), close_update, "evt_open", 2.90, 2)
        out_dir = Exporter(storage).export_session(SESSION_ID, tmp / "exports")
        assert (out_dir / "export_manifest.json").exists()
        assert (out_dir / "strategy_consistency.json").exists()
        assert (out_dir / "strategy_consistency_report.md").exists()
        manifest = json.loads((out_dir / "export_manifest.json").read_text(encoding="utf-8"))
        assert manifest["row_counts"]["trades"] == 1
        assert "strategy_consistency" in manifest["files"]
        assert len(_windows()) == 41
        assert manifest["row_counts"]["event_windows_long"] == 82
        return {"status": "ok", "export_dir": str(out_dir)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print(json.dumps(run_self_check(), ensure_ascii=False, indent=2))
