from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

import pandas as pd

try:
    from backtesting.engine import run_backtest
    from backtesting.types import BacktestConfig, Signal
except ImportError:  # pragma: no cover - package import path
    from .engine import run_backtest
    from .types import BacktestConfig, Signal


DEFAULT_RANDOM_BASELINE_SEED = 20260722
DEFAULT_RANDOM_BASELINE_SIMULATIONS = 100
RANDOM_BASELINE_EQUITY_COLUMNS = ("bar_index", "time", "equity", "drawdown")


@dataclass(frozen=True)
class RandomBaselineConfig:
    simulation_count: int = DEFAULT_RANDOM_BASELINE_SIMULATIONS
    random_seed: int = DEFAULT_RANDOM_BASELINE_SEED
    max_schedule_attempts_per_run: int = 250


@dataclass(frozen=True)
class RandomBaselineResult:
    status: str
    median_equity_curve: pd.DataFrame
    summary: dict[str, Any]
    warnings: list[str]


class FixedRandomEntryStrategy:
    def __init__(self, *, side: str, signal_positions: set[int]):
        self.side = side.upper()
        self.signal_positions = set(signal_positions)
        self.name = f"RandomEntryBaseline{self.side.title()}"

    def on_bar(
        self,
        i: int,
        row: pd.Series,
        history: pd.DataFrame,
        position: dict | None = None,
    ) -> str:
        if position is not None or i not in self.signal_positions:
            return Signal.HOLD
        if self.side == "SHORT":
            return Signal.OPEN_SHORT
        return Signal.OPEN_LONG


def run_random_entry_baseline(
    market_df: pd.DataFrame,
    strategy_trades: pd.DataFrame,
    config: BacktestConfig,
    *,
    symbol: str,
    interval: str,
    random_config: RandomBaselineConfig | None = None,
) -> RandomBaselineResult:
    settings = random_config or RandomBaselineConfig()
    warnings: list[str] = []
    data = market_df.copy() if isinstance(market_df, pd.DataFrame) else pd.DataFrame()
    trades = strategy_trades.copy() if isinstance(strategy_trades, pd.DataFrame) else pd.DataFrame()
    target_trade_count = len(trades)
    base_summary = _base_summary(settings, config, target_trade_count)

    if data.empty:
        return _skipped(base_summary, "random baseline skipped: market data is empty")
    if target_trade_count <= 0:
        return _skipped(base_summary, "random baseline skipped: strategy has no trades")
    if "entry_bar_index" not in trades.columns:
        return _skipped(
            base_summary,
            "random baseline skipped: strategy trades missing entry_bar_index",
        )

    side = _strategy_side(trades)
    if side is None:
        return _skipped(
            base_summary,
            "random baseline skipped: strategy trades have mixed or missing side",
        )
    if side == "SHORT" and not config.allow_short:
        return _skipped(
            base_summary,
            "random baseline skipped: short entries are disabled by BacktestConfig",
        )
    if str(config.signal_timing or "").lower() != "next_open":
        return _skipped(
            base_summary,
            "random baseline skipped: only signal_timing=next_open is supported",
        )
    if config.max_bars_hold is None:
        return _skipped(
            base_summary,
            "random baseline skipped: max_bars_hold is required to enforce non-overlap",
        )

    strategy_entry_bars = _integer_set(trades["entry_bar_index"])
    holding_span = int(config.max_bars_hold) + 1
    cooldown = int(getattr(config, "cooldown_bars", 0) or 0)
    eligible = _eligible_execution_positions(data, strategy_entry_bars, holding_span)
    rng = random.Random(int(settings.random_seed))
    runs: list[dict[str, Any]] = []
    curves: list[pd.DataFrame] = []

    for run_index in range(int(settings.simulation_count)):
        schedule = _sample_schedule(
            rng,
            eligible,
            target_trade_count,
            minimum_spacing=holding_span + cooldown,
            attempts=int(settings.max_schedule_attempts_per_run),
        )
        if schedule is None:
            warnings.append(
                f"random baseline run {run_index} skipped: unable to sample {target_trade_count} non-overlapping entries"
            )
            continue
        raw = run_backtest(
            data,
            FixedRandomEntryStrategy(
                side=side,
                signal_positions={execution_i - 1 for execution_i in schedule},
            ),
            config,
            symbol,
            interval,
        )
        random_trades = raw.trades.copy() if isinstance(raw.trades, pd.DataFrame) else pd.DataFrame()
        if len(random_trades) != target_trade_count:
            actual_count = len(random_trades)
            warnings.append(
                f"random baseline run {run_index} skipped: "
                f"expected {target_trade_count} trades, got {actual_count}"
            )
            continue
        entry_bars = [int(value) for value in random_trades["entry_bar_index"].tolist()]
        if strategy_entry_bars.intersection(entry_bars):
            warnings.append(f"random baseline run {run_index} skipped: sampled a strategy entry bar")
            continue
        if _has_overlap(random_trades):
            warnings.append(f"random baseline run {run_index} skipped: produced overlapping trades")
            continue
        equity = _standardize_equity(raw.equity_curve)
        if equity.empty:
            warnings.append(f"random baseline run {run_index} skipped: equity curve is empty")
            continue
        runs.append(
            {
                "run_index": run_index,
                "entry_bar_indices": entry_bars,
                "exit_bar_indices": [
                    int(value) for value in random_trades["exit_bar_index"].tolist()
                ],
                "final_equity": float(equity["equity"].iloc[-1]),
            }
        )
        curves.append(equity)

    status = "ready" if len(runs) == int(settings.simulation_count) else "partial" if runs else "skipped"
    if status == "skipped":
        warnings.append("random baseline skipped: no complete random simulations were available")
    elif status == "partial":
        warnings.append("random baseline partial: some random simulations were unavailable")

    median_equity = _median_equity_curve(curves)
    summary = {
        **base_summary,
        "status": status,
        "completed_runs": len(runs),
        "direction": side,
        "runs": runs,
        "median": _median_summary(median_equity),
        "warnings": _unique(warnings),
    }
    return RandomBaselineResult(
        status=status,
        median_equity_curve=median_equity,
        summary=summary,
        warnings=_unique(warnings),
    )


