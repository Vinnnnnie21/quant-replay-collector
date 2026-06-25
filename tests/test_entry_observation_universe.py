from __future__ import annotations

import pandas as pd
import pytest

from research.entry_observation_universe import OBSERVATION_COLUMNS, generate_entry_observation_universe


def _deep_v_like_klines() -> pd.DataFrame:
    rows = []
    for position, bar_index in enumerate(range(100, 130)):
        close = 120.0 - position * 0.85
        rows.append(
            {
                "open_time": f"2026-06-18T10:{position:02d}:00+08:00",
                "open": close + 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100.0,
            }
        )
    rows[25].update(
        {
            "open": 97.0,
            "high": 101.5,
            "low": 90.0,
            "close": 100.0,
            "volume": 420.0,
        }
    )
    return pd.DataFrame(rows, index=range(100, 130))


def _confirmation_klines() -> pd.DataFrame:
    frame = _deep_v_like_klines()
    frame.loc[125, ["open", "high", "low", "close", "volume"]] = [97.0, 101.5, 90.0, 96.0, 420.0]
    frame.loc[126, ["open", "high", "low", "close", "volume"]] = [96.5, 105.0, 96.0, 104.5, 260.0]
    return frame


def test_empty_dataframe_returns_empty_observations():
    result = generate_entry_observation_universe(
        pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"]),
        symbol="BTCUSDT",
        interval="1m",
    )

    assert result.empty
    assert list(result.columns) == OBSERVATION_COLUMNS


def test_missing_required_ohlcv_columns_raise_clear_error():
    with pytest.raises(ValueError, match="Missing kline columns: high, volume"):
        generate_entry_observation_universe(
            pd.DataFrame({"open_time": ["2026-06-18T10:00:00+08:00"], "open": [1], "low": [1], "close": [1]}),
            symbol="BTCUSDT",
            interval="1m",
        )


def test_generates_stable_observation_id_and_preserves_bar_index():
    klines = _deep_v_like_klines()

    first = generate_entry_observation_universe(klines, symbol="BTCUSDT", interval="1m")
    second = generate_entry_observation_universe(klines, symbol="BTCUSDT", interval="1m")

    assert not first.empty
    candidate = first[first["bar_index"] == 125].iloc[0]
    assert candidate["observation_id"] == second[second["bar_index"] == 125].iloc[0]["observation_id"]
    assert candidate["symbol"] == "BTCUSDT"
    assert candidate["interval"] == "1m"
    assert candidate["bar_time"] == "2026-06-18T10:25:00+08:00"
    assert candidate["eligible_for_review"] is True
    assert candidate["decision_timing"] == "CURRENT_BAR_CLOSE"
    assert candidate["source"] == "ENTRY_OBSERVATION_CANDIDATE"
    assert candidate["candidate_source"] == "rule_seeded"
    assert candidate["setup_bar_index"] == 125
    assert candidate["decision_bar_index"] == 125
    assert candidate["feature_cutoff_bar_index"] == 125
    assert candidate["feature_timing_policy"] == "current_bar_close"
    assert candidate["candle_id"]
    assert candidate["data_version"].startswith("kline_")


def test_shuffled_klines_are_ordered_before_candidate_generation():
    ordered = generate_entry_observation_universe(_deep_v_like_klines(), symbol="BTCUSDT", interval="1m")
    shuffled = generate_entry_observation_universe(
        _deep_v_like_klines().sample(frac=1.0, random_state=11),
        symbol="BTCUSDT",
        interval="1m",
    )

    assert shuffled["observation_id"].tolist() == ordered["observation_id"].tolist()
    assert shuffled["decision_bar_index"].tolist() == ordered["decision_bar_index"].tolist()


def test_next_bar_confirmation_keeps_setup_and_decision_bar_separate():
    result = generate_entry_observation_universe(
        _confirmation_klines(),
        symbol="BTCUSDT",
        interval="1m",
        lower_shadow_ratio_threshold=0.8,
    )

    candidate = result[result["decision_timing"] == "NEXT_BAR_CONFIRMATION"].iloc[0]
    assert candidate["setup_bar_index"] == 125
    assert candidate["decision_bar_index"] == 126
    assert candidate["feature_cutoff_bar_index"] == 125
    assert candidate["feature_timing_policy"] == "setup_bar_only"
    assert candidate["bar_index"] == 126
    assert candidate["setup_bar_time"] == "2026-06-18T10:25:00+08:00"
    assert candidate["decision_bar_time"] == "2026-06-18T10:26:00+08:00"
    assert "bullish_confirmation" in candidate["candidate_reason"]


def test_generation_uses_only_current_and_prior_bars():
    klines = _deep_v_like_klines()
    changed_future = klines.copy()
    changed_future.loc[126:, ["open", "high", "low", "close", "volume"]] = [9999.0, 9999.0, 9999.0, 9999.0, 9999.0]

    base = generate_entry_observation_universe(klines, symbol="BTCUSDT", interval="1m")
    mutated = generate_entry_observation_universe(changed_future, symbol="BTCUSDT", interval="1m")

    visible_columns = [
        "symbol",
        "interval",
        "bar_index",
        "bar_time",
        "setup_bar_index",
        "decision_bar_index",
        "feature_cutoff_bar_index",
        "feature_timing_policy",
        "candidate_source",
        "eligible_for_review",
        "candidate_reason",
        "decision_timing",
        "source",
    ]
    assert base.loc[base["bar_index"] <= 125, visible_columns].reset_index(drop=True).equals(
        mutated.loc[mutated["bar_index"] <= 125, visible_columns].reset_index(drop=True)
    )


def test_output_excludes_future_outcomes_and_signal_fields():
    klines = _deep_v_like_klines().assign(
        fwd_ret_10=999.0,
        future_return=999.0,
        MFE=999.0,
        MAE=-999.0,
        hit_tp=1,
        hit_sl=0,
        buy_signal=True,
        sell_signal=False,
    )

    result = generate_entry_observation_universe(klines, symbol="BTCUSDT", interval="1m")
    lowered_columns = [column.lower() for column in result.columns]

    assert not any(
        any(token in column for token in ("fwd_", "future", "mfe", "mae", "hit_tp", "hit_sl", "buy_signal", "sell_signal"))
        for column in lowered_columns
    )


def test_candidates_are_review_filter_not_trading_advice():
    result = generate_entry_observation_universe(_deep_v_like_klines(), symbol="BTCUSDT", interval="1m")

    assert not result.empty
    assert set(result["eligible_for_review"]) == {True}
    assert all("review" in reason for reason in result["candidate_reason"].astype(str))
    assert not any(
        token in text.lower()
        for text in " ".join(result.astype(str).to_numpy().ravel())
        for token in ("buy_signal", "sell_signal", "trade_signal", "trade_advice")
    )


def test_duplicate_bar_index_or_open_time_is_rejected():
    duplicate_index = _deep_v_like_klines().reset_index(drop=True)
    duplicate_index["bar_index"] = list(range(len(duplicate_index)))
    duplicate_index.loc[5, "bar_index"] = duplicate_index.loc[4, "bar_index"]

    with pytest.raises(ValueError, match="duplicate bar_index"):
        generate_entry_observation_universe(duplicate_index, symbol="BTCUSDT", interval="1m")

    duplicate_time = _deep_v_like_klines()
    duplicate_time.iloc[5, duplicate_time.columns.get_loc("open_time")] = duplicate_time.iloc[4]["open_time"]

    with pytest.raises(ValueError, match="duplicate open_time"):
        generate_entry_observation_universe(duplicate_time, symbol="BTCUSDT", interval="1m")
