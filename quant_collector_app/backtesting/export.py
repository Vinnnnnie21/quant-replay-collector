from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def _df(data) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    return pd.DataFrame(data or [])


def _json_safe(value: Any):
    if isinstance(value, pd.DataFrame):
        return value.where(pd.notna(value), None).to_dict("records")
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _write_dictionary(output_dir: Path):
    lines = [
        "# Backtest Export Data Dictionary",
        "",
        "This directory contains research backtest outputs. Backtest returns do not represent live trading returns.",
        "",
        "## backtest_trades.csv",
        "- Closed backtest trades. Kept separate from manual replay trades and SQLite records.",
        "",
        "## backtest_equity_curve.csv",
        "- Bar-level realized equity curve produced by the backtest engine.",
        "",
        "## backtest_metrics.json",
        "- Summary metrics including net return, win rate, profit factor, drawdown and Sharpe/Sortino where available.",
        "",
        "## parameter_scan_results.csv",
        "- Optional grid search output. These rows are candidate hypotheses, not trading signals.",
        "",
        "## walk_forward_summary.json",
        "- Optional train/validation/test summary. Test set is evaluation only and must not be used for parameter selection.",
        "",
    ]
    (output_dir / "data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")


def export_backtest_result(
    result,
    output_dir: Path | str,
    parameter_scan_results: pd.DataFrame | None = None,
    walk_forward_summary: dict | None = None,
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    trades = _df(getattr(result, "trades", None))
    equity = _df(getattr(result, "equity_curve", None))
    metrics = dict(getattr(result, "metrics", {}) or {})
    metrics.setdefault("risk_notice", "Backtest result is for research only and does not represent live trading returns.")

    trades.to_csv(output / "backtest_trades.csv", index=False)
    equity.to_csv(output / "backtest_equity_curve.csv", index=False)
    (output / "backtest_metrics.json").write_text(
        json.dumps(_json_safe(metrics), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    scan = _df(parameter_scan_results)
    scan.to_csv(output / "parameter_scan_results.csv", index=False)
    summary = walk_forward_summary or {}
    (output / "walk_forward_summary.json").write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _write_dictionary(output)
    return output
