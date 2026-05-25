from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


LABEL_VERSION = "research_labels_v1.0"


@dataclass(frozen=True)
class LabelDefinition:
    label_name: str
    category: str
    description: str
    formula: str
    requires_future_data: bool = True
    model_input_allowed: bool = False
    notes: str = ""


LABEL_DEFINITIONS = [
    LabelDefinition(f"fwd_ret_{n}", "future_return", f"Return at post-event bar {n}.", f"close[t+{n}]/close[t]-1")
    for n in (1, 3, 5, 10, 20)
] + [
    LabelDefinition(f"fwd_ret_{n}_side_adj", "future_return", f"Direction-adjusted return at bar {n}.", f"fwd_ret_{n}*side_sign")
    for n in (1, 3, 5, 10, 20)
] + [
    LabelDefinition(f"mfe_{n}", "path", f"Maximum favourable excursion through bar {n}.", "max(direction_adjusted_excursion)")
    for n in (5, 10, 20)
] + [
    LabelDefinition(f"mae_{n}", "path", f"Maximum adverse excursion through bar {n}.", "min(direction_adjusted_excursion)")
    for n in (5, 10, 20)
] + [
    LabelDefinition("time_to_mfe_10", "path", "Bars until maximum favourable excursion within ten bars.", "argmax(favourable_excursion_1_10)"),
    LabelDefinition("time_to_mae_10", "path", "Bars until maximum adverse excursion within ten bars.", "argmin(adverse_excursion_1_10)"),
    LabelDefinition("hit_tp_1pct_before_sl_1pct", "path", "Whether a 1 percent target occurs before a 1 percent stop.", "first_hit(tp=1%,sl=1%)"),
    LabelDefinition("hit_tp_2pct_before_sl_1pct", "path", "Whether a 2 percent target occurs before a 1 percent stop.", "first_hit(tp=2%,sl=1%)"),
    LabelDefinition("good_reversal", "classification", "Positive ten-bar rebound with controlled adverse path.", "fwd_ret_10_side_adj>0 and mae_10>-1%"),
    LabelDefinition("failed_reversal", "classification", "Non-positive ten-bar outcome after material adverse movement.", "fwd_ret_10_side_adj<=0 and mae_10<=-1%"),
    LabelDefinition("strong_rebound", "classification", "Direction-adjusted ten-bar return at least one percent.", "fwd_ret_10_side_adj>=1%"),
    LabelDefinition("clean_trade", "classification", "Favourable excursion dominates limited adverse excursion.", "mfe_10>=1% and mae_10>-0.5%"),
    LabelDefinition("trap_move", "classification", "Weak favourable movement followed by material adverse movement.", "mfe_10<0.5% and mae_10<=-1%"),
    LabelDefinition("manual_win", "manual_trade", "Whether recorded manual trade return is positive.", "manual_return>0"),
    LabelDefinition("manual_return", "manual_trade", "Recorded manual closed-trade return.", "net_return_pct or final_return_pct"),
    LabelDefinition("manual_holding_bars", "manual_trade", "Recorded manual holding duration.", "holding_bars"),
]


def label_registry_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(item) for item in LABEL_DEFINITIONS])


