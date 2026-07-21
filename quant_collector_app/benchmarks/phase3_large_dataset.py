from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import sqlite3
import threading
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

try:
    from app_config import APP_VERSION
    from chunked_csv import DEFAULT_CSV_CHUNK_ROWS, write_dataframe_csv_atomic
    from multi_timeframe import normalize_context_frame
    from research.bootstrap import bootstrap_mean_ci
    from research.kline_quality import build_kline_quality_report, validate_research_klines
    from controllers.analysis_controller import AnalysisRefreshController
    from main_app import MainWindow
    from workers.analysis_refresh_worker import AnalysisRefreshWorker
    from market_data.loader import KlineLoader
    from market_data.types import LoadRequest
    from storage import StorageManager
    from time_series_analysis.returns import build_return_series
except ImportError:  # pragma: no cover - package import path
    from ..app_config import APP_VERSION
    from ..chunked_csv import DEFAULT_CSV_CHUNK_ROWS, write_dataframe_csv_atomic
    from ..multi_timeframe import normalize_context_frame
    from ..research.bootstrap import bootstrap_mean_ci
    from ..research.kline_quality import build_kline_quality_report, validate_research_klines
    from ..controllers.analysis_controller import AnalysisRefreshController
    from ..main_app import MainWindow
    from ..workers.analysis_refresh_worker import AnalysisRefreshWorker
    from ..market_data.loader import KlineLoader
    from ..market_data.types import LoadRequest
    from ..storage import StorageManager
    from ..time_series_analysis.returns import build_return_series


DEFAULT_BARS = 270_000
DEFAULT_SEED = 20260713
DEFAULT_INTERVAL = "1m"


class BenchmarkCancelled(Exception):
    pass


def generate_klines(*, bars: int = DEFAULT_BARS, seed: int = DEFAULT_SEED) -> pd.DataFrame:
    row_count = int(bars)
    if row_count < 1:
        raise ValueError("bars must be positive")
    rng = np.random.default_rng(int(seed))
    times = pd.date_range("2025-01-01", periods=row_count, freq="min", tz="UTC")
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.05, row_count))
    open_price = np.concatenate(([close[0]], close[:-1]))
    spread = rng.uniform(0.01, 0.15, row_count)
    return pd.DataFrame(
        {
            "bar_index": np.arange(row_count, dtype=np.int64),
            "open_time_utc_ms": times.as_unit("ms").view("int64"),
            "open_time_bjt": times.tz_convert("Asia/Shanghai"),
            "open": open_price,
            "high": np.maximum(open_price, close) + spread,
            "low": np.minimum(open_price, close) - spread,
            "close": close,
            "volume": rng.uniform(1.0, 100.0, row_count),
        }
    )


def _data_hash(frame: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(frame, index=True).to_numpy(dtype=np.uint64)
    return hashlib.sha256(hashed.tobytes()).hexdigest()


def _market_data_hash(frame: pd.DataFrame) -> str:
    columns = [
        name
        for name in ("open_time_ms", "open", "high", "low", "close", "volume")
        if name in frame.columns
    ]
    canonical = frame.loc[:, columns].reset_index(drop=True).copy()
    for name in ("open", "high", "low", "close", "volume"):
        if name in canonical.columns:
            canonical[name] = pd.to_numeric(canonical[name], errors="raise").round(10)
    return _data_hash(canonical)


def _json_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _total_memory_bytes() -> int | None:
    if os.name != "nt":
        return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.total_physical)


def _environment() -> dict[str, Any]:
    return {
        "operating_system": platform.platform(),
        "windows_version": platform.win32_ver()[1] or None,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "application_version": APP_VERSION,
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": _total_memory_bytes(),
    }


def _finite_float(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"benchmark produced a non-finite measurement: {value!r}")
    return result


