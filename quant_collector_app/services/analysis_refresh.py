from __future__ import annotations

from dataclasses import dataclass, field
from bisect import bisect_left
from types import MappingProxyType
from typing import Any
from collections.abc import Callable, Iterable, Mapping, Sequence
import threading
import time

import pandas as pd

try:
    from app_i18n import tr
except ImportError:  # pragma: no cover - package import path
    from ..app_i18n import tr


MAX_EQUITY_DISPLAY_ROWS = 2_000


@dataclass(frozen=True)
class PublishedMarketData:
    """Versioned reference to a frame that the UI replaces instead of mutating."""

    generation: int
    frame: pd.DataFrame = field(repr=False, compare=False)


@dataclass(frozen=True)
class AnalysisRefreshRequest:
    """Lightweight, Qt-free input captured on the UI thread."""

    db_path: str
    session_id: str
    market_data: PublishedMarketData | None
    market_cursor: int | None
    initial_equity: float
    trade_notional: float
    language: str = "zh_CN"
    revision: int = 0
    ui_input_capture_seconds: float = 0.0
    ui_thread_id: int = 0


@dataclass(frozen=True)
class AnalysisRefreshPreparation:
    worker_thread_id: int
    sqlite_thread_id: int | None
    market_generation: int
    private_snapshot_seconds: float
    revision: int
    ui_thread_id: int
    ui_input_capture_seconds: float
    calculation_seconds: float = 0.0


@dataclass(frozen=True)
class AnalysisRefreshSnapshot:
    events: Iterable[dict[str, Any]]
    features: Iterable[dict[str, Any]]
    trades: Iterable[dict[str, Any]]
    equity_rows: Iterable[dict[str, Any]]
    initial_equity: float
    market_frame: pd.DataFrame | None = None
    market_cursor: int | None = None
    session_id: str = ""
    trade_notional: float = 1000.0
    language: str = "zh_CN"
    revision: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", _materialize_rows(self.events))
        object.__setattr__(self, "features", _materialize_rows(self.features))
        object.__setattr__(self, "trades", _materialize_rows(self.trades))
        object.__setattr__(self, "equity_rows", _materialize_rows(self.equity_rows))
        frame = self.market_frame
        if isinstance(frame, pd.DataFrame):
            time_columns = (
                "open_time_bjt",
                "open_time_utc_ms",
                "open_time_ms",
                "timestamp",
                "open_time",
            )
            columns = [name for name in ("bar_index", *time_columns, "close") if name in frame.columns]
            object.__setattr__(
                self,
                "market_frame",
                frame.loc[:, columns].copy(deep=True),
            )


@dataclass(frozen=True)
class PerformanceTradeMarker:
    trade_id: str
    kind: str
    bar_index: int
    curve_time: Any | None
    equity_value: float
    pnl_value: float


@dataclass(frozen=True)
class PerformanceWorkspacePayload:
    equity_rows: tuple[Mapping[str, Any], ...]
    equity_total_rows: int
    metrics: Mapping[str, Any]
    distribution: Mapping[str, Any]
    equity_values: tuple[float, ...]
    pnl_values: tuple[float, ...]
    trades: tuple[Mapping[str, Any], ...]
    closed_pnls: tuple[float, ...]
    initial_equity: float
    default_notional: float
    markers: tuple[PerformanceTradeMarker, ...] = ()


@dataclass(frozen=True)
class AnalysisRefreshResult:
    event_study: pd.DataFrame
    dataset_text: str
    performance_text: str
    warnings: tuple[str, ...] = ()
    equity_rows: tuple[Mapping[str, Any], ...] = ()
    equity_total_rows: int = 0
    performance_workspace: PerformanceWorkspacePayload | None = None
    revision: int = 0
    preparation: AnalysisRefreshPreparation | None = None


class AnalysisRefreshCancelled(Exception):
    pass


@dataclass(frozen=True)
class AnalysisRefreshProgress:
    revision: int
    message: str


@dataclass(frozen=True)
class AnalysisRefreshFailure:
    revision: int
    message: str


@dataclass(frozen=True)
class AnalysisRefreshCancellation:
    revision: int


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise AnalysisRefreshCancelled()


