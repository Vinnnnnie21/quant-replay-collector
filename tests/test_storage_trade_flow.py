from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app_config import EVENT_WINDOW_POST_BARS, EVENT_WINDOW_PRE_BARS
from services.session_service import list_performance_session_options
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
    event_time = datetime.fromisoformat(NOW)
    return [
        {
            "offset": offset,
            "is_event_bar": 1 if offset == 0 else 0,
            "bar_index": 10 + offset,
            "bar_open_time_bjt": (event_time + timedelta(minutes=offset)).isoformat(),
            "open": 100.0 + offset,
            "high": 101.0 + offset,
            "low": 99.0 + offset,
            "close": 100.5 + offset,
            "volume": 10.0,
            "is_missing_padding": 0,
        }
        for offset in range(-EVENT_WINDOW_PRE_BARS, EVENT_WINDOW_POST_BARS + 1)
    ]


def make_ordered_window_row(event_number: int, offset: int):
    minute = event_number * 10 + offset
    return {
        "offset": offset,
        "is_event_bar": int(offset == 0),
        "bar_index": event_number * 100 + offset,
        "bar_open_time_bjt": f"2026-01-01T00:{minute:02d}:00+08:00",
        "open": 100.0 + offset,
        "high": 101.0 + offset,
        "low": 99.0 + offset,
        "close": 100.5 + offset,
        "volume": 10.0,
        "is_missing_padding": 0,
    }


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


def insert_managed_trade(
    storage: StorageManager,
    *,
    trade_id: str,
    entry_time: str,
    exit_time: str | None = None,
    session_id: str = SESSION_ID,
) -> None:
    entry_event_id = f"{trade_id}_open"
    exit_event_id = f"{trade_id}_close" if exit_time is not None else None
    trade = make_trade_row(trade_id, entry_event_id)
    trade.update(
        {
            "session_id": session_id,
            "status": "CLOSED" if exit_time is not None else "OPEN",
            "exit_event_id": exit_event_id,
            "entry_bar_time_bjt": entry_time,
            "exit_bar_time_bjt": exit_time,
            "net_pnl_quote": 10.0 if exit_time is not None else None,
        }
    )
    storage.insert_trade(trade)
    entry_event = make_event_row(entry_event_id, trade_id, "OPEN")
    entry_event.update(
        {
            "session_id": session_id,
            "bar_open_time_bjt": entry_time,
        }
    )
    storage.insert_event(entry_event)
    if exit_time is not None:
        exit_event = make_event_row(exit_event_id, trade_id, "CLOSE")
        exit_event.update(
            {
                "session_id": session_id,
                "bar_open_time_bjt": exit_time,
            }
        )
        storage.insert_event(exit_event)


def insert_closed_managed_bundle(
    storage: StorageManager,
    *,
    trade_id: str,
    entry_time: str,
    exit_time: str,
    net_pnl_quote: float,
    session_id: str = SESSION_ID,
) -> None:
    entry_event_id = f"{trade_id}_open"
    exit_event_id = f"{trade_id}_close"
    trade = make_trade_row(trade_id, entry_event_id)
    trade.update(
        {
            "session_id": session_id,
            "entry_bar_time_bjt": entry_time,
            "notional_quote": 1_000.0,
        }
    )
    entry_event = make_event_row(entry_event_id, trade_id, "OPEN")
    entry_event.update({"session_id": session_id, "bar_open_time_bjt": entry_time})
    entry_feature = make_feature_row(entry_event_id, trade_id, "OPEN")
    entry_feature["session_id"] = session_id
    storage.insert_open_trade_bundle(
        trade,
        entry_event,
        make_window_rows(),
        entry_feature,
    )
    exit_event = make_event_row(exit_event_id, trade_id, "CLOSE", bar_index=12)
    exit_event.update({"session_id": session_id, "bar_open_time_bjt": exit_time})
    exit_feature = make_feature_row(exit_event_id, trade_id, "CLOSE")
    exit_feature["session_id"] = session_id
    storage.close_trade_bundle(
        exit_event,
        make_window_rows(),
        exit_feature,
        {
            "trade_id": trade_id,
            "status": "CLOSED",
            "exit_event_id": exit_event_id,
            "exit_bar_index": 12,
            "exit_bar_time_bjt": exit_time,
            "exit_real_time_bjt": exit_time,
            "exit_price_proxy": 102.0,
            "holding_bars": 2,
            "final_return_pct": net_pnl_quote / 10.0,
            "gross_pnl_quote": net_pnl_quote,
            "net_pnl_quote": net_pnl_quote,
            "updated_at": exit_time,
        },
        entry_event_id,
        net_pnl_quote / 10.0,
        2,
    )