def _measure(
    name: str,
    rows: int,
    operation: Callable[[], Any],
    *,
    cancelled: Callable[[], bool] | None = None,
    resource_budget: int | None = None,
    batch_size: int | None = None,
    ui_thread: bool = False,
) -> tuple[dict[str, Any], Any]:
    if cancelled is not None and cancelled():
        raise BenchmarkCancelled()
    tracemalloc.start()
    started = time.perf_counter()
    status = "success"
    value: Any = None
    error: str | None = None
    try:
        value = operation()
        if cancelled is not None and cancelled():
            raise BenchmarkCancelled()
    except BenchmarkCancelled:
        status = "cancelled"
    except Exception as exc:  # report the failing path instead of losing the benchmark
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
    elapsed = _finite_float(time.perf_counter() - started)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result = {
        "task": name,
        "status": status,
        "wall_seconds": elapsed,
        "row_count": int(rows),
        "peak_python_bytes": int(peak),
        "ui_thread": bool(ui_thread),
        "resource_budget": int(resource_budget) if resource_budget is not None else None,
        "batch_size": int(batch_size) if batch_size is not None else None,
    }
    if error is not None:
        result["error"] = error
    return result, value


def _kline_rows(frame: pd.DataFrame):
    common = {
        "symbol": "BTCUSDT",
        "interval": DEFAULT_INTERVAL,
        "source": "phase3_benchmark",
        "downloaded_at": "2026-07-13T00:00:00+00:00",
        "data_quality_status": "PASS",
    }
    for row in frame.itertuples(index=False):
        yield {
            **common,
            "open_time_utc_ms": int(row.open_time_utc_ms),
            "open_time_bjt": row.open_time_bjt.isoformat(),
            "close_time_utc_ms": int(row.open_time_utc_ms) + 59_999,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }


