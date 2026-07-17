from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

import pandas as pd
import pytest

import exporter as exporter_module
from quant_collector_app.research import entry_logic_report
from export_publish import ExportDirectoryPublisher
from exporter import ExportCancelled, Exporter
from storage import StorageManager
from test_storage_trade_flow import (
    INTERVAL,
    NOW,
    SESSION_ID,
    SYMBOL,
    insert_open_bundle,
    make_event_row,
    make_feature_row,
    make_ordered_window_row,
    make_window_rows,
)


def make_storage(tmp_path: Path) -> StorageManager:
    return StorageManager(tmp_path / "export_test.db")


def test_entry_logic_report_calculation_failure_is_not_replaced_by_fallback(monkeypatch, tmp_path):
    def fail_report(**_kwargs):
        raise RuntimeError("entry calculation failed")

    monkeypatch.setattr(entry_logic_report, "build_entry_logic_report", fail_report)

    with pytest.raises(RuntimeError, match="entry calculation failed"):
        Exporter(object())._write_entry_logic_report(
            tmp_path,
            {},
            {},
            {"symbol": "BTCUSDT", "interval": "1m"},
            {},
            [],
        )


def test_missing_optional_parquet_engine_keeps_csv_and_emits_warning(monkeypatch, tmp_path, caplog):
    def missing_engine(*_args, **_kwargs):
        raise ImportError("no parquet engine")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", missing_engine)
    files = Exporter(object())._write_dataframes(
        tmp_path,
        {"trades": pd.DataFrame([{"trade_id": "trd_1"}])},
    )

    assert (tmp_path / "trades.csv").exists()
    assert files["trades"]["parquet_status"] == "skipped"
    assert "pyarrow or fastparquet is not installed" in caplog.text


def insert_session(storage: StorageManager):
    storage.upsert_session(
        {
            "session_id": SESSION_ID,
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
            "cursor_bar_index": 12,
            "follow_latest": 0,
            "speed": 1.0,
            "last_opened_at": NOW,
            "last_saved_at": NOW,
            "app_version": "test",
        }
    )


def insert_complete_trade(storage: StorageManager):
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


def test_export_session_writes_core_files(tmp_path):
    storage = make_storage(tmp_path)
    insert_session(storage)
    insert_complete_trade(storage)

    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)

    assert export_dir.exists()
    for name in [
        "trades.csv",
        "trade_events.csv",
        "event_windows_long.csv",
        "event_wide.csv",
        "event_features.csv",
        "event_labels.csv",
        "event_features_full.csv",
        "event_wide_full.csv",
        "account_equity.csv",
        "event_study_summary.csv",
        "ml_features.csv",
        "ml_labels.csv",
        "sample_index.csv",
        "sessions.csv",
        "usdt_premium_history.csv",
        "event_context_features.csv",
        "research_outcome_labels.csv",
    ]:
        assert (export_dir / name).exists(), name

    manifest_path = export_dir / "export_manifest.json"
    dictionary_path = export_dir / "data_dictionary.md"
    perf_csv = export_dir / "performance_summary.csv"
    perf_json = export_dir / "performance_summary.json"

    assert manifest_path.exists()
    assert dictionary_path.exists()
    assert perf_csv.exists() or perf_json.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["session_id"] == SESSION_ID
    assert manifest["symbol"] == SYMBOL
    assert manifest["interval"] == INTERVAL
    assert manifest["row_counts"]["trades"] == 1
    assert manifest["row_counts"]["trade_events"] == 2
    assert manifest["row_counts"]["performance_summary"] == 1
    assert "performance_summary" in manifest["files"]
    assert "ml_features" in manifest["files"]
    assert "event_study_summary" in manifest["files"]
    assert manifest["files"]["entry_logic_report"]["source"] == "formal_entry_logic_writer"
    dictionary = dictionary_path.read_text(encoding="utf-8")
    assert "event_context_features" in dictionary
    assert "research_outcome_labels" in dictionary
    assert "next_open" in dictionary
    assert "legacy_mid" in dictionary
    assert "does not represent executable fill" in dictionary
    assert "matched baseline is not a trading signal" in dictionary
    assert "p-value" in dictionary
    assert "sparse matched controls" in dictionary
    assert "Behavior consistency does not establish strategy effectiveness" in dictionary
    assert "Benjamini-Hochberg FDR" in dictionary
    assert "validated_candidate" in dictionary
    assert "out-of-sample degradation" in dictionary
    assert "not live trading advice" in dictionary