def _num(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _ret(base: float, value: float) -> float:
    return (value / base) - 1.0 if math.isfinite(base) and base != 0 and math.isfinite(value) else math.nan


def _binary(condition: bool, available: bool) -> float:
    return float(bool(condition)) if available else math.nan


class LabelFactory:
    def build(
        self,
        event_windows: pd.DataFrame,
        trade_events: pd.DataFrame | None = None,
        trades: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        windows = event_windows.copy() if isinstance(event_windows, pd.DataFrame) else pd.DataFrame()
        events = trade_events.copy() if isinstance(trade_events, pd.DataFrame) else pd.DataFrame()
        trades = trades.copy() if isinstance(trades, pd.DataFrame) else pd.DataFrame()
        columns = ["event_id", *label_registry_frame()["label_name"].tolist()]
        if windows.empty or "event_id" not in windows.columns:
            return pd.DataFrame(columns=columns)
        event_map = {}
        if not events.empty and "event_id" in events.columns:
            event_map = {str(row["event_id"]): row.to_dict() for _, row in events.iterrows()}
        trade_map = {}
        if not trades.empty and "trade_id" in trades.columns:
            trade_map = {str(row["trade_id"]): row.to_dict() for _, row in trades.iterrows()}
        rows = []
        for event_id, group in windows.groupby("event_id", dropna=False):
            event_id = str(event_id)
            group = group.copy()
            group["offset"] = pd.to_numeric(group["offset"], errors="coerce")
            group = group.sort_values("offset")
            event_rows = group[group["offset"] == 0]
            if event_rows.empty:
                continue
            event_row = event_rows.iloc[-1]
            base = _num(event_row.get("close"))
            meta = event_map.get(event_id, {})
            side = str(meta.get("side") or event_row.get("side") or "LONG").upper()
            direction = -1.0 if side == "SHORT" else 1.0
            post = group[group["offset"] > 0].copy()
            row = {"event_id": event_id}
            for horizon in (1, 3, 5, 10, 20):
                target = post[post["offset"] == horizon]
                raw = _ret(base, _num(target.iloc[-1].get("close"))) if not target.empty else math.nan
                row[f"fwd_ret_{horizon}"] = raw
                row[f"fwd_ret_{horizon}_side_adj"] = raw * direction if math.isfinite(raw) else math.nan
            for horizon in (5, 10, 20):
                subset = post[post["offset"] <= horizon]
                favourable = []
                adverse = []
                for _, bar in subset.iterrows():
                    high_ret = _ret(base, _num(bar.get("high")))
                    low_ret = _ret(base, _num(bar.get("low")))
                    if direction > 0:
                        favourable.append(high_ret)
                        adverse.append(low_ret)
                    else:
                        favourable.append(-low_ret if math.isfinite(low_ret) else math.nan)
                        adverse.append(-high_ret if math.isfinite(high_ret) else math.nan)
                valid_f = [v for v in favourable if math.isfinite(v)]
                valid_a = [v for v in adverse if math.isfinite(v)]
                row[f"mfe_{horizon}"] = max(valid_f) if valid_f else math.nan
                row[f"mae_{horizon}"] = min(valid_a) if valid_a else math.nan
                if horizon == 10:
                    row["time_to_mfe_10"] = float(np.nanargmax(favourable) + 1) if valid_f else math.nan
                    row["time_to_mae_10"] = float(np.nanargmin(adverse) + 1) if valid_a else math.nan
            row["hit_tp_1pct_before_sl_1pct"] = self._hit_target_first(post, base, direction, 0.01, 0.01)
            row["hit_tp_2pct_before_sl_1pct"] = self._hit_target_first(post, base, direction, 0.02, 0.01)
            fwd10 = row["fwd_ret_10_side_adj"]
            mfe10 = row["mfe_10"]
            mae10 = row["mae_10"]
            has_path = all(math.isfinite(value) for value in (fwd10, mfe10, mae10))
            row["good_reversal"] = _binary(fwd10 > 0 and mae10 > -0.01, has_path)
            row["failed_reversal"] = _binary(fwd10 <= 0 and mae10 <= -0.01, has_path)
            row["strong_rebound"] = _binary(fwd10 >= 0.01, math.isfinite(fwd10))
            row["clean_trade"] = _binary(mfe10 >= 0.01 and mae10 > -0.005, has_path)
            row["trap_move"] = _binary(mfe10 < 0.005 and mae10 <= -0.01, has_path)
            trade = trade_map.get(str(meta.get("trade_id") or ""))
            manual_return = math.nan
            holding = math.nan
            if trade and str(trade.get("status") or "").upper() == "CLOSED":
                manual_return = _num(
                    trade.get("net_return_pct")
                    if trade.get("net_return_pct") is not None
                    else trade.get("final_return_pct")
                )
                holding = _num(trade.get("holding_bars"))
            row["manual_return"] = manual_return
            row["manual_holding_bars"] = holding
            row["manual_win"] = _binary(manual_return > 0, math.isfinite(manual_return))
            rows.append(row)
        return pd.DataFrame(rows).reindex(columns=columns)

    @staticmethod
    def _hit_target_first(post: pd.DataFrame, base: float, direction: float, tp: float, sl: float) -> float:
        if not math.isfinite(base) or post.empty:
            return math.nan
        for _, bar in post.sort_values("offset").iterrows():
            high_ret = _ret(base, _num(bar.get("high")))
            low_ret = _ret(base, _num(bar.get("low")))
            if direction > 0:
                target_hit = math.isfinite(high_ret) and high_ret >= tp
                stop_hit = math.isfinite(low_ret) and low_ret <= -sl
            else:
                target_hit = math.isfinite(low_ret) and low_ret <= -tp
                stop_hit = math.isfinite(high_ret) and high_ret >= sl
            if stop_hit:
                return 0.0
            if target_hit:
                return 1.0
        return 0.0