def _base_summary(
    settings: RandomBaselineConfig,
    config: BacktestConfig,
    target_trade_count: int,
) -> dict[str, Any]:
    return {
        "status": "pending",
        "random_seed": int(settings.random_seed),
        "simulation_count": int(settings.simulation_count),
        "completed_runs": 0,
        "target_trade_count": int(target_trade_count),
        "constraints": {
            "signal_timing": config.signal_timing,
            "allow_short": bool(config.allow_short),
            "single_position": bool(config.single_position),
            "max_bars_hold": config.max_bars_hold,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "stop_take_priority": config.stop_take_priority,
            "fee_bps": config.fee_bps,
            "maker_fee_bps": config.maker_fee_bps,
            "taker_fee_bps": config.taker_fee_bps,
            "slippage_bps": config.slippage_bps,
            "notional_quote": config.notional_quote,
            "cooldown_bars": int(getattr(config, "cooldown_bars", 0) or 0),
        },
    }


def _skipped(summary: dict[str, Any], warning: str) -> RandomBaselineResult:
    skipped = {**summary, "status": "skipped", "warnings": [warning]}
    return RandomBaselineResult(
        status="skipped",
        median_equity_curve=pd.DataFrame(columns=RANDOM_BASELINE_EQUITY_COLUMNS),
        summary=skipped,
        warnings=[warning],
    )


def _strategy_side(trades: pd.DataFrame) -> str | None:
    if "side" not in trades.columns:
        return None
    sides = {
        str(value).upper()
        for value in trades["side"].dropna().tolist()
        if str(value).strip()
    }
    if len(sides) != 1:
        return None
    side = next(iter(sides))
    return side if side in {"LONG", "SHORT"} else None


