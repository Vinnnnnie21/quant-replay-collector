from __future__ import annotations

import itertools
import json
from typing import Any

import pandas as pd

from backtesting.engine import run_backtest
from backtesting.types import BacktestConfig


def time_series_split(df, train_ratio=0.6, valid_ratio=0.2, test_ratio=0.2) -> dict:
    data = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    warnings: list[str] = []
    if data.empty:
        return {"train": data, "valid": data.copy(), "test": data.copy(), "warnings": ["input dataframe is empty"]}
    total_ratio = float(train_ratio) + float(valid_ratio) + float(test_ratio)
    if total_ratio <= 0:
        raise ValueError("split ratios must be positive")
    train_ratio = float(train_ratio) / total_ratio
    valid_ratio = float(valid_ratio) / total_ratio
    n = len(data)
    if n < 30:
        warnings.append("sample size is small for train/validation/test split")
    train_end = max(1, min(n, int(n * train_ratio)))
    valid_end = max(train_end, min(n, train_end + int(n * valid_ratio)))
    if valid_end >= n and n >= 3:
        valid_end = n - 1
    return {
        "train": data.iloc[:train_end].copy(),
        "valid": data.iloc[train_end:valid_end].copy(),
        "test": data.iloc[valid_end:].copy(),
        "warnings": warnings,
    }


def _param_combinations(param_grid: dict[str, list[Any]], max_combinations: int = 300) -> tuple[list[dict], list[str]]:
    keys = list(param_grid.keys())
    values = [list(param_grid[k]) for k in keys]
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*values)]
    warnings = []
    if len(combos) > max_combinations:
        warnings.append(f"parameter combinations truncated from {len(combos)} to {max_combinations}")
        combos = combos[:max_combinations]
    return combos, warnings


def _strategy(strategy_factory, params: dict):
    return strategy_factory(**params)


def _metric_row(params: dict, result, split: str) -> dict:
    metrics = result.metrics or {}
    sharpe = metrics.get("time_sharpe")
    if sharpe is None:
        sharpe = metrics.get("trade_sharpe")
    row = {
        "split": split,
        "params_json": json.dumps(params, ensure_ascii=False, sort_keys=True),
        "total_trades": metrics.get("closed_trades") or metrics.get("total_trades"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "total_return_pct": metrics.get("total_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "sharpe": sharpe,
        "sortino": metrics.get("time_sortino") if metrics.get("time_sortino") is not None else metrics.get("trade_sortino"),
        "average_return_pct": metrics.get("average_return_pct"),
        "final_equity": metrics.get("final_equity"),
        "return_drawdown_ratio": (
            metrics.get("total_return_pct") / abs(metrics.get("max_drawdown_pct"))
            if metrics.get("total_return_pct") is not None and metrics.get("max_drawdown_pct") not in (None, 0)
            else None
        ),
        "warnings_json": json.dumps(result.warnings, ensure_ascii=False),
    }
    return row


def grid_search(
    df,
    strategy_factory,
    param_grid: dict,
    config: BacktestConfig,
    symbol: str,
    interval: str,
    split: str = "full",
    max_combinations: int = 300,
) -> pd.DataFrame:
    data = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    combos, warnings = _param_combinations(param_grid or {}, max_combinations=max_combinations)
    if not combos:
        combos = [{}]
    rows = []
    for params in combos:
        try:
            result = run_backtest(data, _strategy(strategy_factory, params), config, symbol, interval)
            row = _metric_row(params, result, split)
            if warnings:
                row["overfit_warning"] = "; ".join(warnings)
            else:
                row["overfit_warning"] = ""
        except Exception as exc:
            row = {
                "split": split,
                "params_json": json.dumps(params, ensure_ascii=False, sort_keys=True),
                "error": f"{type(exc).__name__}: {exc}",
                "overfit_warning": "; ".join(warnings),
            }
        rows.append(row)
    return pd.DataFrame(rows)


def _select_best(results: pd.DataFrame, objective: str) -> dict:
    if results.empty:
        return {}
    if objective not in results.columns:
        objective = "sharpe" if "sharpe" in results.columns else "total_return_pct"
    sortable = results.copy()
    sortable[objective] = pd.to_numeric(sortable[objective], errors="coerce")
    sortable = sortable.dropna(subset=[objective])
    if sortable.empty:
        row = results.iloc[0]
    else:
        row = sortable.sort_values(objective, ascending=False).iloc[0]
    try:
        return json.loads(row.get("params_json") or "{}")
    except Exception:
        return {}


def walk_forward_grid_search(
    df,
    strategy_factory,
    param_grid,
    config,
    symbol,
    interval,
    train_ratio=0.6,
    valid_ratio=0.2,
    test_ratio=0.2,
    objective: str = "sharpe",
    max_combinations: int = 300,
) -> dict:
    split_data = time_series_split(df, train_ratio, valid_ratio, test_ratio)
    train_results = grid_search(split_data["train"], strategy_factory, param_grid, config, symbol, interval, "train", max_combinations)
    valid_results = grid_search(split_data["valid"], strategy_factory, param_grid, config, symbol, interval, "valid", max_combinations)
    selected_params = _select_best(valid_results, objective)
    test_result_obj = run_backtest(split_data["test"], _strategy(strategy_factory, selected_params), config, symbol, interval)
    test_result = _metric_row(selected_params, test_result_obj, "test")
    warnings = list(split_data.get("warnings") or [])
    warnings.append("Parameters are selected on validation only; test is evaluated once.")
    warnings.append("Parameter scan results are candidate hypotheses and may be overfit.")
    valid_best = _select_best(valid_results, objective)
    train_best = _select_best(train_results, objective)
    if valid_best != train_best:
        warnings.append("Best train params differ from selected validation params.")
    valid_metric = pd.to_numeric(valid_results.get(objective), errors="coerce") if objective in valid_results.columns else pd.Series(dtype=float)
    test_metric = test_result.get(objective)
    if not valid_metric.dropna().empty and test_metric is not None:
        if float(test_metric) < float(valid_metric.max()) * 0.5:
            warnings.append("Test performance is materially weaker than validation; overfit risk is high.")
    return {
        "train_results": train_results,
        "valid_results": valid_results,
        "test_result": test_result,
        "selected_params": selected_params,
        "objective": objective,
        "warnings": warnings,
    }