def test_export_session_passes_selected_research_label(tmp_path):
    storage = make_storage(tmp_path)
    insert_session(storage)
    insert_complete_trade(storage)

    export_dir = Exporter(storage).export_session(
        SESSION_ID,
        tmp_path / "exports",
        selected_label="fwd_ret_5_side_adj",
    )
    research_manifest = json.loads((export_dir / "research" / "research_manifest.json").read_text(encoding="utf-8"))
    assert research_manifest["selected_label"] == "fwd_ret_5_side_adj"


class LargeTradeStorage:
    def __init__(self) -> None:
        self.trades = [
            {
                "trade_id": f"trade_{index:05d}",
                "status": "OPEN",
                "side": "LONG",
                "entry_price_proxy": index / 10,
                "created_at": NOW,
            }
            for index in range(10_001)
        ]

    def fetch_table(self, table, where="", params=()):
        if table == "trades":
            return self.trades
        if table == "sessions":
            return [
                {
                    "session_id": SESSION_ID,
                    "symbol": SYMBOL,
                    "interval": INTERVAL,
                    "initial_equity": 10_000.0,
                    "trade_notional": 1_000.0,
                }
            ]
        return []

    def fetch_event_windows_for_session(self, _session_id):
        return []


def _directory_snapshot(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def test_export_session_uses_ordered_event_window_storage_read(tmp_path):
    class DedicatedEventWindowReadStorage(StorageManager):
        def fetch_table(self, table, where="", params=()):
            if table == "event_windows":
                raise AssertionError("event_windows must use its dedicated ordered reader")
            return super().fetch_table(table, where, params)

    storage = DedicatedEventWindowReadStorage(tmp_path / "ordered_export.db")
    insert_session(storage)
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

    export_dir = Exporter(storage).export_session(SESSION_ID, tmp_path / "exports")

    assert physical_order == [
        ("event_b", 1),
        ("event_b", 0),
        ("event_a", 1),
        ("event_a", 0),
    ]
    exported = pd.read_csv(export_dir / "event_windows_long.csv")
    assert list(zip(exported["event_id"], exported["offset"], strict=True)) == [
        ("event_a", 0),
        ("event_a", 1),
        ("event_b", 0),
        ("event_b", 1),
    ]


def test_cancelled_export_stops_before_creating_success_directory_or_manifest(tmp_path):
    storage = make_storage(tmp_path)
    insert_session(storage)
    target = tmp_path / "exports"

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(storage).export_session(
            SESSION_ID,
            target,
            cancelled=lambda: True,
        )

    export_dir = target / f"session_{SESSION_ID}"
    assert not export_dir.exists()
    assert not (export_dir / "export_manifest.json").exists()


def test_cancelled_export_keeps_original_exception_when_staging_cleanup_stays_locked(
    tmp_path,
    caplog,
    monkeypatch,
):
    storage = make_storage(tmp_path)
    insert_session(storage)
    export_root = tmp_path / "exports"
    remove_attempts: list[Path] = []

    def remove_with_persistent_acl_error(path: str | Path) -> None:
        path = Path(path)
        remove_attempts.append(path)
        raise PermissionError(5, "simulated persistent access denied", str(path))

    def publisher_factory(root: str | Path, final_name: str) -> ExportDirectoryPublisher:
        return ExportDirectoryPublisher(
            root,
            final_name,
            remove_tree=remove_with_persistent_acl_error,
            sleep=lambda _delay: None,
        )

    monkeypatch.setattr(exporter_module, "ExportDirectoryPublisher", publisher_factory)

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(storage).export_session(
            SESSION_ID,
            export_root,
            cancelled=lambda: True,
        )

    retained_staging = list(export_root.glob(f".session_{SESSION_ID}.staging-*"))
    assert len(remove_attempts) == 3
    assert retained_staging == remove_attempts[:1]
    assert str(retained_staging[0]) in caplog.text
    assert "cleanup deferred" in caplog.text


def test_cancelled_export_does_not_retry_or_replace_exception_for_non_transient_cleanup_error(
    tmp_path,
    caplog,
    monkeypatch,
):
    storage = make_storage(tmp_path)
    insert_session(storage)
    export_root = tmp_path / "exports"
    remove_attempts: list[Path] = []

    def remove_with_non_transient_error(path: str | Path) -> None:
        path = Path(path)
        remove_attempts.append(path)
        raise OSError("simulated non-transient cleanup error")

    def publisher_factory(root: str | Path, final_name: str) -> ExportDirectoryPublisher:
        return ExportDirectoryPublisher(
            root,
            final_name,
            remove_tree=remove_with_non_transient_error,
            sleep=lambda _delay: pytest.fail("non-transient cleanup must not retry"),
        )

    monkeypatch.setattr(exporter_module, "ExportDirectoryPublisher", publisher_factory)

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(storage).export_session(
            SESSION_ID,
            export_root,
            cancelled=lambda: True,
        )

    retained_staging = list(export_root.glob(f".session_{SESSION_ID}.staging-*"))
    assert retained_staging == remove_attempts
    assert str(retained_staging[0]) in caplog.text
    assert "simulated non-transient cleanup error" in caplog.text


def test_large_csv_export_cancels_after_first_completed_chunk_without_publishing_partial_file(tmp_path):
    cancel_requested = False
    progress_messages: list[str] = []

    def progress(message: str) -> None:
        nonlocal cancel_requested
        progress_messages.append(message)
        if message == "Writing export table: trades (chunk 1/2)":
            cancel_requested = True

    export_root = tmp_path / "exports"
    export_dir = export_root / f"session_{SESSION_ID}"

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(LargeTradeStorage()).export_session(
            SESSION_ID,
            export_root,
            cancelled=lambda: cancel_requested,
            progress=progress,
        )

    assert "Writing export table: trades (chunk 1/2)" in progress_messages
    assert "Writing export table: trades (chunk 2/2)" not in progress_messages
    assert not (export_dir / "trades.csv").exists()
    assert not list(export_dir.glob("*.partial"))
    assert not (export_dir / "export_manifest.json").exists()


def test_export_cancellation_during_research_does_not_publish_research_or_export_manifest(tmp_path):
    storage = make_storage(tmp_path)
    insert_session(storage)
    insert_complete_trade(storage)
    research_started = False
    research_cancellation_checks = 0

    def progress(message: str) -> None:
        nonlocal research_started
        if message == "Generating reproducible research pack...":
            research_started = True

    def cancelled() -> bool:
        nonlocal research_cancellation_checks
        if not research_started:
            return False
        research_cancellation_checks += 1
        return research_cancellation_checks >= 2

    export_root = tmp_path / "exports"
    export_dir = export_root / f"session_{SESSION_ID}"

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(storage).export_session(
            SESSION_ID,
            export_root,
            cancelled=cancelled,
            progress=progress,
        )

    assert research_started is True
    assert not (export_dir / "research" / "research_manifest.json").exists()
    assert not (export_dir / "export_manifest.json").exists()


def test_large_chunked_csv_export_preserves_columns_row_order_and_manifest(tmp_path):
    progress_messages: list[str] = []
    storage = LargeTradeStorage()
    export_dir = Exporter(storage).export_session(
        SESSION_ID,
        tmp_path / "exports",
        progress=progress_messages.append,
    )

    exported = pd.read_csv(export_dir / "trades.csv")
    manifest = json.loads((export_dir / "export_manifest.json").read_text(encoding="utf-8"))

    expected_path = tmp_path / "expected_single_call.csv"
    pd.DataFrame(storage.trades).sort_values(
        ["created_at", "trade_id"]
    ).reset_index(drop=True).to_csv(expected_path, index=False)

    assert exported.columns.tolist() == [
        "trade_id",
        "status",
        "side",
        "entry_price_proxy",
        "created_at",
    ]
    assert len(exported) == 10_001
    assert exported.iloc[0]["trade_id"] == "trade_00000"
    assert exported.iloc[-1]["trade_id"] == "trade_10000"
    assert progress_messages.count("Writing export table: trades (chunk 1/2)") == 1
    assert progress_messages.count("Writing export table: trades (chunk 2/2)") == 1
    assert manifest["row_counts"]["trades"] == 10_001
    assert (export_dir / "trades.csv").read_bytes() == expected_path.read_bytes()
    assert not list(export_dir.glob("*.partial"))


def test_cancelled_reexport_preserves_previous_successful_csv_and_manifest(tmp_path):
    storage = LargeTradeStorage()
    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)
    csv_path = export_dir / "trades.csv"
    manifest_path = export_dir / "export_manifest.json"
    original_csv = csv_path.read_bytes()
    original_manifest = manifest_path.read_bytes()
    cancel_requested = False

    def progress(message: str) -> None:
        nonlocal cancel_requested
        if message == "Writing export table: trades (chunk 1/2)":
            cancel_requested = True

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(storage).export_session(
            SESSION_ID,
            export_root,
            cancelled=lambda: cancel_requested,
            progress=progress,
        )

    assert csv_path.read_bytes() == original_csv
    assert manifest_path.read_bytes() == original_manifest
    assert not list(export_dir.glob("*.partial"))


