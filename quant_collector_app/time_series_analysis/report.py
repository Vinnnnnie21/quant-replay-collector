from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .baseline import build_random_bar_baseline, build_random_event_baseline, compare_events_to_baseline
from .regime import build_regime_features, summarize_regime_distribution
from .returns import build_return_series, summarize_return_distribution


def build_time_series_report(
    kline_df: pd.DataFrame,
    event_features: pd.DataFrame | None = None,
    source: str = "full_session_klines",
    returns_df: pd.DataFrame | None = None,
    regime_df: pd.DataFrame | None = None,
) -> dict:
    warnings: list[str] = []
    returns_df = returns_df if returns_df is not None else build_return_series(kline_df)
    if returns_df.empty:
        warnings.append("time series return analysis skipped: no usable kline data")
    regime_df = regime_df if regime_df is not None else build_regime_features(returns_df)
    limitations = [
        "Statistics are not investment advice.",
        "K-line data cannot reconstruct order book liquidity or partial fills.",
        "Random baseline is a research reference only.",
        "Small samples are not enough for conclusions.",
    ]
    if source == "event_windows_only":
        limitations.append("Time series analysis is based on event windows only, not the full session market series.")
        limitations.append("Returns are computed within each event window only; cross-window returns are intentionally disabled.")
        warnings.append("Time series analysis is based on event windows only, not the full session market series.")
        warnings.append("Event-window time series is fragmented; returns and autocorrelation do not represent the full market sequence.")

    result = {
        "source": source,
        "return_distribution": summarize_return_distribution(returns_df),
        "regime_distribution": summarize_regime_distribution(regime_df),
        "random_baseline": None,
        "random_bar_baseline": None,
        "random_baseline_comparison": None,
        "warnings": warnings,
        "limitations": limitations,
    }
    if event_features is not None and not event_features.empty:
        baseline = build_random_event_baseline(event_features)
        result["random_baseline"] = baseline
        if not baseline.get("skipped"):
            result["random_baseline_comparison"] = compare_events_to_baseline(event_features, baseline)
    if source == "full_session_klines" and kline_df is not None and not kline_df.empty:
        result["random_bar_baseline"] = build_random_bar_baseline(kline_df)
    return result


def write_time_series_report(result: dict, output_path: Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ret = result.get("return_distribution") or {}
    regimes = result.get("regime_distribution") or {}
    baseline = result.get("random_baseline") or {}
    random_bar = result.get("random_bar_baseline") or {}
    comparison = result.get("random_baseline_comparison") or {}
    warnings = result.get("warnings") or []
    limitations = result.get("limitations") or []

    lines = [
        "# Time Series Analysis Report",
        "",
        "This report is for research and review only. It is not investment advice.",
        "",
        "## Return Distribution",
        "",
        f"- sample_count: {ret.get('sample_count')}",
        f"- mean_return: {ret.get('mean_return')}",
        f"- median_return: {ret.get('median_return')}",
        f"- std_return: {ret.get('std_return')}",
        f"- skewness: {ret.get('skewness')}",
        f"- kurtosis: {ret.get('kurtosis')}",
        f"- q05 / q95: {ret.get('q05')} / {ret.get('q95')}",
        f"- min_return / max_return: {ret.get('min_return')} / {ret.get('max_return')}",
        "",
        "## Autocorrelation",
        "",
        f"- autocorr_lag_1: {ret.get('autocorr_lag_1')}",
        f"- autocorr_lag_3: {ret.get('autocorr_lag_3')}",
        f"- autocorr_lag_5: {ret.get('autocorr_lag_5')}",
        f"- squared_return_autocorr_lag_1: {ret.get('squared_return_autocorr_lag_1')}",
        f"- squared_return_autocorr_lag_5: {ret.get('squared_return_autocorr_lag_5')}",
        "",
        "## Volatility Regime",
        "",
        "```json",
        json.dumps(regimes.get("volatility_regime", {}), ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Trend Regime",
        "",
        "```json",
        json.dumps(regimes.get("trend_regime", {}), ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Random Baseline",
        "",
    ]
    if baseline:
        lines.extend(
            [
                f"- baseline_type: {baseline.get('baseline_type')}",
                f"- skipped: {baseline.get('skipped')}",
                f"- sample_size: {baseline.get('sample_size')}",
                f"- baseline_mean: {baseline.get('baseline_mean_distribution_mean')}",
                f"- baseline_q05 / baseline_q95: {baseline.get('baseline_q05')} / {baseline.get('baseline_q95')}",
                f"- event_mean: {comparison.get('event_mean')}",
                f"- event_mean_above_baseline_q95: {comparison.get('event_mean_above_baseline_q95')}",
            ]
        )
    else:
        lines.append("- No random baseline generated.")
    lines.extend(["", "## Random Bar Baseline", ""])
    if random_bar:
        lines.extend(
            [
                f"- baseline_type: {random_bar.get('baseline_type')}",
                f"- skipped: {random_bar.get('skipped')}",
                f"- sample_size: {random_bar.get('sample_size')}",
                f"- baseline_mean: {random_bar.get('baseline_mean_distribution_mean')}",
                f"- baseline_q05 / baseline_q95: {random_bar.get('baseline_q05')} / {random_bar.get('baseline_q95')}",
            ]
        )
    else:
        lines.append("- No random bar baseline generated.")
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {w}" for w in warnings] or ["- None"])
    lines.extend(["", "## Limitations", ""])
    lines.extend([f"- {item}" for item in limitations])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