def _analysis_benchmark_tasks(
    frame: pd.DataFrame,
    bars: int,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "analysis_refresh.sqlite"
    storage = StorageManager(db_path)
    storage.upsert_session(
        {
            "session_id": "phase3_benchmark",
            "initial_equity": 10_000.0,
            "trade_notional": 1_000.0,
        }
    )

    def run_production_chain() -> dict[str, Any]:
        from PySide6 import QtCore

        app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
        requests: list[Any] = []
        results: list[Any] = []
        errors: list[str] = []
        heartbeat: list[bool] = []
        destroyed = {"worker": False, "thread": False, "controller": False}
        loop = QtCore.QEventLoop()
        window = SimpleNamespace(
            df=frame,
            cursor=len(frame) - 1,
            session_id="phase3_benchmark",
            storage=SimpleNamespace(db_path=str(db_path)),
            _market_data_generation=1,
            initialEquitySpin=SimpleNamespace(value=lambda: 10_000.0),
            tradeNotionalSpin=SimpleNamespace(value=lambda: 1_000.0),
        )

        def capture_request():
            request = MainWindow._analysis_refresh_request(window)
            requests.append(request)
            return request

        def worker_factory():
            worker = AnalysisRefreshWorker()
            worker.destroyed.connect(
                lambda *_: destroyed.__setitem__("worker", True)
            )
            return worker

        def thread_factory(parent):
            thread = QtCore.QThread(parent)
            thread.destroyed.connect(
                lambda *_: destroyed.__setitem__("thread", True)
            )
            return thread

        controller = AnalysisRefreshController(
            snapshot_factory=capture_request,
            is_playing=lambda: False,
            delay_ms=0,
            worker_factory=worker_factory,
            thread_factory=thread_factory,
        )
        controller.destroyed.connect(
            lambda *_: destroyed.__setitem__("controller", True)
        )
        controller.resultReady.connect(lambda value: (results.append(value), loop.quit()))
        controller.failed.connect(lambda error: (errors.append(str(error)), loop.quit()))
        controller.schedule()
        heartbeat_timer = QtCore.QTimer(controller)
        heartbeat_timer.setSingleShot(True)
        heartbeat_timer.timeout.connect(lambda: heartbeat.append(True))
        heartbeat_timer.start(0)
        timeout_timer = QtCore.QTimer(controller)
        timeout_timer.setSingleShot(True)
        timeout_timer.timeout.connect(
            lambda: (
                errors.append("analysis production chain timed out"),
                controller.request_stop(),
            )
        )
        timeout_timer.start(60_000)
        poll = QtCore.QTimer(controller)
        poll.setInterval(10)
        poll.timeout.connect(
            lambda: loop.quit() if errors and not controller.is_running else None
        )
        poll.start()
        loop.exec()
        poll.stop()
        timeout_timer.stop()
        if controller.is_running:
            raise RuntimeError("analysis controller remained active after benchmark timeout")
        if errors or not results or not requests:
            raise RuntimeError(errors[0] if errors else "analysis worker returned no result")

        def run_until(predicate, timeout_ms: int = 5_000) -> bool:
            if predicate():
                return True
            cleanup_loop = QtCore.QEventLoop()
            cleanup_poll = QtCore.QTimer()
            cleanup_poll.setInterval(1)
            cleanup_poll.timeout.connect(
                lambda: cleanup_loop.quit() if predicate() else None
            )
            cleanup_timeout = QtCore.QTimer()
            cleanup_timeout.setSingleShot(True)
            cleanup_timeout.timeout.connect(cleanup_loop.quit)
            cleanup_poll.start()
            cleanup_timeout.start(timeout_ms)
            cleanup_loop.exec()
            cleanup_poll.stop()
            cleanup_timeout.stop()
            return bool(predicate())

        if not run_until(lambda: destroyed["worker"] and destroyed["thread"]):
            raise RuntimeError("analysis worker QObjects were not destroyed after QThread.finished")
        controller.deleteLater()
        if not run_until(lambda: destroyed["controller"]):
            raise RuntimeError("analysis controller QObject was not destroyed after benchmark")
        return {
            "result": results[0],
            "request": requests[0],
            "qt_heartbeat": heartbeat == [True],
            "worker_qobject_destroyed": destroyed["worker"],
            "thread_qobject_destroyed": destroyed["thread"],
            "controller_qobject_destroyed": destroyed["controller"],
        }

    worker_task, worker_result = _measure(
        "analysis_refresh_worker",
        bars,
        run_production_chain,
        ui_thread=False,
    )
    tasks: list[dict[str, Any]] = []
    if worker_result is not None:
        request = worker_result["request"]
        result = worker_result["result"]
        preparation = result.preparation
        tasks.append(
            {
                "task": "analysis_ui_input_capture",
                "status": "success",
                "wall_seconds": _finite_float(preparation.ui_input_capture_seconds),
                "row_count": int(bars),
                "peak_python_bytes": 0,
                "ui_thread": bool(
                    preparation.ui_thread_id == threading.main_thread().ident
                ),
                "thread_id": int(preparation.ui_thread_id),
                "resource_budget": None,
                "batch_size": None,
            }
        )
        tasks.append(
            {
                "task": "analysis_private_snapshot",
                "status": "success",
                "wall_seconds": _finite_float(preparation.private_snapshot_seconds),
                "row_count": int(bars),
                "peak_python_bytes": int(worker_task["peak_python_bytes"]),
                "peak_measurement": "analysis worker upper bound",
                "ui_thread": False,
                "worker_thread_id": int(preparation.worker_thread_id),
                "sqlite_thread_id": (
                    int(preparation.sqlite_thread_id)
                    if preparation.sqlite_thread_id is not None
                    else None
                ),
                "market_generation": int(preparation.market_generation),
                "revision": int(preparation.revision),
                "resource_budget": None,
                "batch_size": None,
            }
        )
        worker_task["qt_heartbeat"] = bool(worker_result["qt_heartbeat"])
        worker_task["worker_off_ui_thread"] = bool(
            preparation.worker_thread_id != preparation.ui_thread_id
        )
        worker_task["worker_calculation_seconds"] = _finite_float(
            preparation.calculation_seconds
        )
        worker_task["revision"] = int(result.revision)
        worker_task["market_generation"] = int(preparation.market_generation)
        worker_task["worker_qobject_destroyed"] = bool(
            worker_result["worker_qobject_destroyed"]
        )
        worker_task["thread_qobject_destroyed"] = bool(
            worker_result["thread_qobject_destroyed"]
        )
        worker_task["controller_qobject_destroyed"] = bool(
            worker_result["controller_qobject_destroyed"]
        )
    tasks.append(worker_task)
    return tasks, worker_result


def _cache_benchmark_tasks(
    frame: pd.DataFrame,
    bars: int,
    cache_dir: Path,
) -> list[dict[str, Any]]:
    class DeterministicClient:
        def __init__(self) -> None:
            self.calls = 0
            self.blocked = False

        def download(self, _symbol, _interval, _start, _end, _progress, _cancelled):
            if self.blocked:
                raise AssertionError("network access is forbidden after cold cache fill")
            self.calls += 1
            for row in frame.itertuples(index=False):
                open_time = int(row.open_time_utc_ms)
                yield [
                    open_time,
                    float(row.open),
                    float(row.high),
                    float(row.low),
                    float(row.close),
                    float(row.volume),
                    open_time + 59_999,
                    0.0,
                    0,
                    0.0,
                    0.0,
                    0,
                ]

    client = DeterministicClient()
    loader = KlineLoader(cache_dir=cache_dir, client=client)
    start = frame["open_time_bjt"].iloc[0].to_pydatetime()
    end = frame["open_time_bjt"].iloc[-1].to_pydatetime()
    request = LoadRequest("BTCUSDT", DEFAULT_INTERVAL, start, end, True)
    tasks: list[dict[str, Any]] = []

    def measured_load(name: str) -> tuple[dict[str, Any], pd.DataFrame]:
        before_calls = client.calls
        task, loaded = _measure(name, bars, lambda: loader.load(request))
        loaded_frame = loaded[0] if loaded is not None else pd.DataFrame()
        task["network_calls"] = client.calls - before_calls
        task["row_count"] = len(loaded_frame)
        task["data_hash"] = _market_data_hash(loaded_frame)
        task["quality_status"] = str(
            (loaded_frame.attrs.get("data_quality_report") or {}).get("data_quality_status")
            or "UNKNOWN"
        )
        return task, loaded_frame

    cold_task, cold_frame = measured_load("market_cold_load")
    tasks.append(cold_task)
    client.blocked = True
    exact_task, exact_frame = measured_load("market_exact_cache_hit")
    tasks.append(exact_task)

    exact_path = loader.cache_path("BTCUSDT", DEFAULT_INTERVAL, start, end)
    if not exact_path.exists():
        raise RuntimeError(f"cold cache file was not created: {cold_task}")
    coverage_path = exact_path.with_name("BTCUSDT_1m_coverage_bjt.csv")
    exact_path.replace(coverage_path)
    exact_manifest = loader.manifest_path(exact_path)
    if exact_manifest.exists():
        exact_manifest.replace(loader.manifest_path(coverage_path))
    coverage_task, coverage_frame = measured_load("market_coverage_cache_hit")
    tasks.append(coverage_task)

    expected_hash = cold_task["data_hash"]
    if exact_task["data_hash"] != expected_hash or coverage_task["data_hash"] != expected_hash:
        raise RuntimeError(
            "cache benchmark data hash mismatch: "
            f"cold={expected_hash}, exact={exact_task['data_hash']}, "
            f"coverage={coverage_task['data_hash']}"
        )
    if len(exact_frame) != len(cold_frame) or len(coverage_frame) != len(cold_frame):
        raise RuntimeError("cache benchmark row count mismatch")
    return tasks


def _run_once(
    *,
    run_number: int,
    bars: int,
    seed: int,
    output_dir: Path,
    cancelled: Callable[[], bool] | None,
) -> dict[str, Any]:
    frame = generate_klines(bars=bars, seed=seed)
    tasks: list[dict[str, Any]] = []

    analysis_tasks, snapshot = _analysis_benchmark_tasks(
        frame,
        bars,
        output_dir / f"phase3_analysis_{run_number}",
    )
    tasks.extend(analysis_tasks)
    del snapshot

    tasks.extend(
        _cache_benchmark_tasks(
            frame,
            bars,
            output_dir / f"phase3_cache_{run_number}",
        )
    )

    task, quality = _measure(
        "kline_quality_report",
        bars,
        lambda: build_kline_quality_report(frame, symbol="BTCUSDT", interval=DEFAULT_INTERVAL),
        cancelled=cancelled,
    )
    tasks.append(task)
    task, _unused = _measure(
        "research_quality_gate",
        bars,
        lambda: validate_research_klines(frame, context="phase3 benchmark"),
        cancelled=cancelled,
    )
    tasks.append(task)

    database_path = output_dir / f"phase3_run_{run_number}.db"
    database_path.unlink(missing_ok=True)
    storage = StorageManager(database_path)
    task, _unused = _measure(
        "sqlite_batch_write",
        bars,
        lambda: storage.upsert_klines(_kline_rows(frame)),
        cancelled=cancelled,
        batch_size=5_000,
    )
    tasks.append(task)
    with storage.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    task, sqlite_rows = _measure(
        "sqlite_bulk_read",
        bars,
        lambda: storage.fetch_table("klines"),
        cancelled=cancelled,
    )
    tasks.append(task)
    del sqlite_rows

    higher_frame = frame.iloc[::5].copy()
    higher_frame["bar_index"] = np.arange(len(higher_frame), dtype=np.int64)
    higher_frame["close_time_bjt"] = higher_frame["open_time_bjt"] + pd.Timedelta(minutes=5)
    task, normalized_higher = _measure(
        "multi_timeframe_prepare",
        len(higher_frame),
        lambda: normalize_context_frame(higher_frame, "5m"),
        cancelled=cancelled,
    )
    tasks.append(task)
    del normalized_higher, higher_frame

    task, returns = _measure(
        "time_series_returns",
        bars,
        lambda: build_return_series(frame),
        cancelled=cancelled,
    )
    tasks.append(task)
    if returns is None:
        raise RuntimeError("time-series benchmark failed before randomized statistics")
    sample = returns["simple_return"].dropna().tail(10_000)
    simulation_count = 1_000
    resource_budget = 20_000_000
    configured_batch_size = 128
    task, bootstrap = _measure(
        "bootstrap_mean_ci",
        len(sample),
        lambda: bootstrap_mean_ci(
            sample,
            n_boot=simulation_count,
            random_state=seed,
            batch_size=configured_batch_size,
            max_work_items=resource_budget,
        ),
        cancelled=cancelled,
        resource_budget=resource_budget,
        batch_size=configured_batch_size,
    )
    tasks.append(task)

    export_frame = returns.copy(deep=False)
    task, _unused = _measure(
        "export_preparation",
        len(export_frame),
        lambda: export_frame.reset_index(drop=True),
        cancelled=cancelled,
    )
    tasks.append(task)
    export_path = output_dir / f"phase3_run_{run_number}_time_series_returns.csv"
    task, _unused = _measure(
        "csv_file_write",
        len(export_frame),
        lambda: write_dataframe_csv_atomic(export_frame, export_path),
        cancelled=cancelled,
        batch_size=DEFAULT_CSV_CHUNK_ROWS,
    )
    task["output_bytes"] = int(export_path.stat().st_size) if export_path.exists() else 0
    tasks.append(task)

    research_settings = {
        key: bootstrap[key]
        for key in (
            "estimate",
            "ci_low",
            "ci_high",
            "random_seed",
            "simulation_count",
            "confidence",
            "method_version",
            "application_version",
            "batch_size",
            "batch_count",
            "work_items",
            "resource_budget",
        )
    }
    return {
        "run": int(run_number),
        "data_hash": _data_hash(frame),
        "research_hash": _json_hash(research_settings),
        "quality_status": str(quality["quality_status"]),
        "database_bytes": int(database_path.stat().st_size),
        "research_settings": research_settings,
        "tasks": tasks,
    }


def _markdown(report: dict[str, Any]) -> str:
    configuration = report["configuration"]
    lines = [
        "# Phase 3 large-dataset benchmark",
        "",
        f"- Bars: {configuration['bars']:,}",
        f"- Interval: {configuration['interval']}",
        f"- Seed: {configuration['seed']}",
        f"- Python: {report['environment']['python_version']}",
        f"- Application: {report['environment']['application_version']}",
        "- Execution boundary: background/non-UI core paths",
        f"- Private analysis snapshot SLO: <= {report['targets']['analysis_private_snapshot_max_seconds']:.3f} s",
        f"- SQLite write peak-memory SLO: <= {report['targets']['sqlite_write_peak_max_bytes'] / 1048576:.0f} MiB",
        "",
        "| Run | Task | Status | Wall (s) | Peak Python memory (MiB) | Rows |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for run in report["runs"]:
        for task in run["tasks"]:
            lines.append(
                f"| {run['run']} | {task['task']} | {task['status']} | "
                f"{task['wall_seconds']:.6f} | {task['peak_python_bytes'] / 1048576:.2f} | "
                f"{task['row_count']:,} |"
            )
    lines.extend(
        [
            "",
            "Timing is expected to vary. Data hash, seed, configuration, and research hash must not.",
            "CSV writing is measured separately from export preparation.",
            "",
        ]
    )
    baseline = report.get("baseline")
    if isinstance(baseline, dict):
        lines.extend(["## Before baseline", ""])
        for item in baseline.get("benchmarks", []):
            lines.append(
                f"- {item['name']}: {item['wall_seconds']:.6f} s, "
                f"{item['peak_python_bytes'] / 1048576:.2f} MiB peak"
            )
        lines.append("")
    return "\n".join(lines)


def run_benchmark_suite(
    *,
    bars: int = DEFAULT_BARS,
    seed: int = DEFAULT_SEED,
    runs: int = 2,
    output_dir: str | Path,
    cancelled: Callable[[], bool] | None = None,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    run_count = int(runs)
    if run_count < 1:
        raise ValueError("runs must be positive")
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    baseline = None
    if baseline_path is not None:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    try:
        from scripts.profile_startup import run_probe

        startup_raw = run_probe()
    except Exception as exc:
        startup_raw = {
            "ok": False,
            "process_wall_seconds": 0.0,
            "unexpected_optional_modules_loaded": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    startup_interactive_raw = startup_raw.get("cold_probe_seconds")
    if startup_interactive_raw is None:
        startup_interactive_raw = startup_raw.get("process_wall_seconds", 0.0)
    startup_interactive_seconds = _finite_float(startup_interactive_raw)
    startup_probe = {
        "status": "success" if startup_raw.get("ok") else "failed",
        # Schema v1 exposed wall_seconds; retain it as the budgeted in-process
        # measurement and record process creation overhead under its own key.
        "wall_seconds": startup_interactive_seconds,
        "interactive_seconds": startup_interactive_seconds,
        "process_wall_seconds": _finite_float(
            startup_raw.get("process_wall_seconds", 0.0)
        ),
        "unexpected_optional_modules_loaded": list(
            startup_raw.get("unexpected_optional_modules_loaded") or []
        ),
        "optional_modules_deferred": list(startup_raw.get("optional_modules_deferred") or []),
        "error": startup_raw.get("error"),
    }
    benchmark_runs = [
        _run_once(
            run_number=index,
            bars=int(bars),
            seed=int(seed),
            output_dir=target,
            cancelled=cancelled,
        )
        for index in range(1, run_count + 1)
    ]
    report = {
        "schema_version": 1,
        "environment": _environment(),
        "configuration": {
            "bars": int(bars),
            "seed": int(seed),
            "interval": DEFAULT_INTERVAL,
            "runs": run_count,
        },
        "targets": {
            "analysis_ui_input_capture_max_seconds": 0.05,
            "analysis_private_snapshot_max_seconds": 0.1,
            "sqlite_write_peak_max_bytes": 128 * 1024 * 1024,
            "cache_hit_to_cold_load_ratio_max": 0.9,
            "startup_max_seconds": 3.0,
            "ui_heavy_task_count": 0,
            "reproducible_hashes": True,
            "all_background_tasks_successful": True,
        },
        "startup_probe": startup_probe,
        "baseline": baseline,
        "runs": benchmark_runs,
    }
    for benchmark_run in benchmark_runs:
        tasks = {item["task"]: item for item in benchmark_run["tasks"]}
        if any(item["status"] != "success" for item in benchmark_run["tasks"]):
            raise RuntimeError("benchmark task failed or was cancelled")
        if not tasks["analysis_refresh_worker"].get("qt_heartbeat"):
            raise RuntimeError("analysis worker benchmark did not process a Qt heartbeat")
        if not tasks["analysis_refresh_worker"].get("worker_off_ui_thread"):
            raise RuntimeError("analysis worker benchmark ran on the UI thread")
        ui_capture = tasks["analysis_ui_input_capture"]
        private_snapshot = tasks["analysis_private_snapshot"]
        if not ui_capture.get("ui_thread"):
            raise RuntimeError("analysis UI input capture did not run on the Qt UI thread")
        if ui_capture["wall_seconds"] >= report["targets"]["analysis_ui_input_capture_max_seconds"]:
            report["targets"]["ui_heavy_task_count"] += 1
            raise RuntimeError("analysis UI input capture exceeded its budget")
        if private_snapshot.get("ui_thread"):
            report["targets"]["ui_heavy_task_count"] += 1
            raise RuntimeError("analysis private snapshot ran on the UI thread")
        if private_snapshot["wall_seconds"] > report["targets"]["analysis_private_snapshot_max_seconds"]:
            raise RuntimeError("analysis private snapshot exceeded its budget")
        if private_snapshot.get("sqlite_thread_id") != private_snapshot.get("worker_thread_id"):
            raise RuntimeError("analysis SQLite feature read did not run in the worker thread")
        if tasks["sqlite_batch_write"]["peak_python_bytes"] > report["targets"]["sqlite_write_peak_max_bytes"]:
            raise RuntimeError("SQLite batch write exceeded the peak-memory budget")
        cold_seconds = tasks["market_cold_load"]["wall_seconds"]
        for name in ("market_exact_cache_hit", "market_coverage_cache_hit"):
            tasks[name]["cold_load_ratio"] = tasks[name]["wall_seconds"] / max(cold_seconds, 1e-9)
            if int(bars) >= DEFAULT_BARS and tasks[name]["cold_load_ratio"] > report["targets"]["cache_hit_to_cold_load_ratio_max"]:
                raise RuntimeError(f"{name} did not meet the cache-hit performance budget")
    data_hashes = {item["data_hash"] for item in benchmark_runs}
    research_hashes = {item["research_hash"] for item in benchmark_runs}
    reproducible_hashes = len(data_hashes) == 1 and len(research_hashes) == 1
    report["targets"]["reproducible_hashes"] = reproducible_hashes
    if run_count >= 2 and not reproducible_hashes:
        raise RuntimeError("benchmark data or research hashes are not reproducible")
    if startup_probe["status"] != "success":
        raise RuntimeError(f"startup probe failed: {startup_probe.get('error')}")
    if startup_probe["wall_seconds"] >= report["targets"]["startup_max_seconds"]:
        raise RuntimeError("startup probe exceeded the 3 second budget")
    if startup_probe["unexpected_optional_modules_loaded"]:
        raise RuntimeError("startup imported optional modules eagerly")
    json_path = target / "phase3_benchmark.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (target / "phase3_benchmark.md").write_text(_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the opt-in Phase 3 large-dataset benchmark.")
    parser.add_argument("--bars", type=int, default=DEFAULT_BARS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)
    report = run_benchmark_suite(
        bars=args.bars,
        seed=args.seed,
        runs=args.runs,
        output_dir=args.output,
        baseline_path=args.baseline,
    )
    print(json.dumps({"output": str(args.output.resolve()), "runs": len(report["runs"])}, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = ["generate_klines", "run_benchmark_suite"]
