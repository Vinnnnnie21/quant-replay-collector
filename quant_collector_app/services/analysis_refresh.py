from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Callable, Iterable

import pandas as pd


@dataclass(frozen=True)
class AnalysisRefreshSnapshot:
    events: Iterable[dict[str, Any]]
    features: Iterable[dict[str, Any]]
    trades: Iterable[dict[str, Any]]
    equity_rows: Iterable[dict[str, Any]]
    initial_equity: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", _materialize_rows(self.events))
        object.__setattr__(self, "features", _materialize_rows(self.features))
        object.__setattr__(self, "trades", _materialize_rows(self.trades))
        object.__setattr__(self, "equity_rows", _materialize_rows(self.equity_rows))


@dataclass(frozen=True)
class AnalysisRefreshResult:
    event_study: pd.DataFrame
    dataset_text: str
    performance_text: str
    warnings: tuple[str, ...] = ()


def _materialize_rows(rows: pd.DataFrame | Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    if isinstance(rows, pd.DataFrame):
        return tuple(rows.to_dict("records"))
    return tuple(dict(row) for row in rows)


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
) -> tuple[pd.DataFrame, str | None]:
    if build_summary_fn is None:
        from event_study import build_event_study_summary

        build_summary_fn = build_event_study_summary
    try:
        event_frame = events.copy() if isinstance(events, pd.DataFrame) else pd.DataFrame(list(events))
        feature_frame = features.copy() if isinstance(features, pd.DataFrame) else pd.DataFrame(list(features))
        return build_summary_fn(event_frame, feature_frame), None
    except Exception as exc:
        return pd.DataFrame(), f"事件研究统计失败：{type(exc).__name__}: {exc}"


def build_dataset_summary_text(
    features: pd.DataFrame | Iterable[dict[str, Any]],
    *,
    build_ml_datasets_fn: Callable[[pd.DataFrame], dict[str, pd.DataFrame]] | None = None,
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
        blocked = ["未来收益字段", "事件后窗口字段", "最大有利/不利波动", "人工交易结果字段"]
        text = "\n".join(
            [
                f"当前会话事件特征行数: {len(feature_frame)}",
                f"特征表行/列: {len(ml_features)} / {len(ml_features.columns)}",
                f"标签表行/列: {len(ml_labels)} / {len(ml_labels.columns)}",
                f"样本索引行/列: {len(sample_index)} / {len(sample_index.columns)}",
                f"已隔离未来/结果字段: {', '.join(blocked)}",
            ]
        )
        return text, None
    except Exception as exc:
        text = f"机器学习样本摘要生成失败：{type(exc).__name__}: {exc}"
        return text, text


def build_performance_summary_text(
    trades: Iterable[dict[str, Any]],
    equity_rows: Iterable[dict[str, Any]],
    initial_equity: float,
    *,
    build_summary_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]], float], dict[str, Any]] | None = None,
    format_report_fn: Callable[[dict[str, Any]], str] | None = None,
) -> tuple[str, str | None]:
    if build_summary_fn is None or format_report_fn is None:
        from performance import build_performance_summary, format_performance_report

        build_summary_fn = build_summary_fn or build_performance_summary
        format_report_fn = format_report_fn or format_performance_report
    try:
        summary = build_summary_fn([dict(t) for t in trades], [dict(r) for r in equity_rows], initial_equity)
        return format_report_fn(summary), None
    except Exception as exc:
        text = f"统计生成失败：{type(exc).__name__}: {exc}"
        warning = f"交易绩效统计生成失败：{type(exc).__name__}: {exc}"
        return text, warning


def build_analysis_refresh_result(
    snapshot: AnalysisRefreshSnapshot,
    *,
    build_event_study_fn: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame] | None = None,
    build_ml_datasets_fn: Callable[[pd.DataFrame], dict[str, pd.DataFrame]] | None = None,
    build_performance_summary_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]], float], dict[str, Any]] | None = None,
    format_performance_report_fn: Callable[[dict[str, Any]], str] | None = None,
) -> AnalysisRefreshResult:
    event_study, event_warning = build_event_study_summary_frame(
        snapshot.events,
        snapshot.features,
        build_summary_fn=build_event_study_fn,
    )
    dataset_text, dataset_warning = build_dataset_summary_text(
        snapshot.features,
        build_ml_datasets_fn=build_ml_datasets_fn,
    )
    performance_text, performance_warning = build_performance_summary_text(
        snapshot.trades,
        snapshot.equity_rows,
        snapshot.initial_equity,
        build_summary_fn=build_performance_summary_fn,
        format_report_fn=format_performance_report_fn,
    )
    warnings = tuple(w for w in (event_warning, dataset_warning, performance_warning) if w)
    return AnalysisRefreshResult(
        event_study=event_study,
        dataset_text=dataset_text,
        performance_text=performance_text,
        warnings=warnings,
    )


__all__ = [
    "AnalysisRefreshResult",
    "AnalysisRefreshSnapshot",
    "DeferredAnalysisRefresh",
    "build_analysis_refresh_result",
    "build_dataset_summary_text",
    "build_event_study_summary_frame",
    "build_performance_summary_text",
]
