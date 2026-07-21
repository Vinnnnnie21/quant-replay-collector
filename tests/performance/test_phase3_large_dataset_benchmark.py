from __future__ import annotations

import json
import math
import time

import pandas as pd
import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.mark.performance
def test_phase3_large_dataset_benchmark_is_reproducible_and_writes_reports(tmp_path):
    from quant_collector_app.benchmarks.phase3_large_dataset import run_benchmark_suite

    result = run_benchmark_suite(
        bars=270_000,
        seed=20260713,
        runs=2,
        output_dir=tmp_path,
    )

    assert result["environment"]["python_version"]
    assert result["environment"]["application_version"]
    assert result["configuration"]["bars"] == 270_000
    assert result["configuration"]["interval"] == "1m"
    assert len(result["runs"]) == 2
    assert {run["data_hash"] for run in result["runs"]} == {result["runs"][0]["data_hash"]}
    assert {run["research_hash"] for run in result["runs"]} == {
        result["runs"][0]["research_hash"]
    }
    assert all(item["status"] == "success" for run in result["runs"] for item in run["tasks"])

    json_path = tmp_path / "phase3_benchmark.json"
    markdown_path = tmp_path / "phase3_benchmark.md"
    assert json_path.exists()
    assert markdown_path.exists()
    decoded = json.loads(json_path.read_text(encoding="utf-8"))
    assert decoded == result
    assert "270,000" in markdown_path.read_text(encoding="utf-8")

    def assert_finite_json(value):
        if isinstance(value, dict):
            for child in value.values():
                assert_finite_json(child)
        elif isinstance(value, list):
            for child in value:
                assert_finite_json(child)
        elif isinstance(value, float):
            assert math.isfinite(value)

    assert_finite_json(decoded)


@pytest.mark.performance
def test_phase3_benchmark_records_ui_handoff_boundary_and_slo(tmp_path):
    from quant_collector_app.benchmarks.phase3_large_dataset import run_benchmark_suite

    result = run_benchmark_suite(
        bars=1_000,
        seed=20260713,
        runs=1,
        output_dir=tmp_path,
    )

    tasks = {item["task"]: item for item in result["runs"][0]["tasks"]}
    assert tasks["analysis_ui_input_capture"]["ui_thread"] is True
    assert tasks["analysis_ui_input_capture"]["wall_seconds"] < result["targets"][
        "analysis_ui_input_capture_max_seconds"
    ]
    assert tasks["analysis_private_snapshot"]["ui_thread"] is False
    assert tasks["analysis_private_snapshot"]["worker_thread_id"] != tasks[
        "analysis_ui_input_capture"
    ]["thread_id"]
    assert tasks["analysis_private_snapshot"]["sqlite_thread_id"] == tasks[
        "analysis_private_snapshot"
    ]["worker_thread_id"]
    assert tasks["analysis_private_snapshot"]["market_generation"] == 1
    assert tasks["analysis_private_snapshot"]["revision"] == 1
    assert tasks["analysis_refresh_worker"]["ui_thread"] is False
    assert tasks["analysis_refresh_worker"]["qt_heartbeat"] is True
    assert tasks["analysis_refresh_worker"]["worker_qobject_destroyed"] is True
    assert tasks["analysis_refresh_worker"]["thread_qobject_destroyed"] is True
    assert tasks["analysis_refresh_worker"]["controller_qobject_destroyed"] is True
    assert tasks["market_cold_load"]["data_hash"] == tasks["market_exact_cache_hit"]["data_hash"]
    assert tasks["market_cold_load"]["data_hash"] == tasks["market_coverage_cache_hit"]["data_hash"]
    assert tasks["market_exact_cache_hit"]["network_calls"] == 0
    assert tasks["market_coverage_cache_hit"]["network_calls"] == 0
    assert tasks["multi_timeframe_prepare"]["ui_thread"] is False
    assert result["targets"]["ui_heavy_task_count"] == 0
    assert result["targets"]["reproducible_hashes"] is True
    assert result["startup_probe"]["wall_seconds"] < 3.0
    assert result["startup_probe"]["unexpected_optional_modules_loaded"] == []