def test_cancelled_reexport_after_first_table_preserves_entire_previous_export(tmp_path):
    storage = LargeTradeStorage()
    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)
    original_snapshot = _directory_snapshot(export_dir)
    original_manifest = (export_dir / "export_manifest.json").read_bytes()
    storage.trades.append(
        {
            "trade_id": "trade_new",
            "status": "OPEN",
            "side": "LONG",
            "entry_price_proxy": 1234.5,
            "created_at": NOW,
        }
    )
    cancel_requested = False

    def progress(message: str) -> None:
        nonlocal cancel_requested
        if message == "Writing export table: trade_events":
            cancel_requested = True

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(storage).export_session(
            SESSION_ID,
            export_root,
            cancelled=lambda: cancel_requested,
            progress=progress,
        )

    assert _directory_snapshot(export_dir) == original_snapshot
    assert (export_dir / "export_manifest.json").read_bytes() == original_manifest
    assert not list(export_root.glob(f".session_{SESSION_ID}.staging-*"))
    assert not list(export_root.glob(f".session_{SESSION_ID}.backup-*"))
    assert not list(export_root.rglob("*.partial"))


def test_cancelled_reexport_during_research_preserves_entire_previous_export(tmp_path):
    storage = make_storage(tmp_path)
    insert_session(storage)
    insert_complete_trade(storage)
    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)
    original_snapshot = _directory_snapshot(export_dir)
    with storage.connect() as connection:
        connection.execute(
            "UPDATE trades SET final_return_pct=? WHERE trade_id=?",
            (9.5, "trd_1"),
        )
    research_started = False
    research_cancellation_checks = 0

    def progress(message: str) -> None:
        nonlocal research_started
        if message == "Generating reproducible research pack...":
            research_started = True

    def cancelled() -> bool:
        nonlocal research_cancellation_checks
        if not research_started:
            return False
        research_cancellation_checks += 1
        return research_cancellation_checks >= 2

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(storage).export_session(
            SESSION_ID,
            export_root,
            cancelled=cancelled,
            progress=progress,
        )

    assert research_started is True
    assert _directory_snapshot(export_dir) == original_snapshot
    assert not list(export_root.glob(f".session_{SESSION_ID}.staging-*"))
    assert not list(export_root.glob(f".session_{SESSION_ID}.backup-*"))
    assert not list(export_root.rglob("*.partial"))