def _materialize_rows(rows: pd.DataFrame | Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    if isinstance(rows, pd.DataFrame):
        return tuple(rows.to_dict("records"))
    return tuple(dict(row) for row in rows)


def prepare_analysis_refresh_snapshot(
    request: AnalysisRefreshRequest,
    *,
    storage_factory: Callable[[str], Any] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[AnalysisRefreshSnapshot, AnalysisRefreshPreparation]:
    """Create the owned calculation snapshot in the worker thread."""

    _raise_if_cancelled(cancelled)
    started = time.perf_counter()
    worker_thread_id = threading.get_ident()
    events: Iterable[dict[str, Any]] = ()
    trades: Iterable[dict[str, Any]] = ()
    features: Iterable[dict[str, Any]] = ()
    sqlite_thread_id: int | None = None
    if request.session_id and request.db_path:
        if storage_factory is None:
            try:
                from storage import StorageManager
            except ImportError:  # pragma: no cover - package import path
                from ..storage import StorageManager

            storage_factory = StorageManager
        storage = storage_factory(request.db_path)
        sqlite_thread_id = threading.get_ident()
        _session, trades, events = storage.load_session_snapshot(request.session_id)
        _raise_if_cancelled(cancelled)
        features = storage.fetch_table(
            "event_features", "session_id=?", (request.session_id,)
        )
    _raise_if_cancelled(cancelled)
    published = request.market_data
    snapshot = AnalysisRefreshSnapshot(
        events=events,
        features=features,
        trades=trades,
        equity_rows=(),
        initial_equity=request.initial_equity,
        market_frame=published.frame if published is not None else None,
        market_cursor=request.market_cursor,
        session_id=request.session_id,
        trade_notional=request.trade_notional,
        language=request.language,
        revision=request.revision,
    )
    preparation = AnalysisRefreshPreparation(
        worker_thread_id=worker_thread_id,
        sqlite_thread_id=sqlite_thread_id,
        market_generation=published.generation if published is not None else 0,
        private_snapshot_seconds=time.perf_counter() - started,
        revision=request.revision,
        ui_thread_id=request.ui_thread_id,
        ui_input_capture_seconds=request.ui_input_capture_seconds,
    )
    return snapshot, preparation


def _market_equity_rows(
    snapshot: AnalysisRefreshSnapshot,
    cancelled: Callable[[], bool] | None,
) -> Iterable[dict[str, Any]]:
    frame = snapshot.market_frame
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        if snapshot.equity_rows:
            return snapshot.equity_rows
        try:
            from accounting import build_equity_curve
        except ImportError:  # pragma: no cover - package import path
            from ..accounting import build_equity_curve
        _raise_if_cancelled(cancelled)
        rows = build_equity_curve(
            snapshot.trades,
            snapshot.session_id,
            snapshot.initial_equity,
            snapshot.trade_notional,
        )
        _raise_if_cancelled(cancelled)
        return rows
    try:
        from accounting import build_continuous_equity_curve
    except ImportError:  # pragma: no cover - package import path
        from ..accounting import build_continuous_equity_curve

    cursor = len(frame) - 1 if snapshot.market_cursor is None else int(snapshot.market_cursor)
    end = max(0, min(len(frame), cursor + 1))

    def iter_bars():
        for position, row in enumerate(frame.iloc[:end].itertuples(index=False), start=1):
            if position == 1 or position % 1024 == 0:
                _raise_if_cancelled(cancelled)
            yield {
                "bar_index": getattr(row, "bar_index", position - 1),
                "open_time_bjt": getattr(row, "open_time_bjt", None),
                "close": getattr(row, "close", None),
            }
        _raise_if_cancelled(cancelled)

    return build_continuous_equity_curve(
        iter_bars(),
        snapshot.trades,
        snapshot.session_id,
        snapshot.initial_equity,
        snapshot.trade_notional,
    )


def _bounded_equity_handoff(
    rows: Sequence[dict[str, Any]],
    limit: int = MAX_EQUITY_DISPLAY_ROWS,
) -> tuple[dict[str, Any], ...]:
    """Return a representative, ordered UI slice without changing calculations."""
    size = len(rows)
    if size <= limit:
        return tuple(dict(row) for row in rows)
    last = size - 1
    indices = (round(position * last / (limit - 1)) for position in range(limit))
    return tuple(dict(rows[index]) for index in indices)


def _performance_workspace_payload(
    snapshot: AnalysisRefreshSnapshot,
    equity_rows: Sequence[dict[str, Any]],
) -> PerformanceWorkspacePayload:
    try:
        from performance_analysis import build_performance_snapshot
    except ImportError:  # pragma: no cover - package import path
        from ..performance_analysis import build_performance_snapshot

    display_rows = _bounded_equity_handoff(equity_rows)
    full = build_performance_snapshot(
        equity_rows=equity_rows,
        trades=snapshot.trades,
        initial_equity=snapshot.initial_equity,
        default_notional=snapshot.trade_notional,
    )
    display = build_performance_snapshot(
        equity_rows=display_rows,
        trades=snapshot.trades,
        initial_equity=snapshot.initial_equity,
        default_notional=snapshot.trade_notional,
    )
    markers = _performance_trade_markers(
        display_rows,
        snapshot.trades,
        display["equity_values"],
        display["pnl_values"],
    )
    return PerformanceWorkspacePayload(
        equity_rows=tuple(MappingProxyType(dict(row)) for row in display_rows),
        equity_total_rows=len(equity_rows),
        metrics=MappingProxyType(dict(full["metrics"])),
        distribution=MappingProxyType(dict(full["distribution"])),
        equity_values=tuple(display["equity_values"]),
        pnl_values=tuple(display["pnl_values"]),
        trades=tuple(MappingProxyType(dict(trade)) for trade in snapshot.trades),
        closed_pnls=tuple(float(value) for value in full["closed_pnls"]),
        initial_equity=float(snapshot.initial_equity),
        default_notional=float(snapshot.trade_notional),
        markers=markers,
    )


def build_performance_workspace_payload(
    *,
    equity_rows: Iterable[dict[str, Any]],
    trades: Iterable[dict[str, Any]],
    initial_equity: float,
    default_notional: float,
) -> PerformanceWorkspacePayload:
    """Build the shared current/history performance payload without Qt state."""

    snapshot = AnalysisRefreshSnapshot(
        events=(),
        features=(),
        trades=trades,
        equity_rows=equity_rows,
        initial_equity=float(initial_equity),
        trade_notional=float(default_notional),
    )
    return _performance_workspace_payload(snapshot, snapshot.equity_rows)


def _performance_trade_markers(
    equity_rows: Sequence[dict[str, Any]],
    trades: Iterable[dict[str, Any]],
    equity_values: Sequence[float],
    pnl_values: Sequence[float],
) -> tuple[PerformanceTradeMarker, ...]:
    trade_rows = tuple(trades)
    positions: list[tuple[int, int, dict[str, Any]]] = []
    for position, row in enumerate(equity_rows):
        try:
            bar_index = int(row.get("bar_index", position))
        except (TypeError, ValueError):
            continue
        positions.append((bar_index, position, row))
    if not positions:
        return ()
    positions.sort(key=lambda item: item[0])
    sampled_bar_indices = [item[0] for item in positions]

    def nearest_display_position(bar_index: int) -> tuple[int, dict[str, Any]]:
        insertion = bisect_left(sampled_bar_indices, bar_index)
        candidates = positions[max(0, insertion - 1) : min(len(positions), insertion + 1)]
        _sampled_bar, position, row = min(
            candidates,
            key=lambda item: (abs(item[0] - bar_index), item[0]),
        )
        return position, row

    markers: list[PerformanceTradeMarker] = []
    for trade in trade_rows:
        trade_id = str(trade.get("trade_id") or "")
        for index_key, kind in (("entry_bar_index", "entry"), ("exit_bar_index", "exit")):
            try:
                bar_index = int(trade.get(index_key))
                position, row = nearest_display_position(bar_index)
            except (TypeError, ValueError):
                continue
            markers.append(
                PerformanceTradeMarker(
                    trade_id=trade_id,
                    kind=kind,
                    bar_index=bar_index,
                    curve_time=row.get("time") or row.get("created_at"),
                    equity_value=_smoothed_curve_value(equity_values, position),
                    pnl_value=_smoothed_curve_value(pnl_values, position),
                )
            )
    return tuple(markers)


def _smoothed_curve_value(values: Sequence[float], position: int, window: int = 5) -> float:
    if position <= 0 or position >= len(values) - 1:
        return float(values[position])
    radius = max(1, int(window) // 2)
    start = max(0, position - radius)
    end = min(len(values), position + radius + 1)
    return sum(float(value) for value in values[start:end]) / (end - start)


class DeferredAnalysisRefresh:
    """Debounce and run deferred analysis refresh tasks.

    This module is deliberately Qt-free. The caller injects the timer adapter so
    Qt widgets are still updated only by MainWindow on the main thread.
    """

    def __init__(self, delay_ms: int = 300) -> None:
        self.delay_ms = int(delay_ms)
        self.pending = False

    def schedule(self, single_shot: Callable[[int, Callable[[], None]], None], callback: Callable[[], None]) -> bool:
        if self.pending:
            return False
        self.pending = True
        single_shot(self.delay_ms, callback)
        return True

    def should_run(self, *, is_playing: bool, is_running: bool) -> bool:
        return self.pending and not is_playing and not is_running

    def defer(self, single_shot: Callable[[int, Callable[[], None]], None], callback: Callable[[], None]) -> bool:
        if not self.pending:
            return False
        single_shot(self.delay_ms, callback)
        return True

    def run(self, tasks: Iterable[Callable[[], None]], after: Callable[[], None] | None = None) -> None:
        try:
            for task in tasks:
                task()
        finally:
            self.pending = False
            if after is not None:
                after()


def build_event_study_summary_frame(
    events: pd.DataFrame | Iterable[dict[str, Any]],
    features: pd.DataFrame | Iterable[dict[str, Any]],
    *,
    build_summary_fn: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame] | None = None,
    language: str = "zh_CN",
) -> tuple[pd.DataFrame, str | None]:
    if build_summary_fn is None:
        from event_study import build_event_study_summary

        build_summary_fn = build_event_study_summary
    try:
        event_frame = events.copy() if isinstance(events, pd.DataFrame) else pd.DataFrame(list(events))
        feature_frame = features.copy() if isinstance(features, pd.DataFrame) else pd.DataFrame(list(features))
        return build_summary_fn(event_frame, feature_frame), None
    except Exception as exc:
        return pd.DataFrame(), tr("analysis.error.event_study", language).format(
            error=f"{type(exc).__name__}: {exc}"
        )


def build_dataset_summary_text(
    features: pd.DataFrame | Iterable[dict[str, Any]],
    *,
    build_ml_datasets_fn: Callable[[pd.DataFrame], dict[str, pd.DataFrame]] | None = None,
    language: str = "zh_CN",
) -> tuple[str, str | None]:
    if build_ml_datasets_fn is None:
        from dataset_builder import build_ml_datasets

        build_ml_datasets_fn = build_ml_datasets
    try:
        feature_frame = features.copy() if isinstance(features, pd.DataFrame) else pd.DataFrame(list(features))
        datasets = build_ml_datasets_fn(feature_frame)
        ml_features = datasets["ml_features"]
        ml_labels = datasets["ml_labels"]
        sample_index = datasets["sample_index"]
        blocked = [
            tr("analysis.dataset.blocked.future_returns", language),
            tr("analysis.dataset.blocked.post_event", language),
            tr("analysis.dataset.blocked.excursions", language),
            tr("analysis.dataset.blocked.manual_results", language),
        ]
        text = "\n".join(
            [
                tr("analysis.dataset.feature_rows", language).format(count=len(feature_frame)),
                tr("analysis.dataset.feature_shape", language).format(rows=len(ml_features), columns=len(ml_features.columns)),
                tr("analysis.dataset.label_shape", language).format(rows=len(ml_labels), columns=len(ml_labels.columns)),
                tr("analysis.dataset.index_shape", language).format(rows=len(sample_index), columns=len(sample_index.columns)),
                tr("analysis.dataset.blocked_fields", language).format(fields=", ".join(blocked)),
            ]
        )
        return text, None
    except Exception as exc:
        text = tr("analysis.error.dataset", language).format(
            error=f"{type(exc).__name__}: {exc}"
        )
        return text, text


def build_performance_summary_text(
    trades: Iterable[dict[str, Any]],
    equity_rows: Iterable[dict[str, Any]],
    initial_equity: float,
    *,
    build_summary_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]], float], dict[str, Any]] | None = None,
    format_report_fn: Callable[[dict[str, Any]], str] | None = None,
    language: str = "zh_CN",
) -> tuple[str, str | None]:
    use_default_formatter = format_report_fn is None
    if build_summary_fn is None or format_report_fn is None:
        from performance import build_performance_summary, format_performance_report

        build_summary_fn = build_summary_fn or build_performance_summary
        format_report_fn = format_report_fn or format_performance_report
    try:
        summary = build_summary_fn([dict(t) for t in trades], [dict(r) for r in equity_rows], initial_equity)
        if use_default_formatter:
            return format_report_fn(summary, language=language), None
        return format_report_fn(summary), None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        text = tr("analysis.error.statistics", language).format(error=error)
        warning = tr("analysis.error.performance", language).format(error=error)
        return text, warning


