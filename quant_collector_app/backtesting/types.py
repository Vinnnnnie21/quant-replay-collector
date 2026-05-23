from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


class Signal:
    HOLD = "HOLD"
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"


@dataclass
class BacktestConfig:
    initial_equity: float = 10000.0
    notional_quote: float = 1000.0
    fee_bps: float = 4.0
    slippage_bps: float = 1.0
    fill_mode: str = "CLOSE"
    signal_timing: str = "next_open"
    allow_short: bool = True
    single_position: bool = True
    max_bars_hold: int | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    metrics: dict
    config: dict
    strategy_name: str
    warnings: list[str]