def test_successful_reexport_replaces_entire_directory_and_cleans_backup(tmp_path):
    storage = LargeTradeStorage()
    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)
    original_snapshot = _directory_snapshot(export_dir)
    storage.trades.append(
        {
            "trade_id": "trade_new",
            "status": "OPEN",
            "side": "LONG",
            "entry_price_proxy": 1234.5,
            "created_at": NOW,
        }
    )

    returned_dir = Exporter(storage).export_session(SESSION_ID, export_root)

    manifest = json.loads((returned_dir / "export_manifest.json").read_text(encoding="utf-8"))
    exported_trades = pd.read_csv(returned_dir / "trades.csv")
    assert returned_dir == export_root / f"session_{SESSION_ID}"
    assert _directory_snapshot(returned_dir) != original_snapshot
    assert len(exported_trades) == 10_002
    assert "trade_new" in set(exported_trades["trade_id"])
    assert manifest["row_counts"]["trades"] == len(exported_trades)
    for table_name, row_count in manifest["row_counts"].items():
        csv_path = returned_dir / manifest["files"][table_name]["csv"]
        assert csv_path.is_file()
        try:
            actual_row_count = len(pd.read_csv(csv_path))
        except pd.errors.EmptyDataError:
            actual_row_count = 0
        assert actual_row_count == row_count
    assert not list(export_root.glob(f".session_{SESSION_ID}.staging-*"))
    assert not list(export_root.glob(f".session_{SESSION_ID}.backup-*"))
    assert not list(export_root.rglob("*.partial"))


