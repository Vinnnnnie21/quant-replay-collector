from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from performance import build_performance_summary


RISK_RULES = [
    "This is not investment advice.",
    "Small samples cannot support strong conclusions.",
    "Statistical correlation is not causality.",
    "Replay or backtest returns do not represent live trading returns.",
    "Manual labels may contain selection bias.",
    "Candidate rules require out-of-sample validation.",
]

FORBIDDEN = [
    "Do not provide real-time buy or sell advice.",
    "Do not guarantee profit.",
    "Do not present in-sample statistics as certain future returns.",
    "Do not generate live order instructions.",
    "Do not request full SQLite access or user-provided SQL execution.",
    "Do not treat in-sample parameter scan results as a live-tradable strategy.",
    "Do not recommend trading based on a single backtest.",
    "Do not extract strategy rules from low-consistency samples.",
    "Do not explain mixed trading records as one stable strategy.",
    "Do not interpret strategy consistency score as profitability.",
    "Do not claim a strategy is effective when failed samples are missing.",
    "Do not bypass gate_failures to force a strategy interpretation.",
    "Do not interpret a high consistency score as profitability.",
    "Do not interpret time series statistics as trading signals.",
    "Do not interpret event_windows_only statistics as the full market distribution.",
    "Do not interpret random baseline empirical comparisons as causal conclusions.",
]


def _limit_records(df: pd.DataFrame, max_rows: int) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    safe = df.head(max(0, int(max_rows))).copy()
    return safe.where(pd.notna(safe), None).to_dict("records")


def _limit_list_records(value: Any, max_rows: int) -> list[dict[str, Any]]:
    if isinstance(value, pd.DataFrame):
        return _limit_records(value, max_rows)
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)][: max(0, int(max_rows))]
    return []


def _summary_stats(df: pd.DataFrame, value_col: str) -> dict[str, Any]:
    if df is None or df.empty or value_col not in df.columns:
        return {}
    series = pd.to_numeric(df[value_col], errors="coerce").dropna()
    if series.empty:
        return {}
    return {
        "count": int(len(series)),
        "mean": float(series.mean()),
        "median": float(series.median()),
        "min": float(series.min()),
        "max": float(series.max()),
    }


def _read_export_file(export_dir: Path | None, name: str) -> pd.DataFrame:
    if not export_dir:
        return pd.DataFrame()
    path = Path(export_dir) / name
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_export_json(export_dir: Path | None, name: str) -> dict[str, Any]:
    if not export_dir:
        return {}
    path = Path(export_dir) / name
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _compact_walk_forward(summary: dict[str, Any], max_rows: int) -> dict[str, Any]:
    if not summary:
        return {}
    return {
        "selected_params": summary.get("selected_params"),
        "objective": summary.get("objective"),
        "test_result": summary.get("test_result"),
        "warnings": summary.get("warnings"),
        "valid_results_top": _limit_list_records(summary.get("valid_results"), max_rows),
        "train_results_top": _limit_list_records(summary.get("train_results"), max_rows),
        "interpretation_notice": "Test set is evaluated once only and must not be used for parameter selection.",
    }


def _compact_time_series_summary(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    ret = summary.get("return_distribution") or {}
    compact = {
        "source": summary.get("source"),
        "return_distribution": {
            "sample_count": ret.get("sample_count"),
            "mean_return": ret.get("mean_return"),
            "std_return": ret.get("std_return"),
            "skewness": ret.get("skewness"),
            "kurtosis": ret.get("kurtosis"),
            "autocorr_lag_1": ret.get("autocorr_lag_1"),
            "squared_return_autocorr_lag_1": ret.get("squared_return_autocorr_lag_1"),
        },
        "regime_distribution": summary.get("regime_distribution"),
        "random_baseline": summary.get("random_baseline"),
        "random_baseline_comparison": summary.get("random_baseline_comparison"),
        "warnings": list(summary.get("warnings") or []),
        "limitations": summary.get("limitations") or [],
    }
    if compact["source"] == "event_windows_only":
        warning = "Time series analysis is based on event windows only, not the full session market series."
        if warning not in compact["warnings"]:
            compact["warnings"].append(warning)
    return _remove_path_keys(compact)


def _remove_path_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _remove_path_keys(v) for k, v in value.items() if "path" not in str(k).lower()}
    if isinstance(value, list):
        return [_remove_path_keys(item) for item in value]
    return value