def build_analysis_refresh_result(
    snapshot: AnalysisRefreshSnapshot,
    *,
    build_event_study_fn: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame] | None = None,
    build_ml_datasets_fn: Callable[[pd.DataFrame], dict[str, pd.DataFrame]] | None = None,
    build_performance_summary_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]], float], dict[str, Any]] | None = None,
    format_performance_report_fn: Callable[[dict[str, Any]], str] | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> AnalysisRefreshResult:
    _raise_if_cancelled(cancelled)
    if progress is not None:
        progress(tr("analysis.progress.event_study", snapshot.language))
    event_study, event_warning = build_event_study_summary_frame(
        snapshot.events,
        snapshot.features,
        build_summary_fn=build_event_study_fn,
        language=snapshot.language,
    )
    _raise_if_cancelled(cancelled)
    if progress is not None:
        progress(tr("analysis.progress.dataset", snapshot.language))
    dataset_text, dataset_warning = build_dataset_summary_text(
        snapshot.features,
        build_ml_datasets_fn=build_ml_datasets_fn,
        language=snapshot.language,
    )
    _raise_if_cancelled(cancelled)
    if progress is not None:
        progress(tr("analysis.progress.performance", snapshot.language))
    equity_rows = _market_equity_rows(snapshot, cancelled)
    if not isinstance(equity_rows, Sequence):
        equity_rows = tuple(equity_rows)
    performance_text, performance_warning = build_performance_summary_text(
        snapshot.trades,
        equity_rows,
        snapshot.initial_equity,
        build_summary_fn=build_performance_summary_fn,
        format_report_fn=format_performance_report_fn,
        language=snapshot.language,
    )
    _raise_if_cancelled(cancelled)
    warnings = tuple(w for w in (event_warning, dataset_warning, performance_warning) if w)
    performance_workspace = _performance_workspace_payload(snapshot, equity_rows)
    display_equity_rows = performance_workspace.equity_rows
    return AnalysisRefreshResult(
        event_study=event_study,
        dataset_text=dataset_text,
        performance_text=performance_text,
        warnings=warnings,
        equity_rows=display_equity_rows,
        equity_total_rows=len(equity_rows),
        performance_workspace=performance_workspace,
        revision=snapshot.revision,
    )


__all__ = [
    "AnalysisRefreshCancellation",
    "AnalysisRefreshCancelled",
    "AnalysisRefreshFailure",
    "AnalysisRefreshProgress",
    "AnalysisRefreshPreparation",
    "AnalysisRefreshRequest",
    "AnalysisRefreshResult",
    "AnalysisRefreshSnapshot",
    "DeferredAnalysisRefresh",
    "MAX_EQUITY_DISPLAY_ROWS",
    "PerformanceTradeMarker",
    "PerformanceWorkspacePayload",
    "PublishedMarketData",
    "build_analysis_refresh_result",
    "build_dataset_summary_text",
    "build_event_study_summary_frame",
    "build_performance_summary_text",
    "build_performance_workspace_payload",
    "prepare_analysis_refresh_snapshot",
]