def test_successful_reexport_reports_when_locked_backup_cleanup_is_deferred(
    tmp_path,
    monkeypatch,
):
    storage = LargeTradeStorage()
    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)
    progress_messages: list[str] = []

    def remove_with_locked_backup(path: str | Path) -> None:
        path = Path(path)
        if ".backup-" in path.name:
            raise PermissionError(5, "simulated persistent access denied", str(path))
        shutil.rmtree(path)

    def publisher_factory(root: str | Path, final_name: str) -> ExportDirectoryPublisher:
        return ExportDirectoryPublisher(
            root,
            final_name,
            remove_tree=remove_with_locked_backup,
            sleep=lambda _delay: None,
        )

    monkeypatch.setattr(exporter_module, "ExportDirectoryPublisher", publisher_factory)

    returned_dir = Exporter(storage).export_session(
        SESSION_ID,
        export_root,
        progress=progress_messages.append,
    )

    assert returned_dir == export_dir
    assert "导出已完成，旧临时目录稍后清理" in progress_messages
    assert list(export_root.glob(f".session_{SESSION_ID}.backup-*"))


def test_cancellation_at_pre_publish_boundary_keeps_previous_export(tmp_path):
    storage = LargeTradeStorage()
    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)
    original_snapshot = _directory_snapshot(export_dir)
    storage.trades.append(
        {
            "trade_id": "trade_new",
            "status": "OPEN",
            "side": "LONG",
            "entry_price_proxy": 1234.5,
            "created_at": NOW,
        }
    )
    cancel_requested = False
    progress_messages: list[str] = []

    def progress(message: str) -> None:
        nonlocal cancel_requested
        progress_messages.append(message)
        if message == "Preparing to publish export results...":
            cancel_requested = True

    with pytest.raises(ExportCancelled, match="cancelled"):
        Exporter(storage).export_session(
            SESSION_ID,
            export_root,
            cancelled=lambda: cancel_requested,
            progress=progress,
        )

    assert _directory_snapshot(export_dir) == original_snapshot
    assert "正在安全发布导出结果" not in progress_messages
    assert not list(export_root.glob(f".session_{SESSION_ID}.staging-*"))
    assert not list(export_root.glob(f".session_{SESSION_ID}.backup-*"))


def test_safe_publish_phase_finishes_after_late_cancellation_request(tmp_path):
    storage = LargeTradeStorage()
    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)
    original_snapshot = _directory_snapshot(export_dir)
    storage.trades.append(
        {
            "trade_id": "trade_new",
            "status": "OPEN",
            "side": "LONG",
            "entry_price_proxy": 1234.5,
            "created_at": NOW,
        }
    )
    cancel_requested = False
    progress_messages: list[str] = []

    def progress(message: str) -> None:
        nonlocal cancel_requested
        progress_messages.append(message)
        if message == "正在安全发布导出结果":
            cancel_requested = True

    returned_dir = Exporter(storage).export_session(
        SESSION_ID,
        export_root,
        cancelled=lambda: cancel_requested,
        progress=progress,
    )

    assert cancel_requested is True
    assert "正在安全发布导出结果" in progress_messages
    assert returned_dir == export_dir
    assert _directory_snapshot(returned_dir) != original_snapshot
    assert len(pd.read_csv(returned_dir / "trades.csv")) == 10_002
    assert not list(export_root.glob(f".session_{SESSION_ID}.staging-*"))
    assert not list(export_root.glob(f".session_{SESSION_ID}.backup-*"))