def build_llm_context(session_id: str, storage, export_dir: Path | None = None, max_rows: int = 20) -> dict[str, Any]:
    session_rows = storage.fetch_table("sessions", "session_id=?", (session_id,))
    trades = storage.fetch_table("trades", "session_id=?", (session_id,))
    events = storage.fetch_table("trade_events", "session_id=?", (session_id,))
    equity = storage.fetch_table("account_equity", "session_id=?", (session_id,))
    session_info = dict(session_rows[0]) if session_rows else {"session_id": session_id}
    session_info = {k: v for k, v in session_info.items() if "path" not in str(k).lower()}
    perf = build_performance_summary(trades, equity, session_info.get("initial_equity"))

    event_study = _read_export_file(export_dir, "event_study_summary.csv")
    binning = _read_export_file(export_dir, "feature_binning_summary.csv")
    rules = _read_export_file(export_dir, "candidate_rules.csv")
    backtest_metrics = _remove_path_keys(_read_export_json(export_dir, "backtest_metrics.json"))
    parameter_scan = _read_export_file(export_dir, "parameter_scan_results.csv")
    walk_forward = _read_export_json(export_dir, "walk_forward_summary.json")
    consistency = _remove_path_keys(_read_export_json(export_dir, "strategy_consistency.json"))
    time_series_summary = _compact_time_series_summary(_read_export_json(export_dir, "time_series_summary.json"))
    consistency_summary = {
        "strategy_consistency_score": consistency.get("strategy_consistency_score"),
        "recommendation": consistency.get("recommendation"),
        "sample_count": consistency.get("sample_count"),
        "direction_consistency_pct": consistency.get("direction_consistency_pct"),
        "similar_context_agreement_pct": consistency.get("similar_context_agreement_pct"),
        "high_untagged_warning": consistency.get("high_untagged_warning"),
        "possible_random_trading_warning": consistency.get("possible_random_trading_warning"),
        "possible_selection_bias_warning": consistency.get("possible_selection_bias_warning"),
        "gate_failures": consistency.get("gate_failures", []),
        "label_score_detail": consistency.get("label_score_detail", {}),
        "profile_feature_match_all_pct": consistency.get("profile_feature_match_all_pct"),
    } if consistency else {}

    warnings = []
    if perf.get("closed_trades", 0) < 30:
        warnings.append("closed trade sample size is below 30; conclusions are unstable.")
    if len(events) < 100:
        warnings.append("event sample size is below 100; use for exploration only.")

    return {
        "session_info": session_info,
        "data_audit_summary": {
            "trade_count": len(trades),
            "event_count": len(events),
            "sample_warning": "strong_warning" if len(events) < 30 else ("weak_warning" if len(events) < 100 else "usable_for_exploration"),
        },
        "performance_summary": perf,
        "account_equity_summary": _summary_stats(pd.DataFrame(equity), "equity_after"),
        "event_study_top": _limit_records(event_study, max_rows),
        "feature_binning_top": _limit_records(binning, max_rows),
        "candidate_rules_top": _limit_records(rules, max_rows),
        "backtest_summary": {
            "metrics": backtest_metrics,
            "parameter_scan_top": _limit_records(parameter_scan, max_rows),
            "walk_forward": _compact_walk_forward(walk_forward, max_rows),
            "risk_notice": "Backtest outputs are research summaries only. Full trade lists are intentionally excluded.",
        },
        "strategy_consistency_summary": consistency_summary,
        "time_series_summary": time_series_summary,
        "sample_warnings": warnings,
        "leakage_warnings": ["Do not put fwd_*, post_*, mfe, mae, or manual_trade_* fields into model inputs."],
        "interpretation_rules": RISK_RULES,
        "forbidden_interpretations": FORBIDDEN,
        "next_data_to_collect": [
            "More successful reversal samples after large selloffs.",
            "More failed reversal samples after large selloffs.",
            "Negative observation samples where no trade was opened.",
            "Out-of-sample data across symbols and intervals.",
        ],
    }