@pytest.mark.performance
def test_phase3_benchmark_applies_startup_budget_to_interactive_probe_time(
    tmp_path,
    monkeypatch,
):
    from quant_collector_app.benchmarks.phase3_large_dataset import run_benchmark_suite
    from scripts import profile_startup

    monkeypatch.setattr(
        profile_startup,
        "run_probe",
        lambda: {
            "ok": True,
            "process_wall_seconds": 3.2,
            "cold_probe_seconds": 2.8,
            "unexpected_optional_modules_loaded": [],
            "optional_modules_deferred": [],
            "error": None,
        },
    )

    result = run_benchmark_suite(
        bars=1_000,
        seed=20260713,
        runs=1,
        output_dir=tmp_path,
    )

    assert result["startup_probe"]["interactive_seconds"] == pytest.approx(2.8)
    assert result["startup_probe"]["process_wall_seconds"] == pytest.approx(3.2)


@pytest.mark.performance
def test_phase3_benchmark_fails_when_real_ui_input_capture_exceeds_budget(
    tmp_path, monkeypatch
):
    from quant_collector_app.benchmarks import phase3_large_dataset as benchmark

    original = benchmark.MainWindow._analysis_refresh_request

    def slow_capture(window):
        time.sleep(0.06)
        return original(window)

    monkeypatch.setattr(
        benchmark.MainWindow,
        "_analysis_refresh_request",
        slow_capture,
    )

    with pytest.raises(RuntimeError, match="UI input capture exceeded"):
        benchmark.run_benchmark_suite(
            bars=1_000,
            seed=20260713,
            runs=1,
            output_dir=tmp_path,
        )


@pytest.mark.performance
def test_historical_270k_cached_curve_keeps_heartbeat_and_uses_full_metrics(
    tmp_path,
    monkeypatch,
):
    from controllers.historical_performance_controller import (
        HistoricalPerformanceController,
    )
    import workers.historical_performance_worker as historical_worker_module
    from workers.historical_performance_worker import HistoricalPerformanceWorker

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    bar_count = 270_000
    sampled_indices = {
        round(position * (bar_count - 1) / (2_000 - 1))
        for position in range(2_000)
    }
    dip_index = next(
        index for index in range(1, bar_count - 1) if index not in sampled_indices
    )
    start_time_utc_ms = 1_767_196_800_000
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    close_values = pd.Series(100.0, index=range(bar_count))
    close_values.iloc[dip_index] = 50.0
    pd.DataFrame(
        {
            "open_time_ms": start_time_utc_ms
            + pd.RangeIndex(bar_count).to_numpy() * 60_000,
            "close": close_values,
        }
    ).to_csv(
        cache_dir / "BTCUSDT_1m_20260101_20261231_bjt.csv",
        index=False,
    )

    class StorageBoundary:
        def load_session_snapshot(self, _session_id):
            return (
                {
                    "session_id": "session_history",
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "start_date_bjt": "2026-01-01",
                    "end_date_bjt": "2026-12-31",
                    "initial_equity": 1_000.0,
                    "trade_notional": 500.0,
                },
                [
                    {
                        "trade_id": "open_history_trade",
                        "session_id": "session_history",
                        "side": "LONG",
                        "status": "OPEN",
                        "entry_bar_index": 0,
                        "entry_fill_price": 100.0,
                        "notional_quote": 500.0,
                    }
                ],
                [],
            )

        def fetch_klines_for_range(self, **_kwargs):
            return []

    monkeypatch.setattr(
        historical_worker_module,
        "StorageManager",
        lambda _db_path: StorageBoundary(),
    )
    controller = HistoricalPerformanceController(
        db_path=tmp_path / "history.db",
        worker_factory=HistoricalPerformanceWorker,
    )
    order: list[str] = []
    results: list[object] = []
    errors: list[str] = []
    loop = QtCore.QEventLoop()

    def receive_result(result) -> None:
        results.append(result)
        order.append("result")
        loop.quit()

    controller.resultReady.connect(receive_result)
    controller.failed.connect(lambda error: (errors.append(error), loop.quit()))

    assert controller.request("session_history") is True
    QtCore.QTimer.singleShot(0, lambda: order.append("heartbeat"))
    QtCore.QTimer.singleShot(30_000, loop.quit)
    loop.exec()
    app.processEvents()

    assert errors == []
    assert order == ["heartbeat", "result"]
    payload = results[0].payload
    assert payload.equity_total_rows == bar_count
    assert len(payload.equity_rows) <= 2_000
    assert min(payload.equity_values) == pytest.approx(1_000.0)
    assert payload.metrics["max_drawdown_pct"] == pytest.approx(-25.0)
    assert controller.is_running is False