def test_insert_open_trade_bundle_writes_related_records(tmp_path):
    storage = make_storage(tmp_path)
    insert_open_bundle(storage)

    assert len(storage.fetch_table("trades", "session_id=?", (SESSION_ID,))) == 1
    assert len(storage.fetch_table("trade_events", "session_id=?", (SESSION_ID,))) == 1
    assert len(storage.fetch_table("event_windows", "session_id=?", (SESSION_ID,))) == 41
    assert len(storage.fetch_table("event_features", "session_id=?", (SESSION_ID,))) == 1


def test_performance_session_catalog_reads_only_stable_session_identity_in_saved_order(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_session(
        {
            "session_id": "sess_old",
            "symbol": "ETHUSDT",
            "interval": "5m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-02",
            "last_saved_at": "2026-01-02T00:00:00+08:00",
        }
    )
    storage.upsert_session(
        {
            "session_id": "sess_new",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_date_bjt": "2026-02-01",
            "end_date_bjt": "2026-02-02",
            "last_saved_at": "2026-02-02T00:00:00+08:00",
        }
    )

    rows = storage.list_performance_sessions()

    assert [row["session_id"] for row in rows] == ["sess_new", "sess_old"]
    assert set(rows[0]) == {
        "session_id",
        "symbol",
        "interval",
        "start_date_bjt",
        "end_date_bjt",
        "last_opened_at",
        "last_saved_at",
    }


def test_get_session_reads_the_explicit_restore_target_instead_of_latest(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_session(
        {
            "session_id": "sess_target",
            "symbol": "ETHUSDT",
            "interval": "5m",
            "cursor_bar_index": 37,
            "last_saved_at": "2026-01-01T00:00:00+08:00",
        }
    )
    storage.upsert_session(
        {
            "session_id": "sess_latest",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "cursor_bar_index": 99,
            "last_saved_at": "2026-02-01T00:00:00+08:00",
        }
    )

    row = storage.get_session("sess_target")

    assert row["session_id"] == "sess_target"
    assert row["symbol"] == "ETHUSDT"
    assert row["interval"] == "5m"
    assert row["cursor_bar_index"] == 37


def test_trade_management_range_matches_trade_by_entry_replay_time(tmp_path):
    storage = make_storage(tmp_path)
    insert_managed_trade(
        storage,
        trade_id="trd_in_range",
        entry_time="2026-01-01T00:05:00+08:00",
    )

    rows = storage.list_trade_samples_for_management(
        start_time="2026-01-01T00:05:00+08:00",
        end_time="2026-01-01T00:06:00+08:00",
    )

    assert [row["trade_id"] for row in rows] == ["trd_in_range"]
    assert rows[0]["entry_time"] == "2026-01-01T00:05:00+08:00"


def test_trade_management_session_list_is_narrow_and_scoped_to_selected_session(tmp_path):
    storage = make_storage(tmp_path)
    insert_managed_trade(
        storage,
        trade_id="trd_selected",
        session_id="sess_selected",
        entry_time="2026-01-01T00:05:00+08:00",
        exit_time="2026-01-01T00:06:00+08:00",
    )
    insert_managed_trade(
        storage,
        trade_id="trd_other",
        session_id="sess_other",
        entry_time="2026-01-01T00:07:00+08:00",
    )

    rows = storage.list_trade_samples_for_session("sess_selected")

    assert [row["trade_id"] for row in rows] == ["trd_selected"]
    assert set(rows[0]) == {
        "trade_id",
        "session_id",
        "symbol",
        "interval",
        "side",
        "status",
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "quantity",
        "return_pct",
        "pnl",
    }


def test_delete_performance_session_removes_its_trades_and_keeps_other_session(tmp_path):
    storage = make_storage(tmp_path)
    for session_id in ("sess_target", "sess_other"):
        storage.upsert_session(
            {
                "session_id": session_id,
                "initial_equity": 10_000.0,
                "trade_notional": 1_000.0,
            }
        )
    for sequence, pnl in enumerate((10.0, -5.0), start=1):
        insert_closed_managed_bundle(
            storage,
            trade_id=f"trd_target_{sequence}",
            session_id="sess_target",
            entry_time=f"2026-01-01T00:0{sequence}:00+08:00",
            exit_time=f"2026-01-01T00:1{sequence}:00+08:00",
            net_pnl_quote=pnl,
        )
    insert_closed_managed_bundle(
        storage,
        trade_id="trd_other",
        session_id="sess_other",
        entry_time="2026-01-01T00:03:00+08:00",
        exit_time="2026-01-01T00:13:00+08:00",
        net_pnl_quote=20.0,
    )
    other_equity = [
        {
            "session_id": "sess_other",
            "sequence_no": 1,
            "trade_id": "trd_other",
            "equity_after": 10_020.0,
        }
    ]
    storage.replace_equity_curve("sess_other", other_equity)
    before_other_equity = storage.fetch_table(
        "account_equity", "session_id=?", ("sess_other",)
    )

    preview = storage.preview_performance_session_deletion("sess_target")
    deleted = storage.delete_performance_session("sess_target")

    assert preview["trades"] == 2
    assert preview["session_ids"] == ["sess_target"]
    assert deleted["trades"] == 2
    assert storage.fetch_table("trades", "session_id=?", ("sess_target",)) == []
    assert storage.fetch_table("trade_events", "session_id=?", ("sess_target",)) == []
    assert storage.fetch_table("event_windows", "session_id=?", ("sess_target",)) == []
    assert storage.fetch_table("event_features", "session_id=?", ("sess_target",)) == []
    assert storage.fetch_table("account_equity", "session_id=?", ("sess_target",)) == []
    assert storage.fetch_table("sessions", "session_id=?", ("sess_target",)) == []
    assert storage.fetch_trade("trd_other") is not None
    assert (
        storage.fetch_table("account_equity", "session_id=?", ("sess_other",))
        == before_other_equity
    )


def test_delete_empty_performance_session_removes_session_but_keeps_market_data(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_session({"session_id": "sess_empty", "symbol": SYMBOL, "interval": INTERVAL})
    storage.upsert_session({"session_id": "sess_keep", "symbol": SYMBOL, "interval": INTERVAL})
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO klines (symbol, interval, open_time_utc_ms) VALUES (?, ?, ?)",
            (SYMBOL, INTERVAL, 1),
        )
        conn.execute(
            "INSERT INTO data_quality_reports (report_id, symbol, interval) VALUES (?, ?, ?)",
            ("report_keep", SYMBOL, INTERVAL),
        )

    deleted = storage.delete_performance_session("sess_empty")

    assert deleted["sessions"] == 1
    assert storage.get_session("sess_empty") is None
    assert storage.get_session("sess_keep") is not None
    assert len(storage.fetch_table("klines")) == 1
    assert len(storage.fetch_table("data_quality_reports")) == 1


def test_delete_performance_session_compacts_same_range_display_sequence(tmp_path):
    storage = make_storage(tmp_path)
    common = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "start_date_bjt": "2026-04-01",
        "end_date_bjt": "2026-05-01",
    }
    for session_id, saved_day in (
        ("sess_first", "03"),
        ("sess_middle", "02"),
        ("sess_last", "01"),
    ):
        storage.upsert_session(
            {
                **common,
                "session_id": session_id,
                "last_saved_at": f"2026-07-{saved_day}T00:00:00+08:00",
            }
        )

    before = list_performance_session_options(storage)
    storage.delete_performance_session("sess_middle")
    after = list_performance_session_options(storage)

    assert [option.session_id for option in before] == [
        "sess_first",
        "sess_middle",
        "sess_last",
    ]
    assert before[1].display_name.endswith("#2")
    assert before[2].display_name.endswith("#3")
    assert [option.session_id for option in after] == ["sess_first", "sess_last"]
    assert "#" not in after[0].display_name
    assert after[1].display_name.endswith("#2")


def test_delete_performance_session_removes_all_session_owned_research_records(tmp_path):
    storage = make_storage(tmp_path)
    for session_id in ("sess_target", "sess_keep"):
        storage.upsert_session({"session_id": session_id})
    with storage.connect() as conn:
        for suffix, session_id in (("target", "sess_target"), ("keep", "sess_keep")):
            sample_id = f"sample_{suffix}"
            annotation_id = f"annotation_{suffix}"
            conn.execute(
                """
                INSERT INTO observation_universe (
                    sample_id, session_id, source_type, symbol, interval, bar_index,
                    user_action, created_at
                ) VALUES (?, ?, 'USER_EVENT', ?, ?, 1, 'HOLD', ?)
                """,
                (sample_id, session_id, SYMBOL, INTERVAL, NOW),
            )
            conn.execute(
                """
                INSERT INTO strategy_samples (
                    strategy_sample_id, sample_id, experiment_id, feature_version,
                    label_version, dataset_hash, sample_role, created_at
                ) VALUES (?, ?, 'experiment', 'feature-v1', 'label-v1', 'hash',
                          'USER_ACTION', ?)
                """,
                (f"strategy_{suffix}", sample_id, NOW),
            )
            conn.execute(
                """
                INSERT INTO event_context_features (
                    context_feature_id, sample_id, session_id, feature_version,
                    symbol, interval, bar_index, lookback_bars, feature_name,
                    feature_value, created_at
                ) VALUES (?, ?, ?, 'feature-v1', ?, ?, 1, 20, 'range_pct', 1.0, ?)
                """,
                (f"context_{suffix}", sample_id, session_id, SYMBOL, INTERVAL, NOW),
            )
            conn.execute(
                """
                INSERT INTO research_outcome_labels (
                    outcome_label_id, sample_id, session_id, label_version,
                    symbol, interval, bar_index, horizon_bars, pricing_basis, created_at
                ) VALUES (?, ?, ?, 'label-v1', ?, ?, 1, 5, 'next_open', ?)
                """,
                (f"outcome_{suffix}", sample_id, session_id, SYMBOL, INTERVAL, NOW),
            )
            conn.execute(
                """
                INSERT INTO entry_annotations (annotation_id, observation_id, session_id)
                VALUES (?, ?, NULL)
                """,
                (annotation_id, sample_id),
            )
            conn.execute(
                """
                INSERT INTO entry_annotation_history (
                    annotation_id, revision_no, operation, session_id, snapshot_json
                ) VALUES (?, 1, 'CREATE', NULL, '{}')
                """,
                (annotation_id,),
            )

    deleted = storage.delete_performance_session("sess_target")

    assert deleted["research_records"] == 6
    for table in (
        "observation_universe",
        "event_context_features",
        "research_outcome_labels",
    ):
        assert storage.fetch_table(table, "session_id=?", ("sess_target",)) == []
        assert len(storage.fetch_table(table, "session_id=?", ("sess_keep",))) == 1
    assert storage.fetch_table("entry_annotations", "annotation_id=?", ("annotation_target",)) == []
    assert len(storage.fetch_table("entry_annotations", "annotation_id=?", ("annotation_keep",))) == 1
    assert storage.fetch_table(
        "entry_annotation_history", "annotation_id=?", ("annotation_target",)
    ) == []
    assert len(
        storage.fetch_table(
            "entry_annotation_history", "annotation_id=?", ("annotation_keep",)
        )
    ) == 1
    assert storage.fetch_table("strategy_samples", "sample_id=?", ("sample_target",)) == []
    assert len(storage.fetch_table("strategy_samples", "sample_id=?", ("sample_keep",))) == 1


def test_trade_management_range_matches_exit_event_but_not_position_only_overlap(tmp_path):
    storage = make_storage(tmp_path)
    insert_managed_trade(
        storage,
        trade_id="trd_exit_hit",
        entry_time="2026-01-01T00:01:00+08:00",
        exit_time="2026-01-01T00:05:30+08:00",
    )
    insert_managed_trade(
        storage,
        trade_id="trd_position_overlap_only",
        entry_time="2026-01-01T00:01:00+08:00",
        exit_time="2026-01-01T00:10:00+08:00",
    )

    rows = storage.list_trade_samples_for_management(
        start_time="2026-01-01T00:05:00+08:00",
        end_time="2026-01-01T00:06:00+08:00",
    )

    assert [row["trade_id"] for row in rows] == ["trd_exit_hit"]


def test_trade_management_adjacent_half_open_ranges_do_not_duplicate_boundary_event(tmp_path):
    storage = make_storage(tmp_path)
    insert_managed_trade(
        storage,
        trade_id="trd_boundary",
        entry_time="2026-01-01T00:06:00+08:00",
    )

    first = storage.list_trade_samples_for_management(
        start_time="2026-01-01T00:05:00+08:00",
        end_time="2026-01-01T00:06:00+08:00",
    )
    second = storage.list_trade_samples_for_management(
        start_time="2026-01-01T00:06:00+08:00",
        end_time="2026-01-01T00:07:00+08:00",
    )

    assert first == []
    assert [row["trade_id"] for row in second] == ["trd_boundary"]


def test_trade_sample_deletion_preview_counts_related_records_and_sessions(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_session({"session_id": SESSION_ID})
    insert_open_bundle(storage)
    storage.replace_equity_curve(
        SESSION_ID,
        [{"session_id": SESSION_ID, "sequence_no": 1, "trade_id": "trd_1"}],
    )

    preview = storage.preview_trade_sample_deletion(["trd_1"])

    assert preview["trades"] == 1
    assert preview["trade_events"] == 1
    assert preview["event_windows"] == 41
    assert preview["event_features"] == 1
    assert preview["account_equity"] == 1
    assert preview["session_ids"] == [SESSION_ID]


def test_delete_trade_sample_removes_relations_rebuilds_equity_and_keeps_session_market_data(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_session(
        {
            "session_id": SESSION_ID,
            "initial_equity": 10_000.0,
            "trade_notional": 1_000.0,
        }
    )
    insert_closed_managed_bundle(
        storage,
        trade_id="trd_delete",
        entry_time="2026-01-01T00:01:00+08:00",
        exit_time="2026-01-01T00:02:00+08:00",
        net_pnl_quote=10.0,
    )
    insert_closed_managed_bundle(
        storage,
        trade_id="trd_keep",
        entry_time="2026-01-01T00:03:00+08:00",
        exit_time="2026-01-01T00:04:00+08:00",
        net_pnl_quote=20.0,
    )
    storage.replace_equity_curve(
        SESSION_ID,
        [{"session_id": SESSION_ID, "sequence_no": 99, "equity_after": 99.0}],
    )
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO klines (symbol, interval, open_time_utc_ms) VALUES (?, ?, ?)",
            (SYMBOL, INTERVAL, 1),
        )
        conn.execute(
            "INSERT INTO data_quality_reports (report_id, symbol, interval) VALUES (?, ?, ?)",
            ("report_keep", SYMBOL, INTERVAL),
        )

    deleted = storage.delete_trade_samples(["trd_delete"])

    assert deleted["trades"] == 1
    assert deleted["trade_events"] == 2
    assert deleted["event_windows"] == 82
    assert deleted["event_features"] == 2
    assert storage.fetch_trade("trd_delete") is None
    assert storage.fetch_trade("trd_keep") is not None
    assert storage.fetch_table("trade_events", "trade_id=?", ("trd_delete",)) == []
    assert storage.fetch_table("event_windows", "event_id LIKE ?", ("trd_delete%",)) == []
    assert storage.fetch_table("event_features", "trade_id=?", ("trd_delete",)) == []
    equity = storage.fetch_table("account_equity", "session_id=?", (SESSION_ID,))
    assert len(equity) == 1
    assert equity[0]["trade_id"] == "trd_keep"
    assert equity[0]["equity_after"] == 10_020.0
    assert len(storage.fetch_table("sessions", "session_id=?", (SESSION_ID,))) == 1
    assert len(storage.fetch_table("klines")) == 1
    assert len(storage.fetch_table("data_quality_reports")) == 1


def test_delete_session_trade_does_not_change_other_session_trade_or_equity(tmp_path):
    storage = make_storage(tmp_path)
    for session_id in ("sess_target", "sess_other"):
        storage.upsert_session(
            {
                "session_id": session_id,
                "initial_equity": 10_000.0,
                "trade_notional": 1_000.0,
            }
        )
    insert_closed_managed_bundle(
        storage,
        trade_id="trd_target",
        session_id="sess_target",
        entry_time="2026-01-01T00:01:00+08:00",
        exit_time="2026-01-01T00:02:00+08:00",
        net_pnl_quote=10.0,
    )
    insert_closed_managed_bundle(
        storage,
        trade_id="trd_other",
        session_id="sess_other",
        entry_time="2026-01-01T00:03:00+08:00",
        exit_time="2026-01-01T00:04:00+08:00",
        net_pnl_quote=20.0,
    )
    storage.replace_equity_curve(
        "sess_other",
        [{"session_id": "sess_other", "sequence_no": 1, "trade_id": "trd_other", "equity_after": 10_020.0}],
    )
    before_other_equity = storage.fetch_table(
        "account_equity", "session_id=?", ("sess_other",)
    )

    storage.delete_trade_samples(["trd_target"])

    assert storage.fetch_trade("trd_other") is not None
    assert storage.fetch_table("account_equity", "session_id=?", ("sess_other",)) == before_other_equity


def test_delete_trade_samples_rolls_back_all_tables_when_sqlite_aborts_mid_transaction(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_session({"session_id": SESSION_ID})
    insert_closed_managed_bundle(
        storage,
        trade_id="trd_rollback",
        entry_time="2026-01-01T00:01:00+08:00",
        exit_time="2026-01-01T00:02:00+08:00",
        net_pnl_quote=10.0,
    )
    storage.replace_equity_curve(
        SESSION_ID,
        [{"session_id": SESSION_ID, "sequence_no": 1, "trade_id": "trd_rollback"}],
    )
    before = {
        table: storage.fetch_table(table, "session_id=?", (SESSION_ID,))
        for table in (
            "trades",
            "trade_events",
            "event_windows",
            "event_features",
            "account_equity",
        )
    }
    with storage.connect() as conn:
        conn.execute(
            """
            CREATE TRIGGER abort_trade_sample_delete
            BEFORE DELETE ON trades
            WHEN OLD.trade_id = 'trd_rollback'
            BEGIN
                SELECT RAISE(ABORT, 'rollback test');
            END
            """
        )

    with pytest.raises(Exception, match="rollback test"):
        storage.delete_trade_samples(["trd_rollback"])

    after = {
        table: storage.fetch_table(table, "session_id=?", (SESSION_ID,))
        for table in before
    }
    assert after == before


def test_delete_performance_session_rolls_back_on_sqlite_error(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_session({"session_id": "sess_rollback"})
    for sequence in (1, 2):
        insert_closed_managed_bundle(
            storage,
            trade_id=f"trd_session_rollback_{sequence}",
            session_id="sess_rollback",
            entry_time=f"2026-01-01T00:0{sequence}:00+08:00",
            exit_time=f"2026-01-01T00:1{sequence}:00+08:00",
            net_pnl_quote=10.0,
        )
    before = {
        table: storage.fetch_table(table, "session_id=?", ("sess_rollback",))
        for table in (
            "sessions",
            "trades",
            "trade_events",
            "event_windows",
            "event_features",
            "account_equity",
        )
    }
    with storage.connect() as conn:
        conn.execute(
            """
            CREATE TRIGGER abort_session_trade_sample_delete
            BEFORE DELETE ON trades
            WHEN OLD.trade_id = 'trd_session_rollback_2'
            BEGIN
                SELECT RAISE(ABORT, 'session rollback test');
            END
            """
        )

    with pytest.raises(Exception, match="session rollback test"):
        storage.delete_performance_session("sess_rollback")

    after = {
        table: storage.fetch_table(table, "session_id=?", ("sess_rollback",))
        for table in before
    }
    assert after == before


def test_fetch_event_windows_for_session_returns_stable_event_offset_order(tmp_path):
    storage = make_storage(tmp_path)

    storage.save_event_windows(
        SESSION_ID,
        "event_b",
        [make_ordered_window_row(2, 1), make_ordered_window_row(2, 0)],
    )
    storage.save_event_windows(
        SESSION_ID,
        "event_a",
        [make_ordered_window_row(1, 1), make_ordered_window_row(1, 0)],
    )
    with storage.connect() as connection:
        physical_order = [
            (row["event_id"], row["offset"])
            for row in connection.execute(
                "SELECT event_id, offset FROM event_windows WHERE session_id=? ORDER BY id",
                (SESSION_ID,),
            ).fetchall()
        ]

    rows = storage.fetch_event_windows_for_session(SESSION_ID)

    assert physical_order == [
        ("event_b", 1),
        ("event_b", 0),
        ("event_a", 1),
        ("event_a", 0),
    ]
    assert [(row["event_id"], row["offset"]) for row in rows] == [
        ("event_a", 0),
        ("event_a", 1),
        ("event_b", 0),
        ("event_b", 1),
    ]


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


def test_clear_all_trade_samples_keeps_sessions_market_quality_and_premium_data(tmp_path):
    storage = make_storage(tmp_path)
    storage.upsert_session({"session_id": SESSION_ID})
    insert_open_bundle(storage)
    with storage.connect() as conn:
        conn.execute(
            "INSERT INTO account_equity (session_id, sequence_no) VALUES (?, ?)",
            (SESSION_ID, 1),
        )
        conn.execute(
            "INSERT INTO usdt_premium_history (sample_time_bjt) VALUES (?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO klines (symbol, interval, open_time_utc_ms) VALUES (?, ?, ?)",
            (SYMBOL, INTERVAL, 1),
        )
        conn.execute(
            "INSERT INTO data_quality_reports (report_id, symbol, interval) VALUES (?, ?, ?)",
            ("report_1", SYMBOL, INTERVAL),
        )

    preview = storage.preview_all_trade_sample_deletion()
    deleted = storage.clear_manual_research_records()

    assert preview["trades"] == 1
    assert preview["trade_events"] == 1
    assert preview["event_windows"] == 41
    assert preview["event_features"] == 1
    assert preview["session_ids"] == [SESSION_ID]
    assert deleted["trades"] == 1
    assert deleted["trade_events"] == 1
    assert deleted["event_windows"] == 41
    assert deleted["event_features"] == 1
    assert deleted["account_equity"] == 1
    for table in StorageManager.MANUAL_RESEARCH_TABLES:
        assert storage.fetch_table(table) == []
    assert len(storage.fetch_table("sessions", "session_id=?", (SESSION_ID,))) == 1
    assert len(storage.fetch_table("usdt_premium_history")) == 1
    assert len(storage.fetch_table("klines")) == 1
    assert len(storage.fetch_table("data_quality_reports")) == 1
