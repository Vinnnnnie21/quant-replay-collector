from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

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
    maker_fee_bps: float | None = None
    taker_fee_bps: float | None = None
    slippage_bps: float = 1.0
    fill_mode: str = "CLOSE"
    signal_timing: str = "next_open"
    allow_short: bool = True
    single_position: bool = True
    max_bars_hold: int | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    stop_take_priority: str = "stop_first"
    funding_fee_bps: float = 0.0
    funding_rate_series: Any = None
    entry_liquidity: str = "taker"
    exit_liquidity: str = "taker"

    def to_dict(self) -> dict:
        result = asdict(self)
        series = result.pop("funding_rate_series", None)
        result["funding_rate_series_provided"] = series is not None
        return result

    def fee_for_liquidity(self, liquidity: str) -> float:
        if str(liquidity or "").lower() == "maker" and self.maker_fee_bps is not None:
            return float(self.maker_fee_bps)
        if str(liquidity or "").lower() == "taker" and self.taker_fee_bps is not None:
            return float(self.taker_fee_bps)
        return float(self.fee_bps)


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    metrics: dict
    config: dict
    strategy_name: str
    warnings: list[str]