def _integer_set(series: pd.Series) -> set[int]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return {int(value) for value in values.tolist()}


def _eligible_execution_positions(
    data: pd.DataFrame,
    strategy_entry_bars: set[int],
    holding_span: int,
) -> list[int]:
    reset = data.reset_index(drop=True)
    latest_execution_i = len(reset) - max(1, holding_span)
    eligible: list[int] = []
    for execution_i in range(1, latest_execution_i + 1):
        try:
            entry_bar = int(reset.iloc[execution_i]["bar_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if entry_bar not in strategy_entry_bars:
            eligible.append(execution_i)
    return eligible


def _sample_schedule(
    rng: random.Random,
    eligible: list[int],
    target_count: int,
    *,
    minimum_spacing: int,
    attempts: int,
) -> list[int] | None:
    if target_count <= 0:
        return []
    for _ in range(max(1, attempts)):
        candidates = list(eligible)
        rng.shuffle(candidates)
        selected: list[int] = []
        for execution_i in candidates:
            proposal = sorted([*selected, execution_i])
            if _is_spaced(proposal, minimum_spacing):
                selected.append(execution_i)
                if len(selected) == target_count:
                    return sorted(selected)
    return None


def _is_spaced(positions: list[int], minimum_spacing: int) -> bool:
    ordered = sorted(positions)
    return all(right - left >= minimum_spacing for left, right in zip(ordered, ordered[1:]))


def _has_overlap(trades: pd.DataFrame) -> bool:
    if trades.empty:
        return False
    ordered = trades.sort_values("entry_bar_index")
    previous_exit: int | None = None
    for _, row in ordered.iterrows():
        entry = int(row["entry_bar_index"])
        if previous_exit is not None and entry <= previous_exit:
            return True
        previous_exit = int(row["exit_bar_index"])
    return False


def _standardize_equity(equity: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(equity, pd.DataFrame) or equity.empty:
        return pd.DataFrame(columns=RANDOM_BASELINE_EQUITY_COLUMNS)
    out = equity.copy()
    result = pd.DataFrame(
        {
            "bar_index": pd.to_numeric(out["bar_index"], errors="coerce").astype("Int64"),
            "time": out.get("bar_open_time_bjt"),
            "equity": pd.to_numeric(out["equity_after"], errors="coerce"),
            "drawdown": pd.to_numeric(out["drawdown_pct"], errors="coerce"),
        }
    )
    return result.dropna(subset=["bar_index", "equity"]).reset_index(drop=True)


def _median_equity_curve(curves: list[pd.DataFrame]) -> pd.DataFrame:
    if not curves:
        return pd.DataFrame(columns=RANDOM_BASELINE_EQUITY_COLUMNS)
    indexed = [
        curve.set_index("bar_index")["equity"].rename(f"run_{i}")
        for i, curve in enumerate(curves)
    ]
    median = pd.concat(indexed, axis=1).median(axis=1).sort_index()
    first = curves[0].drop_duplicates("bar_index").set_index("bar_index")
    result = pd.DataFrame({"bar_index": median.index.astype(int), "equity": median.values})
    result["time"] = result["bar_index"].map(first["time"].to_dict())
    peak = result["equity"].cummax()
    result["drawdown"] = (result["equity"] / peak - 1.0) * 100.0
    return result[["bar_index", "time", "equity", "drawdown"]].reset_index(drop=True)


def _median_summary(median_equity: pd.DataFrame) -> dict[str, Any]:
    if median_equity.empty:
        return {}
    return {
        "final_equity": float(median_equity["equity"].iloc[-1]),
        "min_equity": float(median_equity["equity"].min()),
        "max_drawdown_pct": float(median_equity["drawdown"].min()),
    }


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "DEFAULT_RANDOM_BASELINE_SEED",
    "DEFAULT_RANDOM_BASELINE_SIMULATIONS",
    "FixedRandomEntryStrategy",
    "RandomBaselineConfig",
    "RandomBaselineResult",
    "run_random_entry_baseline",
]
