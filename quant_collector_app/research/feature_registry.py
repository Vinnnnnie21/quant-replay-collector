from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


FEATURE_VERSION = "research_features_v1.0"


@dataclass(frozen=True)
class FeatureDefinition:
    feature_name: str
    category: str
    description: str
    formula: str
    required_window: str
    uses_future_data: bool = False
    model_input_allowed: bool = True
    missing_policy: str = "NaN when required history is unavailable"
    expected_direction: str = "research dependent"
    notes: str = ""


FEATURE_DEFINITIONS = [
    FeatureDefinition("body_pct", "price_shape", "Absolute candle body divided by open.", "abs(close-open)/open", "event"),
    FeatureDefinition("body_to_range", "price_shape", "Absolute candle body divided by high-low range.", "abs(close-open)/(high-low)", "event"),
    FeatureDefinition("upper_wick_ratio", "price_shape", "Upper wick share of candle range.", "(high-max(open,close))/(high-low)", "event"),
    FeatureDefinition("lower_wick_ratio", "price_shape", "Lower wick share of candle range.", "(min(open,close)-low)/(high-low)", "event"),
    FeatureDefinition("upper_wick_atr_ratio", "price_shape", "Upper wick scaled by ATR.", "upper_wick/atr_14", "14 bars"),
    FeatureDefinition("lower_wick_atr_ratio", "price_shape", "Lower wick scaled by ATR.", "lower_wick/atr_14", "14 bars"),
    FeatureDefinition("close_position", "price_shape", "Close position inside candle range.", "(close-low)/(high-low)", "event"),
    FeatureDefinition("range_pct", "price_shape", "Candle range divided by open.", "(high-low)/open", "event"),
    FeatureDefinition("range_atr_ratio", "price_shape", "Candle range scaled by ATR.", "(high-low)/atr_14", "14 bars"),
    FeatureDefinition("body_atr_ratio", "price_shape", "Candle body scaled by ATR.", "abs(close-open)/atr_14", "14 bars"),
    FeatureDefinition("log_ret_1", "prior_trend", "Event-close log return from preceding close.", "log(event_close/previous_close)", "2 bars"),
    FeatureDefinition("pre_ret_3", "prior_trend", "Simple return in preceding three bars.", "pre_close[-1]/pre_close[-3]-1", "3 pre bars"),
    FeatureDefinition("pre_ret_5", "prior_trend", "Simple return in preceding five bars.", "pre_close[-1]/pre_close[-5]-1", "5 pre bars"),
    FeatureDefinition("pre_ret_10", "prior_trend", "Simple return in preceding ten bars.", "pre_close[-1]/pre_close[-10]-1", "10 pre bars"),
    FeatureDefinition("pre_ret_20", "prior_trend", "Simple return in preceding twenty bars.", "pre_close[-1]/pre_close[-20]-1", "20 pre bars"),
    FeatureDefinition("pre_log_ret_5", "prior_trend", "Log return in preceding five bars.", "log(pre_close[-1]/pre_close[-5])", "5 pre bars"),
    FeatureDefinition("pre_log_ret_10", "prior_trend", "Log return in preceding ten bars.", "log(pre_close[-1]/pre_close[-10])", "10 pre bars"),
    FeatureDefinition("down_run_length", "prior_trend", "Consecutive down candles immediately before event.", "trailing_count(close<open)", "pre bars"),
    FeatureDefinition("up_run_length", "prior_trend", "Consecutive up candles immediately before event.", "trailing_count(close>open)", "pre bars"),
    FeatureDefinition("trend_slope_20", "prior_trend", "OLS slope of preceding log closes.", "slope(log(pre_close), index)", "20 pre bars"),
    FeatureDefinition("distance_to_prev_high_20", "prior_trend", "Event close distance from preceding high.", "event_close/prev_high_20-1", "20 pre bars"),
    FeatureDefinition("distance_to_prev_low_20", "prior_trend", "Event close distance from preceding low.", "event_close/prev_low_20-1", "20 pre bars"),
    FeatureDefinition("break_prev_high_20", "prior_trend", "Event high exceeds preceding high.", "event_high>prev_high_20", "20 pre bars"),
    FeatureDefinition("break_prev_low_20", "prior_trend", "Event low breaches preceding low.", "event_low<prev_low_20", "20 pre bars"),
    FeatureDefinition("reclaim_prev_low_20", "prior_trend", "Broken prior low is reclaimed at event close.", "break_prev_low_20 and close>prev_low_20", "20 pre bars"),
    FeatureDefinition("reject_prev_high_20", "prior_trend", "Broken prior high is rejected at event close.", "break_prev_high_20 and close<prev_high_20", "20 pre bars"),
    FeatureDefinition("break_depth", "prior_trend", "Depth below prior low when breached.", "(prev_low_20-event_low)/prev_low_20", "20 pre bars"),
    FeatureDefinition("reclaim_strength", "prior_trend", "Close distance above prior low after breach.", "(event_close-prev_low_20)/prev_low_20", "20 pre bars"),
    FeatureDefinition("true_range", "volatility", "Event true range versus preceding close.", "max(high-low,abs(high-prev_close),abs(low-prev_close))", "2 bars"),
    FeatureDefinition("atr_14", "volatility", "Average true range through event bar.", "mean(true_range,14)", "14 bars"),
    FeatureDefinition("realized_vol_20", "volatility", "Volatility of preceding log returns.", "std(log_return,20)", "20 pre bars"),
    FeatureDefinition("realized_vol_50", "volatility", "Volatility of preceding log returns.", "std(log_return,50)", "50 pre bars"),
    FeatureDefinition("volatility_regime", "volatility", "Bucket derived from realised volatility.", "bucket(realized_vol_20)", "20 pre bars"),
    FeatureDefinition("range_zscore_20", "volatility", "Event range z-score versus prior ranges.", "zscore(event_range,pre_range_20)", "20 pre bars"),
    FeatureDefinition("volume_ratio_5", "volume", "Event volume divided by preceding mean volume.", "volume/mean(pre_volume_5)", "5 pre bars"),
    FeatureDefinition("volume_ratio_20", "volume", "Event volume divided by preceding mean volume.", "volume/mean(pre_volume_20)", "20 pre bars"),
    FeatureDefinition("volume_zscore_20", "volume", "Event volume z-score versus prior volume.", "zscore(volume,pre_volume_20)", "20 pre bars"),
    FeatureDefinition("quote_volume_proxy", "volume", "Event close times base volume.", "close*volume", "event"),
    FeatureDefinition("quote_volume_zscore_20", "volume", "Quote-volume proxy z-score.", "zscore(close*volume,pre_close*pre_volume)", "20 pre bars"),
    FeatureDefinition("volume_climax_score", "volume", "Large range and volume composite.", "mean(norm(volume_ratio_20),norm(range_atr_ratio))", "20 pre bars"),
    FeatureDefinition("volume_absorption_score", "volume", "Large volume with reclaimed lower break composite.", "mean(norm(volume_ratio_20),reclaim_prev_low_20,close_position)", "20 pre bars"),
    FeatureDefinition("volume_dump_score", "volume", "Prior fall plus event volume composite.", "mean(norm(-pre_ret_10),norm(volume_ratio_20))", "20 pre bars"),
    FeatureDefinition("reversal_candle_score", "composite", "Lower wick and strong close composite.", "mean(lower_wick_ratio,close_position,body_to_range)", "14 bars"),
    FeatureDefinition("panic_drop_score", "composite", "Prior decline, range and volume composite.", "mean(norm(-pre_ret_10),norm(range_atr_ratio),norm(volume_ratio_20))", "20 pre bars"),
    FeatureDefinition("false_breakdown_score", "composite", "Prior-low breach followed by reclaim.", "mean(break_prev_low_20,reclaim_prev_low_20,close_position)", "20 pre bars"),
    FeatureDefinition("fake_breakout_score", "composite", "Prior-high breach followed by rejection.", "mean(break_prev_high_20,reject_prev_high_20,1-close_position)", "20 pre bars"),
    FeatureDefinition("hour_of_day", "time_state", "Event hour in Beijing time.", "hour(open_time_bjt)", "event"),
    FeatureDefinition("day_of_week", "time_state", "Event weekday in Beijing time.", "weekday(open_time_bjt)", "event"),
    FeatureDefinition("time_session", "time_state", "Event Beijing-time trading-session bucket.", "bucket(hour_of_day)", "event"),
    FeatureDefinition("trend_regime", "time_state", "Prior trend slope bucket for grouped analysis.", "bucket(trend_slope_20)", "20 pre bars"),
    FeatureDefinition("premium_avg_pct", "premium", "Last observed premium at or before event.", "asof(premium_avg_pct)", "optional premium history"),
    FeatureDefinition("premium_change_3", "premium", "Change across latest three prior premium observations.", "premium[-1]-premium[-3]", "optional premium history"),
    FeatureDefinition("premium_zscore_50", "premium", "Latest premium z-score over prior samples.", "zscore(premium[-1],premium[-50:])", "optional premium history"),
    FeatureDefinition("premium_spread", "premium", "Sell premium minus buy premium.", "sell_premium_pct-buy_premium_pct", "optional premium history"),
]


def feature_registry_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(item) for item in FEATURE_DEFINITIONS])


def model_input_features() -> list[str]:
    return [item.feature_name for item in FEATURE_DEFINITIONS if item.model_input_allowed and not item.uses_future_data]
